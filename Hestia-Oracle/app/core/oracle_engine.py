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
import re
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


# ── Tool-call helper functions ─────────────────────────────────────────────────

def _collect_vars(obj, result: set) -> None:
    """Collect all $variable names from a nested template structure."""
    if isinstance(obj, dict):
        for v in obj.values():
            _collect_vars(v, result)
    elif isinstance(obj, list):
        for item in obj:
            _collect_vars(item, result)
    elif isinstance(obj, str) and obj.startswith("$"):
        result.add(obj[1:])


def _resolve_template(obj, args: dict, session_id: str, notify_target: str | None):
    """Recursively resolve $var references in a template dict/list/str."""
    if isinstance(obj, dict):
        return {k: _resolve_template(v, args, session_id, notify_target) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_template(item, args, session_id, notify_target) for item in obj]
    if isinstance(obj, str) and obj.startswith("$"):
        var = obj[1:]
        if var == "session_id":
            return session_id
        if var in ("chat_id", "owner") and notify_target:
            return notify_target
        return args.get(var)
    return obj


def _strip_nones(obj):
    """Remove None values from nested dicts/lists (for clean API payloads)."""
    if isinstance(obj, dict):
        return {k: _strip_nones(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_strip_nones(item) for item in obj if item is not None]
    return obj


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
        save_history: bool = True,
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
            if save_history:
                self._save_history(session_id, user_message, answer)
            logger.info("Quick chat done in %sms", int(
                (time.perf_counter() - t0) * 1000))
            yield stream_emitter.emit_final(answer, "general")
            return

        # ── Domain query path ─────────────────────────────────────────────────
        if explicit_domain and explicit_domain not in valid_domains:
            valid_domains = [explicit_domain] + \
                [d for d in valid_domains if d != explicit_domain]

        # ── Action call (tool use) — try before retrieval ─────────────────────
        yield stream_emitter.emit_status("⚙️ Verifica azioni disponibili...")
        try:
            action_answer = self._try_action_call(
                user_message, history_text, client_instructions, session_id, notify_target
            )
        except Exception as exc:
            logger.warning("Action call attempt failed (non-fatal): %s", exc)
            action_answer = None

        if action_answer is not None:
            if save_history:
                self._save_history(session_id, user_message, action_answer)
            logger.info("Action call done in %sms",
                        int((time.perf_counter() - t0) * 1000))
            yield stream_emitter.emit_final(action_answer, "action")
            return

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

        if save_history:
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
        thinking: bool = False,
        max_length: int | None = None,
        locale: str = "it",
    ) -> str:
        """Ask the analyst to format a structured service payload as human text."""
        payload_text = json.dumps(payload, ensure_ascii=False, indent=2)
        is_alert = str(command or "").startswith("alert:")

        html_format_rule = (
            "FORMATTAZIONE HTML TELEGRAM OBBLIGATORIA: usa <b>testo</b> per grassetto, "
            "<i>testo</i> per corsivo, <a href=\"url\">testo</a> per link, <code>testo</code> per codice. "
            "Per liste usa il simbolo • (bullet) direttamente — MAI trattini o asterischi. "
            "MAI usare sintassi Markdown (**testo**, _testo_, ##, [testo](url), * testo, - testo). "
        )

        if is_alert:
            prompt = (
                "Sei Hestia e stai PROATTIVAMENTE informando l'utente. "
                "Scrivi come se TU stessi iniziando una conversazione per condividere qualcosa di rilevante. "
                "Sii naturale, entusiasta ma preciso. "
                f"{html_format_rule}"
                "Per i link, usa SEMPRE il titolo/descrizione dell'elemento come testo del link, MAI testi generici. "
                "Non inventare dati. NON usare saluti introduttivi come 'Ciao' o 'Ecco'. "
                f"COMMAND: {command}\nSERVICE_PAYLOAD:\n{payload_text}\n"
            )
        else:
            prompt = (
                "Sei Hestia. Trasforma il payload strutturato in una risposta chiara e utile per l'utente finale. "
                "Mantieni tono naturale, sintetico e orientato all'azione. "
                "Presenta SOLO i dati del payload — non speculare, non offrire aiuto aggiuntivo, non fare domande retoriche. "
                "Non inventare dati e non includere JSON grezzo. "
                "NON usare saluti, introduzioni o frasi di chiusura. Rispondi direttamente con i dettagli utili. "
                f"{html_format_rule}"
                f"COMMAND: {command}\nSERVICE_PAYLOAD:\n{payload_text}\n"
            )

        prompt += f"\n{conversation_style_contract()}\n"
        if locale and str(locale).strip():
            prompt += f"\nLINGUA: Rispondi SEMPRE in lingua '{str(locale).strip()}'. Traduci qualsiasi testo del payload nella lingua richiesta.\n"
        if response_prompt and str(response_prompt).strip():
            prompt += f"\nSERVICE_RESPONSE_PROMPT:\n{str(response_prompt).strip()}\n"
        if client_instructions and str(client_instructions).strip():
            prompt += f"\nCLIENT_INSTRUCTIONS:\n{str(client_instructions).strip()}\n"
        if max_length:
            prompt += f"\nLUNGHEZZA: Rispondi in massimo {max_length} parole.\n"

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

    def _try_action_call(
        self,
        user_message: str,
        history_text: str,
        client_instructions: str | None,
        session_id: str,
        notify_target: str | None,
    ) -> str | None:
        """Attempt to match the user request to a Hub action command and execute it.

        Returns the formatted answer string if a tool was called, or None if no
        matching action was found (caller should fall through to domain query path).
        """
        from datetime import datetime

        # Fetch action commands (state-changing methods only) from Hub discovery
        all_commands = self._hub.get_commands()
        action_commands = [
            c for c in all_commands
            if c.get("method", "GET").upper() in ("POST", "PUT", "PATCH", "DELETE")
            # skip commands that require interactive arg picking
            and not c.get("arg_picker")
        ]
        if not action_commands:
            return None

        today_str = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")

        # Build a compact tool schema for the LLM
        tool_schemas = []
        for cmd in action_commands:
            schema: dict = {
                "name": cmd["command"],
                "description": cmd.get("description", ""),
                "params": {},
            }
            args_schema = cmd.get("arguments_schema") or {}
            if args_schema:
                schema["params"] = {
                    k: {"desc": v.get("description", k),
                        "required": v.get("required", False)}
                    for k, v in args_schema.items()
                }
            else:
                flat: set[str] = set()
                _collect_vars(cmd.get("body_template") or {}, flat)
                _collect_vars(cmd.get("query_template") or {}, flat)
                flat -= {"session_id", "chat_id", "owner"}
                if flat:
                    schema["params"] = {
                        v: {"desc": v, "required": True} for v in flat}
            tool_schemas.append(schema)

        tools_json = json.dumps(tool_schemas, ensure_ascii=False, indent=2)

        selection_prompt = (
            "Sei il selettore di azioni di Hestia.\n\n"
            f"DATA E ORA ATTUALE: {today_str}\n"
            f"CRONOLOGIA RECENTE:\n{history_text or '(nessuna)'}\n\n"
            f"MESSAGGIO UTENTE: {user_message}\n\n"
            f"AZIONI DISPONIBILI:\n{tools_json}\n\n"
            "ISTRUZIONI:\n"
            "- Se il messaggio RICHIEDE di creare, aggiungere, modificare, rimuovere o eseguire qualcosa → scegli l'azione appropriata.\n"
            "- Se il messaggio è una domanda, richiesta di informazioni o conversazione → rispondi con {\"action\": null}.\n"
            "- Risolvi le date relative (domani, lunedì prossimo, ecc.) usando DATA E ORA ATTUALE. Usa formato ISO 8601: YYYY-MM-DDTHH:MM:SS.\n"
            "- Per i parametri opzionali non menzionati dall'utente, usa null.\n\n"
            "Rispondi SOLO con JSON valido, nessun testo aggiuntivo prima o dopo.\n"
            "Formato azione: {\"action\": \"nome_comando\", \"params\": {\"key\": \"value\"}}\n"
            "Formato nessuna azione: {\"action\": null}"
        )

        # Use the fast scribe for tool selection
        raw = ""
        try:
            raw = self._agents.scribe.ask(selection_prompt)
        except Exception:
            try:
                raw = self._agents.fallback_scribe.ask(selection_prompt)
            except Exception as exc:
                logger.warning("Tool selection LLM failed: %s", exc)
                return None

        # Parse the JSON response
        try:
            raw_stripped = raw.strip()
            if raw_stripped.startswith("```"):
                raw_stripped = re.sub(
                    r"^```[a-z]*\n?", "", raw_stripped, flags=re.MULTILINE)
                raw_stripped = raw_stripped.rstrip("`").strip()
            selection = json.loads(raw_stripped)
        except Exception as exc:
            logger.debug(
                "Tool selection JSON parse failed: %s | raw=%s", exc, raw[:300])
            return None

        action_name = selection.get("action")
        if not action_name:
            return None  # LLM decided this is not an action request

        matched = next(
            (c for c in action_commands if c["command"] == action_name), None)
        if not matched:
            logger.warning(
                "Tool selected '%s' not found in commands", action_name)
            return None

        user_params = selection.get("params") or {}

        # Resolve body and query templates with user params + system vars
        body = _resolve_template(
            matched.get("body_template") or {
            }, user_params, session_id, notify_target
        )
        query = _resolve_template(
            matched.get("query_template") or {
            }, user_params, session_id, notify_target
        )

        # Clean up None values for a tidy API call
        if body and isinstance(body, dict):
            body = _strip_nones(body) or None
        if query and isinstance(query, dict):
            query = {k: v for k, v in query.items() if v is not None}

        logger.info(
            "Tool call | cmd=%s service=%s path=%s",
            action_name, matched.get("service", ""), matched.get("path", ""),
        )
        ok, result = self._hub.route_to_service(
            service=matched.get("service", ""),
            path=matched.get("path", ""),
            method=matched.get("method", "POST"),
            body=body,
            query=query or {},
        )

        if not ok:
            logger.warning(
                "Tool call failed | cmd=%s | result=%s", action_name, result)
            return "⚠️ Non è stato possibile completare l'azione. Il servizio non è disponibile o i parametri non sono validi."

        answer = self.format_payload(
            command=action_name,
            payload=result,
            response_prompt=matched.get("response_prompt", ""),
            client_instructions=client_instructions,
        )
        return answer

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
            "Non introdurre domini o argomenti non menzionati dall'utente.\n"
            f"\n{conversation_style_contract()}\n"
        )
        if client_instructions and str(client_instructions).strip():
            prompt += f"\nSTILE:\n{str(client_instructions).strip()}"
        # For quick chat, prefer the fast fallback analyst (Gemini Flash) over the heavy local model
        try:
            return self._agents.fallback_analyst.ask(prompt)
        except Exception:
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
