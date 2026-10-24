import os
import threading
from typing import Any

from fastapi import Body, FastAPI, HTTPException

from .core.runtime import AthenaRuntime
from .core.schemas import CommitmentResolveRequest, TriggerRequest
from .core.service_contract import HestiaServiceBase, ServiceDescriptor
from .core.shared_imports import import_shared_symbol
from .core.athena_settings import settings as athena_settings

setup_service_logging = import_shared_symbol(
    "hestia_common.logging_utils", "setup_service_logging"
)
create_log_control_router = import_shared_symbol(
    "hestia_common.logging_utils", "create_log_control_router"
)
logger, log_buffer = setup_service_logging("hestia_athena")
plugin_client = import_shared_symbol("hestia_common.plugin_client", "PluginClient")
llm_usecase = import_shared_symbol("hestia_common.oracle_usecases", "usecase")
llm_capabilities = import_shared_symbol("hestia_common.oracle_usecases", "capabilities")

# What Athena asks Oracle for (chains chosen by Marko in Oracle → Cervello → Modelli).
LLM_USECASES = [
    llm_usecase("athena.strategia", "Athena · strategia e memoria", chain="potente",
                help="Ragionamenti di Athena (proposte, consolidamento della memoria)."),
    llm_usecase("athena.revisione", "Athena · revisione risposte", chain="veloce",
                help="Valuta la qualità delle risposte dell'assistente."),
    llm_usecase("athena.recap", "Athena · recap della giornata", chain="veloce",
                help="Scrive il recap serale o del mattino dai fatti delle aree (allenamento, spese, agenda…)."),
    llm_usecase("athena.riflessione", "Athena · riflessione sulla tua vita", chain="potente",
                help="Legge i segnali delle aree e i collegamenti tra le settimane e scrive le osservazioni "
                     "del recap della sera."),
]
plugin_page = import_shared_symbol("hestia_common.plugin_client", "page")
plugin_widget = import_shared_symbol("hestia_common.plugin_client", "widget")
plugin_quick_action = import_shared_symbol("hestia_common.plugin_client", "quick_action")


class AthenaService(HestiaServiceBase):
    def build_capabilities(self) -> dict[str, Any]:
        return {
            "focus_brief_loop": True,
            "relevance_gate_fields": [
                "urgency",
                "usefulness",
                "novelty",
                "interruption_cost",
                "confidence",
            ],
            "retrospective_inputs": [
                "recent_outcomes",
                "repeated_failures",
                "unresolved_commitments",
            ],
            "observation_sources": [
                "hub_registry",
                "argus_health",
                "archive_entities",
                "self_state",
            ],
            "thinking_modules": [
                "observer",
                "strategist",
                "reflection",
            ],
            "event_emit_endpoint": "/api/events/ingest",
            "oracle_hint_route": "/api/athena/hints",
            "status_endpoint": "/api/athena/status",
            "manual_trigger_endpoint": "/api/athena/trigger",
            "commitments_endpoint": "/api/athena/commitments",
            "thinking_endpoint": "/api/athena/thinking",
            "thinking_summary_endpoint": "/api/athena/thinking/summary",
            "think_now_endpoint": "/api/athena/think",
            "observation_endpoint": "/api/athena/observation",
            "recap_compose_endpoint": "/api/athena/recap",
            "signals_endpoint": "/api/athena/signals",
            # Athena's own piece of the daily recap («Da tenere d'occhio»), discovered like any module's.
            "recap_endpoint": "/api/module/recap",
            **ui.capabilities(SERVICE_BASE_URL),
            **llm_capabilities(LLM_USECASES),
        }


_HUB_KEEPALIVE_SECONDS = max(60, int(os.getenv("HUB_KEEPALIVE_SECONDS", "60")))
_hub_keepalive_stop = threading.Event()
_hub_keepalive_thread: threading.Thread | None = None


def _register_on_hub() -> None:
    try:
        service.register_to_hub(timeout_seconds=4)
        logger.info(
            "event=registered_hub_name_base_url Registered on Hub | name=%s base_url=%s",
            SERVICE_NAME,
            SERVICE_BASE_URL,
        )
    except Exception as error:
        logger.warning(
            "event=hub_registration_failed_non_fatal Hub registration failed (non-fatal): %s",
            error,
        )


def _hub_keepalive_loop() -> None:
    while not _hub_keepalive_stop.wait(_HUB_KEEPALIVE_SECONDS):
        _register_on_hub()


def _start_hub_keepalive() -> None:
    global _hub_keepalive_thread
    if _hub_keepalive_thread and _hub_keepalive_thread.is_alive():
        return
    _hub_keepalive_stop.clear()
    _hub_keepalive_thread = threading.Thread(
        target=_hub_keepalive_loop,
        daemon=True,
        name="athena-hub-keepalive",
    )
    _hub_keepalive_thread.start()


def _stop_hub_keepalive() -> None:
    _hub_keepalive_stop.set()


SERVICE_NAME = os.getenv("SERVICE_NAME", "athena")
SERVICE_BASE_URL = os.getenv("SERVICE_BASE_URL", "http://hestia_athena:19009")
SERVICE_VERSION = os.getenv("SERVICE_VERSION", "1.0.0")
SERVICE_TYPE = os.getenv("SERVICE_TYPE", "core")
SERVICE_TAGS = [
    tag.strip().lower()
    for tag in os.getenv("SERVICE_TAGS", SERVICE_TYPE).split(",")
    if tag.strip()
]
SERVICE_TOPOLOGY_TAGS = [
    tag.strip().lower()
    for tag in os.getenv(
        "SERVICE_TOPOLOGY_TAGS",
        "layer:cognition,domain:strategy,status:beta",
    ).split(",")
    if tag.strip()
]

service = AthenaService(
    ServiceDescriptor(
        name=SERVICE_NAME,
        base_url=SERVICE_BASE_URL,
        service_type=SERVICE_TYPE,
        service_version=SERVICE_VERSION,
        tags=SERVICE_TAGS,
        topology_tags=SERVICE_TOPOLOGY_TAGS,
    )
)
runtime = AthenaRuntime()

# ── WebUI plugin (core module, Sistema section): Pensieri ────────────────────
# Inside view (SPEC docs/work/2026-10-18-moduli-core-e-mcp-esterno §A2): every cycle observe → think → gate → act.
UI_DIST = os.getenv("ATHENA_UI_DIST", "/ui/dist")   # outside /code/app: the compose dev mount must not hide it
API = "/api/athena"
ui = plugin_client("athena", title="Athena", icon="zap", color="amber", kind="core", dist=UI_DIST,
                   description="Cosa pensa Hestia da sola: osserva, propone, filtra con il punteggio, agisce.",
                   version=SERVICE_VERSION)
ui.webui(
    entry="athena.js", api_prefix=f"{API}/",
    pages=[plugin_page("pensieri", "Pensieri", element="athena-thoughts", icon="zap", order=130,
                       help="Ogni ciclo di Athena, in due tracce: Vita (segnali delle aree, collegamenti tra le "
                            "settimane, osservazioni per il recap) e Sistema (salute di Hestia). Cosa ha osservato, "
                            "il punteggio (5 fattori) e cosa ha fatto o scartato, con il motivo. «Pensa ora» per un "
                            "ciclo subito."),
           plugin_page("segnali", "Segnali", element="athena-signals", icon="pulse", order=131,
                       help="I segnali brevi che ogni area pubblica sui suoi dati e i numeri settimanali che la "
                            "riflessione confronta. Le osservazioni che ne nascono arrivano nel recap della sera."),
           plugin_page("recap", "Recap", element="athena-recaps", icon="note", order=132,
                       help="I recap della giornata: il testo che ti è arrivato e, sotto, i fatti di ogni area da "
                            "cui è stato scritto. L'orario si sposta nel calendario.")],
    widgets=[plugin_widget("ultimo", "Ultimo pensiero", element="athena-last-widget", sizes=["m", "l"], auto=True,
                           open_page="pensieri", icon="zap", help="L'ultimo ciclo di Athena e cosa ne è uscito.")],
    quick_actions=[plugin_quick_action("pensa", "Fai pensare Athena", "POST", f"{API}/think", icon="zap",
                                       group="Sistema"),
                   plugin_quick_action("recap", "Recap adesso", "POST", f"{API}/recap/now", icon="note",
                                       group="Sistema")],
)

app = FastAPI(title="Hestia Athena", version=SERVICE_VERSION)
app.include_router(ui.router())


@app.on_event("startup")
def startup() -> None:
    logger.info(
        "event=service_startup service=%s version=%s",
        SERVICE_NAME,
        SERVICE_VERSION,
    )
    _register_on_hub()
    _start_hub_keepalive()
    athena_settings.start()
    runtime.start()


@app.on_event("shutdown")
def shutdown() -> None:
    logger.info("event=service_shutdown service=%s", SERVICE_NAME)
    runtime.stop()
    _stop_hub_keepalive()


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "service_type": service.descriptor.service_type,
        "tags": service.descriptor.tags,
    }


@app.get("/api/logs")
def get_logs(limit: int = 200, level: str | None = None, contains: str | None = None):
    rows = log_buffer.query(limit=limit, level=level, contains=contains)
    return {
        "service": "hestia_athena",
        "count": len(rows),
        "logs": rows,
    }


@app.get("/api/athena/status")
def athena_status() -> dict[str, Any]:
    return {"status": "ok", "runtime": runtime.status()}


@app.post("/api/athena/trigger")
def athena_trigger(request: TriggerRequest) -> dict[str, Any]:
    return runtime.trigger(request)


@app.get("/api/athena/tasks")
def athena_tasks(
    limit: int = 100,
    task_type: str | None = None,
    lifecycle_state: str | None = None,
) -> dict[str, Any]:
    rows = runtime.list_tasks(
        limit=limit,
        task_type=task_type,
        lifecycle_state=lifecycle_state,
    )
    return {
        "status": "ok",
        "count": len(rows),
        "tasks": rows,
    }


@app.get("/api/athena/tasks/{task_id}")
def athena_task(task_id: str) -> dict[str, Any]:
    row = runtime.get_task(task_id)
    if not row:
        raise HTTPException(
            status_code=404, detail=f"task '{task_id}' not found")
    return {
        "status": "ok",
        "task": row,
    }


@app.get("/api/athena/commitments")
def athena_commitments(
    limit: int = 100,
    include_resolved: bool = False,
) -> dict[str, Any]:
    rows = runtime.list_commitments(
        limit=limit,
        include_resolved=include_resolved,
    )
    return {
        "status": "ok",
        "count": len(rows),
        "commitments": rows,
    }


@app.post("/api/athena/commitments/{brief_id}/resolve")
def resolve_athena_commitment(brief_id: str, request: CommitmentResolveRequest) -> dict[str, Any]:
    row = runtime.resolve_commitment(
        brief_id=brief_id,
        status=request.status,
        note=request.note,
    )
    if not row:
        raise HTTPException(
            status_code=404, detail=f"commitment '{brief_id}' not found")
    return {
        "status": "ok",
        "commitment": row,
    }


@app.get("/api/athena/thinking")
def athena_thinking(
    limit: int = 20,
) -> dict[str, Any]:
    """Return recent thinking records — observation → candidates → decisions.

    Each record shows what Athena observed, what it considered doing,
    and what it actually emitted. This is the audit trail for proactive
    cognition that a client can display to show "what Athena is thinking."
    """
    rows = runtime.list_thinking_records(limit=limit)
    return {
        "status": "ok",
        "count": len(rows),
        "thinking": rows,
    }


@app.get("/api/athena/thinking/summary")
def athena_thinking_summary(limit: int = 10, track: str | None = None) -> dict[str, Any]:
    """Compact cycles (newest first) for the Pensieri page and the MCP tool ``athena_thinking``: observation
    counts, every candidate with its 5 gate factors, score, accepted/discarded and why, and the outcome.
    ``track`` = ``vita`` | ``sistema`` (both when omitted)."""
    return runtime.thinking_summary(limit=limit, track=track or None)


@app.post("/api/athena/think")
def athena_think_now(track: str = "sistema") -> dict[str, Any]:
    """«Pensa ora»: start one full thinking cycle now (background; past the idle gate and the agenda window).
    ``track`` = ``sistema`` (default) or ``vita``. ``started`` or ``busy`` (a cycle is already running); the
    record appears in /api/athena/thinking."""
    if track not in ("sistema", "vita"):
        raise HTTPException(status_code=422, detail="track: sistema | vita")
    return runtime.think_now(track=track)


@app.get("/api/athena/signals")
def athena_signals(domain: str | None = None, limit: int = 50, weeks: int = 12) -> dict[str, Any]:
    """What the reflection reads: active signals of the modules (worst first), the weekly series, the links found
    and the observations of the last 14 days (page Segnali, MCP ``athena_signals``)."""
    from .core.reflection import correlate
    from .core import athena_settings as AS
    try:
        signals = runtime.reflection.reader.signals(domain=domain)
        series = runtime.reflection.reader.series(weeks=max(4, min(int(weeks), 52)))
    except Exception as exc:
        logger.warning("[🔄] event=athena_signals_read_failed error=%s fallback=503", exc)
        raise HTTPException(status_code=503, detail="segnali non disponibili")
    if domain:
        series = {k: v for k, v in series.items() if v.get("domain") == domain}
    links = correlate(series, min_weeks=AS.get_int(AS.REFLECTION_MIN_WEEKS),
                      min_r=AS.get_float(AS.REFLECTION_MIN_CORRELATION))
    observations = runtime.reflection.observations(since_days=14)
    observations.sort(key=lambda o: str(o.get("at") or ""), reverse=True)
    return {"status": "ok", "signals": signals[:max(1, min(int(limit), 200))], "series": series,
            "links": links[:10], "observations": observations[:20]}


@app.get("/api/module/recap")
def module_recap(day: str | None = None, next: str | None = None) -> dict[str, Any]:  # noqa: A002 — contract name
    """Athena's piece of the daily recap (contract docs/work/2026-10-20-recap-giornaliero §3.2): the life
    observations of ``day`` under «Da tenere d'occhio», or ``{empty: true}``. Deterministic, no model call."""
    from .core.reflection import local_day
    return runtime.reflection.recap_piece(day or local_day())


@app.get("/api/athena/observation")
def athena_observation() -> dict[str, Any]:
    """Return the most recent observation snapshot.

    Shows live system state as last seen by Athena: registered services,
    unhealthy services, domain entity summaries, and self-state.
    """
    snapshot = runtime._observe()
    return {
        "status": "ok",
        "observation": snapshot.model_dump(),
    }


# ── Daily recap (docs/work/2026-10-20-recap-giornaliero) ─────────────────────
@app.post("/api/athena/recap")
def athena_recap(body: dict = Body(default={})) -> dict[str, Any]:
    """Compose the recap (agenda job, template, quick action). ``deliver`` false = return the text only."""
    momento = str((body or {}).get("momento") or "sera")
    day = str((body or {}).get("day") or "").strip() or None
    try:
        return runtime.recap.compose(momento=momento, day=day, deliver=bool((body or {}).get("deliver", True)),
                                     trigger=str((body or {}).get("trigger") or "manual"))
    except ValueError:
        raise HTTPException(status_code=400, detail="day must be YYYY-MM-DD")


@app.post("/api/athena/recap/now")
def athena_recap_now() -> dict[str, Any]:
    """Quick action «Recap adesso»: evening recap now, delivered like the scheduled one."""
    out = runtime.recap.compose(momento="sera", trigger="quick")
    label = ("Niente da raccontare oggi" if out.get("status") == "empty"
             else "Recap inviato" if out.get("delivered") else "Recap pronto (consegna in ritardo)")
    return {**out, "label": label}


@app.get("/api/athena/recaps")
def athena_recaps(limit: int = 20) -> dict[str, Any]:
    rows = runtime.recap.history(limit)
    return {"count": len(rows), "recaps": rows}


def _recap_today_handler(momento: str = "", **_kw) -> dict:
    """Chat «fammi il recap»: before 14:00 the morning view (yesterday + today), then the evening one."""
    from datetime import datetime as _dt
    moment = momento if momento in {"sera", "mattina"} else ("mattina" if _dt.now().hour < 14 else "sera")
    out = runtime.recap.compose(momento=moment, deliver=False, trigger="chat")
    if out.get("status") == "empty":
        return {"status": "empty", "text": "Niente da raccontare: nessuna area ha registrato qualcosa."}
    return {"status": "ok", "momento": moment, "day": out.get("day"), "text": out.get("text")}


# ── MCP tools ──────────────────────────────────────────────────────────────────
try:
    from hestia_common.mcp_helpers import MCPTool, create_mcp_router
    from .core.auditor import ConversationAuditor

    _ATHENA_HUB_URL = os.getenv(
        "HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")

    def _athena_audit_handler(
        session_id: str = "",
        limit: int = 0,
    ) -> dict:
        """Run a quality audit on recent conversation turns."""
        auditor = ConversationAuditor(_ATHENA_HUB_URL)
        result = auditor.audit_session(
            session_id=str(session_id or "").strip(),
            limit=int(limit) if limit else None,   # None → setting athena.audit.max_turns
        )
        return result

    _athena_mcp_tools = [
        MCPTool(
            name="recap_today",
            description=("Recap della giornata: com'è andata (allenamento, routine, spese, agenda, notifiche "
                         "aperte…) e cosa c'è dopo. 'momento': sera = oggi + domani, mattina = ieri + oggi "
                         "(default secondo l'ora). Restituisce il testo pronto."),
            parameters={"type": "object", "properties": {
                "momento": {"type": "string", "enum": ["sera", "mattina"],
                            "description": "sera = oggi e domani; mattina = ieri e oggi"}}},
            handler=_recap_today_handler,
            title="Recap della giornata",
            method="POST",
            path="/api/athena/recap/today",
            clients=["telegram", "ui", "external"],
            response_mode="direct",
            telegram_visible=True,
            telegram_group="giornata",
                telegram={"section": "Recap", "primary": 3, "label": "Recap"}),
        # Inside view, also for external AIs (SPEC docs/work/2026-10-18-moduli-core-e-mcp-esterno §B4): read only.
        MCPTool(
            name="athena_thinking",
            description=(
                "Ultimi cicli di pensiero di Athena (la parte proattiva di Hestia): cosa ha osservato, le azioni "
                "candidate con i 5 fattori del punteggio (urgenza, utilità, novità, sicurezza, disturbo), soglia, "
                "accettate o scartate con il motivo, e cosa ne ha fatto (inviata, Forge, proposta impostazione)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50,
                              "description": "Quanti cicli (default 10, più recenti prima)"},
                },
            },
            handler=lambda limit=10, **_kw: runtime.thinking_summary(limit=int(limit or 10)),
            title="Pensieri dell'assistente",
            method="GET",
            path="/api/athena/thinking/summary",
            clients=["ui", "external"],
            response_mode="oracle_natural",
            telegram_visible=False,
            telegram_group="sistema",
                telegram={"section": "Assistente"}),
        MCPTool(
            name="athena_signals",
            description=(
                "Segnali brevi che ogni area (allenamento, cura di sé, spese, guardaroba…) pubblica sui suoi dati, "
                "i numeri settimanali, i collegamenti trovati tra le settimane e le osservazioni recenti della "
                "riflessione. Utile per «com'è andata la settimana?» o «cosa noti di me?»."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "domain": {"type": "string", "description": "Solo un'area (es. fitness, finance)"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200,
                              "description": "Quanti segnali (default 50, i più importanti prima)"},
                },
            },
            handler=lambda domain=None, limit=50, **_kw: athena_signals(domain=domain or None,
                                                                         limit=int(limit or 50)),
            title="Segnali delle aree",
            method="GET",
            path="/api/athena/signals",
            clients=["ui", "external"],
            response_mode="oracle_natural",
            telegram_visible=False,
            telegram_group="sistema",
                telegram={"section": "Assistente"}),
        MCPTool(
            name="athena_audit_conversation",
            description=(
                "Run a quality audit on recent conversation turns using the "
                "26B reasoning model. Scores style adherence, accuracy, and "
                "usefulness for each assistant turn. Persists scores via "
                "Archive's feedback_submit. On-demand only — no automated loop."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Session identifier to audit",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 100,
                        "description": "Max conversation turns to pull (default: setting athena.audit.max_turns)",
                    },
                },
                "required": ["session_id"],
            },
            handler=_athena_audit_handler,
            title="Rivedi una conversazione",
            method="POST",
            path="/api/athena/audit/conversation",
            clients=["telegram", "ui"],
            response_mode="oracle_natural",
            response_prompt=(
                "Riporta i risultati dell'audit in modo chiaro: numero di "
                "risposte valutate e distribuzione dei punteggi per stile, "
                "accuratezza e utilità. Sii conciso."
            ),
            telegram_visible=True,
            telegram_group="sistema",
                telegram={"section": "Avanzate"}),
    ]
    app.include_router(
        create_mcp_router(_athena_mcp_tools, service_name="athena")
    )
    logger.info(
        "event=mcp_router_mounted service=athena tools=%d",
        len(_athena_mcp_tools),
    )
except ModuleNotFoundError:
    logger.info(
        "event=mcp_router_skipped service=athena "
        "reason=hestia_common_not_available"
    )

app.include_router(create_log_control_router("hestia_athena"))
app.include_router(athena_settings.router())


# Serve declared REST paths of MCP-only tools (Hub/Telegram/MCP gateway call
# tools by path; without this they got 404). Must stay at the end of the file.
try:
    from hestia_common.mcp_helpers import mount_missing_rest_routes
    mount_missing_rest_routes(app, _athena_mcp_tools, service_name="athena")
except (ModuleNotFoundError, NameError):
    pass
