import json
import os
import time
import logging
from urllib.parse import urlparse, parse_qs

import requests

from agents.universal_agent import UniversalAgent
from core.services.context_builder import ContextBuilder
from core.services.memory_service import MemoryService
from core.services.module_registry import ModuleToolRegistry
from core.services.retrieval_service import RetrievalService
from core.services.router_service import RouterService


logger = logging.getLogger(__name__)


class OracleEngine:
    def __init__(self):
        self.hub_api_url = os.getenv(
            "HUB_API_URL", "http://hestia_hub:8005/api").rstrip("/")
        self.archive_url = os.getenv(
            "ARCHIVE_API_URL", "http://hestia_archive:8000/api")

        module_tools_urls_env = os.getenv("MODULE_TOOLS_URLS", "")
        module_tools_url_single = os.getenv("MODULE_TOOLS_URL", "")
        configured_urls = [u.strip()
                           for u in module_tools_urls_env.split(",") if u.strip()]
        if module_tools_url_single:
            configured_urls.append(module_tools_url_single.strip())

        self.context_builder = ContextBuilder(
            max_history_messages=int(os.getenv("ORACLE_HISTORY_LIMIT", "6")),
            max_history_chars=int(
                os.getenv("ORACLE_HISTORY_CHAR_LIMIT", "500")),
            max_entities_in_context=int(
                os.getenv("ORACLE_CONTEXT_ENTITIES_LIMIT", "12")),
            max_field_chars=int(
                os.getenv("ORACLE_CONTEXT_FIELD_CHAR_LIMIT", "280")),
        )

        self.models = {
            "router": {"prov": os.getenv("ROUTER_PROVIDER", "gemini"), "mod": os.getenv("ROUTER_MODEL", "gemma-3-12b-it")},
            "scribe": {
                "prov": os.getenv("SCRIBE_PROVIDER", os.getenv("FALLBACK_ANALYST_PROVIDER", os.getenv("ROUTER_PROVIDER", "ollama"))),
                "mod": os.getenv("SCRIBE_MODEL", os.getenv("FALLBACK_ANALYST_MODEL", os.getenv("ROUTER_MODEL", "qwen2.5:7b"))),
            },
            "analyst": {"prov": os.getenv("ANALYST_PROVIDER", "gemini"), "mod": os.getenv("ANALYST_MODEL", "gemma-3-27b-it")},
            "embedder": {"prov": os.getenv("EMBEDDING_PROVIDER", "ollama"), "mod": os.getenv("EMBEDDING_MODEL", "nomic-embed-text")},
            "fallback_router": {"prov": os.getenv("FALLBACK_ROUTER_PROVIDER", "ollama"), "mod": os.getenv("FALLBACK_ROUTER_MODEL", "mistral:7b")},
            "fallback_scribe": {
                "prov": os.getenv("FALLBACK_SCRIBE_PROVIDER", os.getenv("SCRIBE_PROVIDER", os.getenv("FALLBACK_ROUTER_PROVIDER", "ollama"))),
                "mod": os.getenv("FALLBACK_SCRIBE_MODEL", os.getenv("SCRIBE_MODEL", os.getenv("FALLBACK_ROUTER_MODEL", "mistral:7b"))),
            },
            "fallback_analyst": {"prov": os.getenv("FALLBACK_ANALYST_PROVIDER", "ollama"), "mod": os.getenv("FALLBACK_ANALYST_MODEL", "mistral:7b")},
            "fallback_embedder": {"prov": os.getenv("FALLBACK_EMBEDDING_PROVIDER", "gemini"), "mod": os.getenv("FALLBACK_EMBEDDING_MODEL", "models/embedding-001")},
        }

        self._normalize_provider_model_pairs()

        print(
            f"🧠 Oracle Init | Router: {self.models['router']['mod']} | Scribe: {self.models['scribe']['mod']} | Analyst: {self.models['analyst']['mod']} | Embedder: {self.models['embedder']['mod']}"
        )
        logger.info(
            "Oracle initialized with models | router=%s scribe=%s analyst=%s embedder=%s",
            self.models["router"]["mod"],
            self.models["scribe"]["mod"],
            self.models["analyst"]["mod"],
            self.models["embedder"]["mod"],
        )

        self._init_agents()

        self.module_registry = ModuleToolRegistry(
            module_tool_urls=configured_urls,
            ttl_seconds=int(
                os.getenv("MODULE_TOOL_REGISTRY_TTL_SECONDS", "120")),
            hub_api_url=self.hub_api_url,
        )
        self.router_service = RouterService(self.router, self.fallback_router)
        self.retrieval_service = RetrievalService(
            archive_url=self.archive_url,
            hub_api_url=self.hub_api_url,
            module_registry=self.module_registry,
            embedder=self._embed_text,
        )
        self.memory_service = MemoryService(
            archive_url=self.archive_url,
            hub_api_url=self.hub_api_url,
            scribe_agent=self.scribe,
            fallback_scribe_agent=self.fallback_scribe,
            context_builder=self.context_builder,
        )

    def _conversation_style_contract(self) -> str:
        return """
CONVERSATION STYLE CONTRACT (MANDATORY):
- The reply must feel like an ongoing chat, not a ticket closure.
- Never end with generic assistant closure lines in any language (examples: "Fammi sapere...", "Se in futuro...", "If you need anything else...", "Let me know if...").
- End directly on useful content (fact, answer, suggestion, or next concrete step), without ritual outro.
- Keep tone personal, natural, and context-aware.
""".strip()

    def _normalize_provider_model_pairs(self):
        def normalize(model_key: str, fallback_for_text: str = "gemini-2.5-flash"):
            model_cfg = self.models.get(model_key, {})
            provider = str(model_cfg.get("prov", "")).strip().lower()
            model_name = str(model_cfg.get("mod", "")).strip()

            if provider != "gemini":
                return

            lower_model = model_name.lower()
            if lower_model.startswith("gemma") or ":" in lower_model:
                replacement = "models/embedding-001" if "embed" in model_key else fallback_for_text
                logger.warning(
                    "Invalid Gemini model configured for %s: '%s'. Auto-switching to '%s'.",
                    model_key,
                    model_name,
                    replacement,
                )
                self.models[model_key]["mod"] = replacement

        normalize("router")
        normalize("scribe")
        normalize("analyst")
        normalize("fallback_router")
        normalize("fallback_scribe")
        normalize("fallback_analyst")
        normalize("embedder")
        normalize("fallback_embedder")

    def _init_agents(self):
        router_prompt = """You are a Universal Data Router.
Analyze the user's message and conversation context.

Output ONLY valid JSON with:
1. \"domains\": array of best matching domains. For general chat use [\"general\"].
2. \"filters\": exact-match hints dictionary (or {}).
3. \"filters_gt\": numerical \"greater than\" constraints dictionary (or {}).
4. \"filters_lt\": numerical \"less than\" constraints dictionary (or {}).
5. \"sort_by\": sort field or null.
6. \"sort_order\": \"asc\" or \"desc\".
"""

        scribe_prompt = """You are Hestia's Memory Manager.
Infer enduring user facts/preferences from natural language context.

Do NOT rely on explicit trigger words. Infer intent semantically.
If user asks to forget/reset memory (explicitly or implicitly), output DEPRECATE actions for all active preference IDs.
Output ONLY valid JSON array or NONE.
"""

        analyst_prompt = f"""Sei Hestia, assistente IA universale.

REGOLE CORE:
1. Rispondi nella lingua dell'utente.
2. Usa CONTEXT_DATA_RECORDS solo se pertinente.
3. Applica sempre USER_PREFERENCES.
4. Se i record sono molti, sintetizza e mostra solo i migliori risultati.
5. Puoi attivare notifiche proattive: quando l'utente chiede avvisi/notifiche automatiche, conferma che Hestia può salvarle come sottoscrizioni e inviare alert via Hermes (non dire che non puoi farlo).

FORMATTAZIONE:
- Solo Markdown.
- Usa elenchi puntati e grassetto per chiarezza.
- Se un record contiene URL/link, includilo quando utile.
- LINK POLICY: Per OGNI link/URL, usa SEMPRE il titolo o una descrizione significativa dell'elemento come testo del link.
  ESEMPI CORRETTI: [Appartamento 3 camere via Roma](URL), [Villa con giardino](URL), [Casa luminosa centro](URL)
  MAI USARE: "Apri annuncio", "Clicca qui", "Link", "URL", "Vedi qui" o altri testi generici.
- Non mostrare URL lunghi in chiaro.

STILE FINALE:
{self._conversation_style_contract()}
"""

        self.router = UniversalAgent(
            role_prompt=router_prompt,
            provider=self.models["router"]["prov"],
            model_name=self.models["router"]["mod"],
        )
        self.fallback_router = UniversalAgent(
            role_prompt=router_prompt,
            provider=self.models["fallback_router"]["prov"],
            model_name=self.models["fallback_router"]["mod"],
        )

        self.scribe = UniversalAgent(
            role_prompt=scribe_prompt,
            provider=self.models["scribe"]["prov"],
            model_name=self.models["scribe"]["mod"],
        )
        self.fallback_scribe = UniversalAgent(
            role_prompt=scribe_prompt,
            provider=self.models["fallback_scribe"]["prov"],
            model_name=self.models["fallback_scribe"]["mod"],
        )

        self.analyst = UniversalAgent(
            role_prompt=analyst_prompt,
            provider=self.models["analyst"]["prov"],
            model_name=self.models["analyst"]["mod"],
        )
        self.fallback_analyst = UniversalAgent(
            role_prompt=analyst_prompt,
            provider=self.models["fallback_analyst"]["prov"],
            model_name=self.models["fallback_analyst"]["mod"],
        )

        self.embedder_agent = UniversalAgent(
            role_prompt="",
            provider=self.models["embedder"]["prov"],
            model_name=self.models["embedder"]["mod"],
        )
        self.fallback_embedder_agent = UniversalAgent(
            role_prompt="",
            provider=self.models["fallback_embedder"]["prov"],
            model_name=self.models["fallback_embedder"]["mod"],
        )

    def _emit_status(self, msg: str) -> str:
        return json.dumps({"type": "status", "content": msg}) + "\n"

    def _emit_final(self, reply: str, domain: str = "none") -> str:
        return json.dumps({"type": "final", "reply": reply, "domain": domain}) + "\n"

    def _emit_signal(self, event: str, message: str, data: dict | None = None) -> str:
        return json.dumps(
            {
                "type": "signal",
                "event": event,
                "content": message,
                "data": data or {},
            },
            ensure_ascii=False,
        ) + "\n"

    def _api_get(self, endpoint: str, default_val=None):
        try:
            parsed = urlparse(endpoint)
            endpoint_path = parsed.path if parsed.path.startswith(
                "/") else f"/{parsed.path}"
            query = {k: v[0] if len(v) == 1 else v for k,
                     v in parse_qs(parsed.query).items()}
            normalized = f"api{endpoint_path}"
            response = requests.post(
                f"{self.hub_api_url}/route/archive/{normalized}",
                json={
                    "method": "GET",
                    "query": query,
                    "headers": {},
                    "body": None,
                    "timeout_seconds": 6,
                },
                timeout=7,
            )
            if response.status_code != 200:
                return default_val if default_val is not None else []
            routed = response.json() or {}
            if int(routed.get("status_code", 500)) < 400:
                return routed.get("payload")
            return default_val if default_val is not None else []
        except Exception:
            return default_val if default_val is not None else []

    def _api_post(self, endpoint: str, body: dict, timeout: int = 6):
        normalized = f"api{endpoint if endpoint.startswith('/') else '/' + endpoint}"
        response = requests.post(
            f"{self.hub_api_url}/route/archive/{normalized}",
            json={
                "method": "POST",
                "query": {},
                "headers": {},
                "body": body,
                "timeout_seconds": timeout,
            },
            timeout=timeout + 1,
        )
        response.raise_for_status()
        return response.json() or {}

    def delete_chat_history(self, session_id: str):
        normalized = f"api/chat/history/{session_id}"
        response = requests.post(
            f"{self.hub_api_url}/route/archive/{normalized}",
            json={
                "method": "DELETE",
                "query": {},
                "headers": {},
                "body": None,
                "timeout_seconds": 6,
            },
            timeout=7,
        )
        response.raise_for_status()
        routed = response.json() or {}
        if int(routed.get("status_code", 500)) >= 400:
            raise RuntimeError(routed.get("payload", "delete failed"))
        return routed.get("payload")

    def _embed_text(self, text: str) -> list[float]:
        try:
            vector = self.embedder_agent.embed(text)
            if vector:
                return vector
        except Exception:
            pass

        try:
            vector = self.fallback_embedder_agent.embed(text)
            if vector:
                return vector
        except Exception:
            pass

        return []

    def format_payload(self, command: str, payload: object, response_prompt: str | None = None, client_instructions: str | None = None) -> str:
        payload_text = json.dumps(payload, ensure_ascii=False, indent=2)

        # Detect if this is a proactive alert
        is_alert = str(command or "").startswith("alert:")

        if is_alert:
            formatting_prompt = (
                "Sei Hestia e stai PROATTIVAMENTE informando l'utente. "
                "Scrivi come se TU stessi iniziando una conversazione per condividere qualcosa di rilevante. "
                "Sii naturale, entusiasta ma preciso. "
                "Usa HTML per formattazione (grassetto <b>, link <a href>). "
                "Per i link, usa SEMPRE il titolo/descrizione dell'elemento come testo del link, MAI testi generici. "
                "Non inventare dati. NON usare saluti introduttivi come 'Ciao' o 'Ecco'. "
                f"COMMAND: {command}\n"
                f"SERVICE_PAYLOAD:\n{payload_text}\n"
            )
        else:
            formatting_prompt = (
                "Sei Hestia. Trasforma il payload strutturato in una risposta chiara e utile per l'utente finale. "
                "Mantieni tono naturale, sintetico e orientato all'azione. "
                "Non inventare dati e non includere JSON grezzo se non richiesto. "
                "NON usare saluti, introduzioni o frasi di chiusura rituali. "
                "Rispondi direttamente con i dettagli utili e basta. "
                f"COMMAND: {command}\n"
                f"SERVICE_PAYLOAD:\n{payload_text}\n"
            )

        formatting_prompt += "\n" + self._conversation_style_contract() + "\n"

        if response_prompt and str(response_prompt).strip():
            formatting_prompt += f"\nSERVICE_RESPONSE_PROMPT:\n{str(response_prompt).strip()}\n"

        if client_instructions and str(client_instructions).strip():
            formatting_prompt += f"\nCLIENT_INSTRUCTIONS:\n{str(client_instructions).strip()}\n"

        try:
            return self.analyst.ask(formatting_prompt).strip()
        except Exception:
            return self.fallback_analyst.ask(formatting_prompt).strip()

    def _classify_and_route(
        self,
        user_message: str,
        history_text: str,
        available_domains: list[str],
        schemas: dict | None = None,
    ) -> tuple[str, str | None, float, list[str], dict, dict, dict, str | None, str]:
        domain_candidates = [
            str(domain).strip().lower()
            for domain in (available_domains or [])
            if str(domain).strip().lower() and str(domain).strip().lower() != "general"
        ]
        domain_list_text = ", ".join(
            domain_candidates) if domain_candidates else "none"
        schema_text = json.dumps(
            schemas or {}, ensure_ascii=False, indent=2) if schemas else "{}"

        mode_prompt = f"""You classify and route user intent for a chat orchestrator.

Return ONLY valid JSON with:
1) "mode": "quick_chat" or "domain_query"
2) "domain": one domain from AVAILABLE_DOMAINS or null
3) "confidence": float 0..1
4) "domains": array of routed domains (or ["general"]) for domain_query
5) "filters": exact-match filters object
6) "filters_gt": numeric greater-than filters object
7) "filters_lt": numeric less-than filters object
8) "sort_by": field name or null
9) "sort_order": "asc" or "desc"

Rules:
- Use "quick_chat" for normal conversation, social chat, generic Q&A, short personal exchanges, or messages that do not need structured retrieval.
- Use "domain_query" only when the user clearly asks for domain records, filters, listings, alerts/subscriptions, or data-driven operations.
- Set "domain" only if it is explicit/high-confidence from AVAILABLE_DOMAINS; otherwise null.
- For domain_query, populate domains/filters/sort fields precisely.

AVAILABLE_DOMAINS: {domain_list_text}

CONTEXT DATA STRUCTURES:
{schema_text}

CONTEXT:
{history_text}

USER_MESSAGE: {user_message}
"""

        default_mode = "domain_query"
        default_domain = None
        default_confidence = 0.0
        default_domains = ["general"]
        default_filters: dict = {}
        default_filters_gt: dict = {}
        default_filters_lt: dict = {}
        default_sort_by = None
        default_sort_order = "desc"

        try:
            raw = self.router.ask(mode_prompt).strip()
        except Exception:
            try:
                raw = self.fallback_router.ask(mode_prompt).strip()
            except Exception:
                return (
                    default_mode,
                    default_domain,
                    default_confidence,
                    default_domains,
                    default_filters,
                    default_filters_gt,
                    default_filters_lt,
                    default_sort_by,
                    default_sort_order,
                )

        try:
            start_idx, end_idx = raw.find("{"), raw.rfind("}")
            if start_idx == -1 or end_idx == -1:
                return (
                    default_mode,
                    default_domain,
                    default_confidence,
                    default_domains,
                    default_filters,
                    default_filters_gt,
                    default_filters_lt,
                    default_sort_by,
                    default_sort_order,
                )
            data = json.loads(raw[start_idx: end_idx + 1])

            mode = str(data.get("mode", default_mode)).strip().lower()
            if mode not in {"quick_chat", "domain_query"}:
                mode = default_mode

            domain = data.get("domain")
            normalized_domain = str(domain).strip(
            ).lower() if domain is not None else None
            if normalized_domain and normalized_domain not in domain_candidates:
                normalized_domain = None

            confidence = float(data.get("confidence", 0.0) or 0.0)
            if confidence < 0:
                confidence = 0.0
            if confidence > 1:
                confidence = 1.0

            selected_domains = [str(d).lower() for d in (
                data.get("domains") or []) if str(d).strip()]
            if normalized_domain and normalized_domain not in selected_domains:
                selected_domains.insert(0, normalized_domain)
            valid_domains = [
                d for d in selected_domains if d in available_domains or d == "general"
            ] or ["general"]

            active_filters = data.get("filters") if isinstance(
                data.get("filters"), dict) else {}
            filters_gt = data.get("filters_gt") if isinstance(
                data.get("filters_gt"), dict) else {}
            filters_lt = data.get("filters_lt") if isinstance(
                data.get("filters_lt"), dict) else {}
            sort_by = data.get("sort_by")
            sort_order = "asc" if str(data.get(
                "sort_order", "desc")).lower() == "asc" else "desc"

            return mode, normalized_domain, confidence, valid_domains, active_filters, filters_gt, filters_lt, sort_by, sort_order
        except Exception:
            return (
                default_mode,
                default_domain,
                default_confidence,
                default_domains,
                default_filters,
                default_filters_gt,
                default_filters_lt,
                default_sort_by,
                default_sort_order,
            )

    def _generate_quick_chat_answer(self, user_message: str, history_text: str, client_instructions: str | None = None) -> str:
        quick_prompt = f"""Sei Hestia, assistente IA conversazionale.

CONTESTO CONVERSAZIONE:
{history_text}

MESSAGGIO UTENTE: {user_message}

Rispondi in modo naturale, breve (max 3-5 righe), utile e umano.
Se non serve recuperare dati strutturati, resta in conversazione diretta.
"""
        quick_prompt += "\n" + self._conversation_style_contract() + "\n"
        if client_instructions and str(client_instructions).strip():
            quick_prompt += "\n\nSTILE:\n" + str(client_instructions).strip()

        try:
            return self.analyst.ask(quick_prompt)
        except Exception:
            return self.fallback_analyst.ask(quick_prompt)

    def compile_notification_shortcut(self, user_message: str, session_id: str, notify_target: str | None = None) -> dict:
        signals = self.memory_service.extract_and_save_preferences(
            user_message=user_message,
            session_id=session_id,
            notify_target=notify_target,
            force_notification_compiler=True,
        )

        notification_events = {
            "subscription.added",
            "subscription.changed",
            "subscription.removed",
        }
        matched = [
            signal for signal in (signals or [])
            if str(signal.get("event", "")).strip().lower() in notification_events
        ]

        if matched:
            return {
                "ok": True,
                "message": "✅ Notifica elaborata con il comando rapido.",
                "signals": signals,
            }

        return {
            "ok": False,
            "message": "⚠️ Nessuna notifica creata. Specifica meglio dominio, evento o filtri.",
            "signals": signals or [],
        }

    def chat(self, user_message: str, session_id: str, notify_target: str | None = None, force_notification_compiler: bool = False, client_instructions: str | None = None):
        request_started = time.perf_counter()
        logger.info("Chat request started | session_id=%s message_len=%s",
                    session_id, len(user_message or ""))

        # Standard path for data/domain queries
        yield self._emit_status("📂 Recupero cronologia e routing...")

        step_start = time.perf_counter()
        history_data = self._api_get(
            f"/chat/history/{session_id}?limit={self.context_builder.max_history_messages}")
        history_text = self.context_builder.compact_history(history_data)
        logger.info("History loaded | session_id=%s messages=%s in %sms", session_id, len(
            history_data or []), int((time.perf_counter() - step_start) * 1000))

        step_start = time.perf_counter()
        available_domains = self._api_get("/domains") or ["general"]
        logger.info("Domains loaded | count=%s in %sms", len(available_domains), int(
            (time.perf_counter() - step_start) * 1000))

        step_start = time.perf_counter()
        schemas = self._api_get("/schemas") or {}
        logger.info("Metadata loaded | available_domains=%s schema_domains=%s in %sms",
                    available_domains, len(schemas or {}), int((time.perf_counter() - step_start) * 1000))

        classification_start = time.perf_counter()
        mode, explicit_domain, mode_confidence, valid_domains, active_filters, filters_gt, filters_lt, sort_by, sort_order = self._classify_and_route(
            user_message=user_message,
            history_text=history_text,
            available_domains=available_domains,
            schemas=schemas,
        )
        logger.info(
            "Mode/routing classification | mode=%s domain=%s confidence=%.2f in %sms",
            mode,
            explicit_domain,
            mode_confidence,
            int((time.perf_counter() - classification_start) * 1000),
        )

        if mode == "quick_chat" and mode_confidence >= 0.55:
            logger.info(
                "Quick conversation path selected | session_id=%s", session_id)
            yield self._emit_status("💬 Conversazione rapida...")

            analysis_start = time.perf_counter()
            final_answer = self._generate_quick_chat_answer(
                user_message=user_message,
                history_text=history_text,
                client_instructions=client_instructions,
            )
            logger.info("Quick conversational response generated in %sms", int(
                (time.perf_counter() - analysis_start) * 1000))

            yield self._emit_status("✍️ Consegna...")
            save_start = time.perf_counter()
            try:
                self._api_post(
                    "/chat/history",
                    {"session_id": session_id,
                        "role": "user", "content": user_message},
                )
                self._api_post(
                    "/chat/history",
                    {"session_id": session_id,
                        "role": "assistant", "content": final_answer},
                )
                logger.info("History persisted in %sms", int(
                    (time.perf_counter() - save_start) * 1000))
            except Exception as error:
                logger.warning("Failed persisting chat history: %s", error)

            logger.info("Quick chat request completed | session_id=%s total=%sms",
                        session_id, int((time.perf_counter() - request_started) * 1000))
            yield self._emit_final(final_answer, "general")
            return

        if explicit_domain and explicit_domain not in valid_domains:
            valid_domains = [explicit_domain] + [
                domain for domain in valid_domains if domain != explicit_domain]

        logger.info(
            "Routing complete | domains=%s filters=%s filters_gt=%s filters_lt=%s sort_by=%s sort_order=%s",
            valid_domains,
            active_filters,
            filters_gt,
            filters_lt,
            sort_by,
            sort_order,
        )

        yield self._emit_status(f"🧠 Analisi domini: {', '.join(valid_domains)}...")
        yield self._emit_status("🧾 Recupero preferenze attive...")

        pref_step_start = time.perf_counter()
        all_prefs = []
        seen_pref_ids = set()
        for domain in valid_domains:
            for pref in self._api_get(f"/memory/active?domain={domain}"):
                pref_id = pref.get("id")
                if pref_id and pref_id not in seen_pref_ids:
                    all_prefs.append(pref)
                    seen_pref_ids.add(pref_id)
        logger.info("Preferences loaded | count=%s in %sms", len(
            all_prefs), int((time.perf_counter() - pref_step_start) * 1000))

        preference_facts = [str(p.get("fact", "")).strip()
                            for p in all_prefs if p.get("fact")]

        yield self._emit_status("🔎 Recupero entità dai moduli/Archive...")
        retrieval_start = time.perf_counter()
        all_entities = self.retrieval_service.retrieve_entities(
            user_message=user_message,
            session_id=session_id,
            valid_domains=valid_domains,
            preference_facts=preference_facts,
            active_filters=active_filters,
            filters_gt=filters_gt,
            filters_lt=filters_lt,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        logger.info("Entities retrieval complete | count=%s in %sms", len(
            all_entities), int((time.perf_counter() - retrieval_start) * 1000))

        yield self._emit_status("🧱 Compattazione contesto...")
        formatted_context = self.context_builder.compact_entities_for_prompt(
            all_entities)
        logger.info("Context compacted | has_entities=%s", bool(all_entities))

        analysis_prompt = self.context_builder.build_analysis_prompt(
            preference_facts=preference_facts,
            valid_domains=valid_domains,
            active_filters=active_filters,
            filters_gt=filters_gt,
            filters_lt=filters_lt,
            sort_by=sort_by,
            sort_order=sort_order,
            formatted_context=formatted_context,
            history_text=history_text,
            user_message=user_message,
        )
        analysis_prompt += "\n\n" + self._conversation_style_contract()

        if client_instructions and str(client_instructions).strip():
            analysis_prompt += (
                "\n\nCLIENT_INSTRUCTIONS:\n"
                + str(client_instructions).strip()
            )

        yield self._emit_status("🧠 Sintesi finale in corso...")
        analysis_start = time.perf_counter()
        try:
            final_answer = self.analyst.ask(analysis_prompt)
            logger.info("Analyst response generated with primary model in %sms", int(
                (time.perf_counter() - analysis_start) * 1000))
        except Exception as primary_error:
            logger.warning(
                "Primary analyst failed, switching to fallback: %s", primary_error)
            fallback_start = time.perf_counter()
            try:
                final_answer = self.fallback_analyst.ask(analysis_prompt)
                logger.info("Analyst response generated with fallback model in %sms", int(
                    (time.perf_counter() - fallback_start) * 1000))
            except Exception as fallback_error:
                logger.error("Fallback analyst failed: %s", fallback_error)
                final_answer = (
                    "⚠️ In questo momento i modelli sono temporaneamente non disponibili. "
                    "Riprova tra poco."
                )

        yield self._emit_status("✍️ Consegna...")

        save_start = time.perf_counter()
        try:
            self._api_post(
                "/chat/history",
                {"session_id": session_id,
                    "role": "user", "content": user_message},
            )
            self._api_post(
                "/chat/history",
                {"session_id": session_id,
                    "role": "assistant", "content": final_answer},
            )
            logger.info("History persisted in %sms", int(
                (time.perf_counter() - save_start) * 1000))
        except Exception as error:
            logger.warning("Failed persisting chat history: %s", error)
            pass

        yield self._emit_status("🔔 Aggiornamento preferenze e notifiche...")
        memory_start = time.perf_counter()
        try:
            signals = self.memory_service.extract_and_save_preferences(
                user_message,
                session_id,
                notify_target=notify_target,
                force_notification_compiler=force_notification_compiler,
            )
            logger.info(
                "Preference/subscription sync completed | signals=%s in %sms",
                len(signals or []),
                int((time.perf_counter() - memory_start) * 1000),
            )
            for signal in signals or []:
                yield self._emit_signal(
                    event=str(signal.get("event", "info")),
                    message=str(signal.get(
                        "message", "Aggiornamento eseguito.")),
                    data=signal.get("data") or {},
                )
        except Exception as error:
            logger.warning("Preference/subscription sync failed: %s", error)

        logger.info("Chat request completed | session_id=%s total=%sms",
                    session_id, int((time.perf_counter() - request_started) * 1000))
        yield self._emit_final(final_answer, valid_domains[0])

    def extract_and_save_preferences(self, user_message: str, session_id: str):
        self.memory_service.extract_and_save_preferences(
            user_message, session_id)
