"""OracleEngine — thin orchestrator for the Hestia Oracle service.

This module's only responsibility is to wire together the specialised
services and orchestrate the two main user-facing flows:

  1. chat()             — conversational + domain-query loop (NDJSON stream)
  2. analyze_document() — file analysis + background RAG archiving (NDJSON stream)

All business logic lives in the imported service/document modules.
"""
import json
import logging
import os
import time

from core.services.agent_factory import AgentFactory, conversation_style_contract
from core.services.hub_client import HubClient
from core.services.chat_classifier import ChatClassifier, QUICK_CHAT_CONFIDENCE_THRESHOLD
from core.services import stream_emitter
from core.services.context_builder import ContextBuilder
from core.services.memory_service import MemoryService
from core.services.module_registry import ModuleToolRegistry
from core.services.retrieval_service import RetrievalService
from core.document.archiver import DocumentArchiver
from core.document.rag import DocumentRAG
from core.document.analyser import DocumentAnalyser

logger = logging.getLogger(__name__)


class OracleEngine:
    """Top-level orchestrator — instantiate once per process."""

    def __init__(self) -> None:
        self._hub_url = os.getenv(
            "HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
        self._archive_url = os.getenv(
            "ARCHIVE_API_URL", "http://hestia_archive:19002/api")

        # ── LLM agents ────────────────────────────────────────────────────────
        self._agents = AgentFactory.create()

        # ── Infrastructure services ───────────────────────────────────────────
        self._hub = HubClient(self._hub_url)

        self._context_builder = ContextBuilder(
            max_history_messages=int(os.getenv("ORACLE_HISTORY_LIMIT", "6")),
            max_history_chars=int(
                os.getenv("ORACLE_HISTORY_CHAR_LIMIT", "500")),
            max_entities_in_context=int(
                os.getenv("ORACLE_CONTEXT_ENTITIES_LIMIT", "12")),
            max_field_chars=int(
                os.getenv("ORACLE_CONTEXT_FIELD_CHAR_LIMIT", "280")),
        )

        module_tool_urls = [
            u.strip()
            for u in os.getenv("MODULE_TOOLS_URLS", "").split(",")
            if u.strip()
        ]
        if single := os.getenv("MODULE_TOOLS_URL", "").strip():
            module_tool_urls.append(single)

        self._module_registry = ModuleToolRegistry(
            module_tool_urls=module_tool_urls,
            ttl_seconds=int(
                os.getenv("MODULE_TOOL_REGISTRY_TTL_SECONDS", "120")),
            hub_api_url=self._hub_url,
        )

        self._retrieval_service = RetrievalService(
            archive_url=self._archive_url,
            hub_api_url=self._hub_url,
            module_registry=self._module_registry,
            embedder=self._embed,
        )

        self._memory_service = MemoryService(
            archive_url=self._archive_url,
            hub_api_url=self._hub_url,
            scribe_agent=self._agents.scribe,
            fallback_scribe_agent=self._agents.fallback_scribe,
            context_builder=self._context_builder,
        )

        self._classifier = ChatClassifier(
            router_agent=self._agents.router,
            fallback_router_agent=self._agents.fallback_router,
        )

        # ── Document pipeline ─────────────────────────────────────────────────
        self._archiver = DocumentArchiver(
            hub_client=self._hub,
            embed_fn=self._embed,
            analyst=self._agents.analyst,
            fallback_analyst=self._agents.fallback_analyst,
        )

        self._doc_rag = DocumentRAG(
            hub_client=self._hub,
            embed_fn=self._embed,
        )

        self._doc_analyser = DocumentAnalyser(
            hub_client=self._hub,
            archiver=self._archiver,
            analyst=self._agents.analyst,
            fallback_analyst=self._agents.fallback_analyst,
            style_contract_fn=conversation_style_contract,
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def chat(
        self,
        user_message: str,
        session_id: str,
        notify_target: str | None = None,
        force_notification_compiler: bool = False,
        client_instructions: str | None = None,
    ):
        """Main conversational loop. Yields NDJSON lines."""
        t0 = time.perf_counter()
        logger.info("Chat | session=%s msg_len=%s",
                    session_id, len(user_message or ""))

        yield stream_emitter.emit_status("📂 Recupero cronologia e routing...")

        history_data = self._hub.get(
            f"/chat/history/{session_id}?limit={self._context_builder.max_history_messages}"
        )
        history_text = self._context_builder.compact_history(history_data)

        available_domains = self._hub.get("/domains") or ["general"]
        schemas = self._hub.get("/schemas") or {}

        mode, explicit_domain, confidence, valid_domains, filters, filters_gt, filters_lt, sort_by, sort_order = (
            self._classifier.classify(
                user_message, history_text, available_domains, schemas)
        )
        logger.info("Classify | mode=%s domain=%s conf=%.2f",
                    mode, explicit_domain, confidence)

        # ── Quick chat path ───────────────────────────────────────────────────
        if mode == "quick_chat" and confidence >= QUICK_CHAT_CONFIDENCE_THRESHOLD:
            yield stream_emitter.emit_status("💬 Conversazione rapida...")

            extra_context = ""
            if self._doc_rag.message_is_about_docs(user_message):
                extra_context = self._doc_rag.list_user_docs_brief(
                    chat_id=notify_target, session_id=session_id
                )

            answer = self._quick_answer(
                user_message, history_text, client_instructions, extra_context or None)
            self._save_history(session_id, user_message, answer)
            logger.info("Quick chat done in %sms", int(
                (time.perf_counter() - t0) * 1000))
            yield stream_emitter.emit_final(answer, "general")
            return

        # ── Domain query path ─────────────────────────────────────────────────
        if explicit_domain and explicit_domain not in valid_domains:
            valid_domains = [explicit_domain] + \
                [d for d in valid_domains if d != explicit_domain]

        yield stream_emitter.emit_status(f"🧠 Analisi domini: {', '.join(valid_domains)}...")
        yield stream_emitter.emit_status("🧾 Recupero preferenze attive...")

        all_prefs = self._load_preferences(valid_domains)
        preference_facts = [str(p.get("fact", "")).strip()
                            for p in all_prefs if p.get("fact")]

        yield stream_emitter.emit_status("🔎 Recupero entità dai moduli/Archive...")
        all_entities = self._retrieval_service.retrieve_entities(
            user_message=user_message,
            session_id=session_id,
            valid_domains=valid_domains,
            preference_facts=preference_facts,
            active_filters=filters,
            filters_gt=filters_gt,
            filters_lt=filters_lt,
            sort_by=sort_by,
            sort_order=sort_order,
        )

        yield stream_emitter.emit_status("🧱 Compattazione contesto...")
        formatted_context = self._context_builder.compact_entities_for_prompt(
            all_entities)

        # Inject relevant document chunks
        doc_chunks = self._doc_rag.search_relevant_chunks(
            user_message, notify_target, session_id)
        if doc_chunks:
            doc_section = DocumentRAG.format_chunks_for_prompt(doc_chunks)
            formatted_context = f"{formatted_context}\n\n{doc_section}".strip(
            ) if formatted_context else doc_section
        elif self._doc_rag.message_is_about_docs(user_message):
            brief = self._doc_rag.list_user_docs_brief(
                chat_id=notify_target, session_id=session_id)
            if brief:
                formatted_context = f"{formatted_context}\n\n{brief}".strip(
                ) if formatted_context else brief

        analysis_prompt = self._context_builder.build_analysis_prompt(
            preference_facts=preference_facts,
            valid_domains=valid_domains,
            active_filters=filters,
            filters_gt=filters_gt,
            filters_lt=filters_lt,
            sort_by=sort_by,
            sort_order=sort_order,
            formatted_context=formatted_context,
            history_text=history_text,
            user_message=user_message,
        )
        analysis_prompt += f"\n\n{conversation_style_contract()}"
        if client_instructions and str(client_instructions).strip():
            analysis_prompt += f"\n\nCLIENT_INSTRUCTIONS:\n{str(client_instructions).strip()}"

        yield stream_emitter.emit_status("🧠 Sintesi finale in corso...")
        answer = self._ask_analyst(analysis_prompt)

        self._save_history(session_id, user_message, answer)

        yield stream_emitter.emit_status("🔔 Aggiornamento preferenze e notifiche...")
        try:
            signals = self._memory_service.extract_and_save_preferences(
                user_message, session_id,
                notify_target=notify_target,
                force_notification_compiler=force_notification_compiler,
            )
            for signal in signals or []:
                yield stream_emitter.emit_signal(
                    event=str(signal.get("event", "info")),
                    message=str(signal.get(
                        "message", "Aggiornamento eseguito.")),
                    data=signal.get("data") or {},
                )
        except Exception as exc:
            logger.warning("Memory sync failed: %s", exc)

        logger.info("Chat done | session=%s total=%sms", session_id,
                    int((time.perf_counter() - t0) * 1000))
        yield stream_emitter.emit_final(answer, valid_domains[0])

    def analyze_document(
        self,
        file_bytes: bytes,
        mime_type: str,
        user_message: str,
        session_id: str,
        notify_target: str | None = None,
        client_instructions: str | None = None,
        filename: str | None = None,
    ):
        """Analyse an uploaded file and yield NDJSON lines."""
        yield from self._doc_analyser.analyse(
            file_bytes=file_bytes,
            mime_type=mime_type,
            user_message=user_message,
            session_id=session_id,
            notify_target=notify_target,
            client_instructions=client_instructions,
            filename=filename,
            analyst_model_name=self._agents.analyst_model_name,
        )

    def format_payload(
        self,
        command: str,
        payload: object,
        response_prompt: str | None = None,
        client_instructions: str | None = None,
    ) -> str:
        """Ask the analyst to format a structured service payload as human text."""
        payload_text = json.dumps(payload, ensure_ascii=False, indent=2)
        is_alert = str(command or "").startswith("alert:")

        if is_alert:
            prompt = (
                "Sei Hestia e stai PROATTIVAMENTE informando l'utente. "
                "Scrivi come se TU stessi iniziando una conversazione per condividere qualcosa di rilevante. "
                "Sii naturale, entusiasta ma preciso. "
                "Usa HTML per formattazione (grassetto <b>, link <a href>). "
                "Per i link, usa SEMPRE il titolo/descrizione dell'elemento come testo del link, MAI testi generici. "
                "Non inventare dati. NON usare saluti introduttivi come 'Ciao' o 'Ecco'. "
                f"COMMAND: {command}\nSERVICE_PAYLOAD:\n{payload_text}\n"
            )
        else:
            prompt = (
                "Sei Hestia. Trasforma il payload strutturato in una risposta chiara e utile per l'utente finale. "
                "Mantieni tono naturale, sintetico e orientato all'azione. "
                "Non inventare dati e non includere JSON grezzo se non richiesto. "
                "NON usare saluti, introduzioni o frasi di chiusura rituali. "
                "Rispondi direttamente con i dettagli utili e basta. "
                f"COMMAND: {command}\nSERVICE_PAYLOAD:\n{payload_text}\n"
            )

        prompt += f"\n{conversation_style_contract()}\n"
        if response_prompt and str(response_prompt).strip():
            prompt += f"\nSERVICE_RESPONSE_PROMPT:\n{str(response_prompt).strip()}\n"
        if client_instructions and str(client_instructions).strip():
            prompt += f"\nCLIENT_INSTRUCTIONS:\n{str(client_instructions).strip()}\n"

        return self._ask_analyst(prompt)

    def compile_notification_shortcut(
        self, user_message: str, session_id: str, notify_target: str | None = None
    ) -> dict:
        """Process a notification shortcut command and return a result dict."""
        signals = self._memory_service.extract_and_save_preferences(
            user_message=user_message,
            session_id=session_id,
            notify_target=notify_target,
            force_notification_compiler=True,
        )
        notification_events = {"subscription.added",
                               "subscription.changed", "subscription.removed"}
        matched = [s for s in (signals or []) if str(
            s.get("event", "")).lower() in notification_events]
        if matched:
            return {"ok": True, "message": "✅ Notifica elaborata con il comando rapido.", "signals": signals}
        return {"ok": False, "message": "⚠️ Nessuna notifica creata. Specifica meglio dominio, evento o filtri.", "signals": signals or []}

    def delete_chat_history(self, session_id: str):
        """Delete chat history for *session_id* via Hub/Archive."""
        return self._hub.delete(f"/chat/history/{session_id}")

    def extract_and_save_preferences(self, user_message: str, session_id: str) -> None:
        """Delegate preference extraction to MemoryService."""
        self._memory_service.extract_and_save_preferences(
            user_message, session_id)

    # ── Private helpers ───────────────────────────────────────────────────────

    def _embed(self, text: str) -> list[float]:
        """Embed *text*, falling back to the secondary embedder on failure."""
        for agent in (self._agents.embedder, self._agents.fallback_embedder):
            try:
                vector = agent.embed(text)
                if vector:
                    return vector
            except Exception:
                pass
        return []

    def _ask_analyst(self, prompt: str) -> str:
        """Ask the primary analyst, falling back to secondary on error."""
        try:
            return self._agents.analyst.ask(prompt)
        except Exception as exc:
            logger.warning("Primary analyst failed, using fallback: %s", exc)
        try:
            return self._agents.fallback_analyst.ask(prompt)
        except Exception as exc:
            logger.error("Fallback analyst also failed: %s", exc)
            return "⚠️ In questo momento i modelli sono temporaneamente non disponibili. Riprova tra poco."

    def _quick_answer(
        self,
        user_message: str,
        history_text: str,
        client_instructions: str | None,
        extra_context: str | None,
    ) -> str:
        prompt = (
            "Sei Hestia, assistente IA conversazionale.\n\n"
            f"CONTESTO CONVERSAZIONE:\n{history_text}\n"
        )
        if extra_context:
            prompt += f"\nCONTESTO AGGIUNTIVO:\n{extra_context.strip()}\n"
        prompt += (
            f"\nMESSAGGIO UTENTE: {user_message}\n\n"
            "Rispondi in modo naturale, breve (max 3-5 righe), utile e umano.\n"
            "Se non serve recuperare dati strutturati, resta in conversazione diretta.\n"
            f"\n{conversation_style_contract()}\n"
        )
        if client_instructions and str(client_instructions).strip():
            prompt += f"\nSTILE:\n{str(client_instructions).strip()}"
        return self._ask_analyst(prompt)

    def _save_history(self, session_id: str, user_message: str, answer: str) -> None:
        try:
            self._hub.post(
                "/chat/history", {"session_id": session_id, "role": "user", "content": user_message})
            self._hub.post(
                "/chat/history", {"session_id": session_id, "role": "assistant", "content": answer})
        except Exception as exc:
            logger.warning("Failed to persist chat history: %s", exc)

    def _load_preferences(self, valid_domains: list[str]) -> list[dict]:
        all_prefs: list[dict] = []
        seen: set = set()
        for domain in valid_domains:
            for pref in (self._hub.get(f"/memory/active?domain={domain}") or []):
                pid = pref.get("id")
                if pid and pid not in seen:
                    all_prefs.append(pref)
                    seen.add(pid)
        return all_prefs
