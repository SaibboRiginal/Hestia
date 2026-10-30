"""Hestia-Metis — Continuous Improvement Organ.

Single responsibility: turn graded interactions into better models,
measure the improvement, and tell you when to switch.

Operates on the system's trajectory over time — unlike Argus (now),
Athena (next), Oracle (execute), Hephaestus (fix).
"""
import json
import logging
import os
import threading
import time
from pathlib import Path
import sys

import requests
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core.hub_client import HubClient
from .core import dataset_builder
from .core.insights import build_insights
from .core.metis_settings import review_auto_accept, review_batch, settings as metis_settings, traces_keep_days
from .core.review import USE_CASE as REVIEW_USE, Review
from .core.traces import Traces
from .core.usage import CLIENTS, IDEAS_USE, Usage

# ── Shared imports ────────────────────────────────────────────────────────────
try:
    from hestia_common.logging_utils import create_log_control_router, setup_service_logging
except ModuleNotFoundError:
    _workspace_root = Path(__file__).resolve().parents[2]
    _shared_pkg = _workspace_root / "Hestia-Shared"
    if str(_shared_pkg) not in sys.path:
        sys.path.insert(0, str(_shared_pkg))
    from hestia_common.logging_utils import create_log_control_router, setup_service_logging
from hestia_common.agenda_client import AgendaClient, daily_window, job_rule
from hestia_common.display import action, display, item
from hestia_common.module_kit import Hub as RoutedHub, Invalid, Store, StoreUnavailable
from hestia_common.oracle_usecases import capabilities as llm_capabilities, usecase
from hestia_common.presence_client import PresenceClient
from hestia_common.plugin_client import PluginClient, page

logger, log_buffer = setup_service_logging("hestia_metis")

# ── Config ────────────────────────────────────────────────────────────────────
SERVICE_NAME = os.getenv("SERVICE_NAME", "metis")
SERVICE_BASE_URL = os.getenv(
    "SERVICE_BASE_URL", "http://hestia_metis:19014")
SERVICE_VERSION = os.getenv("SERVICE_VERSION", "1.0.0")
SERVICE_TYPE = os.getenv("SERVICE_TYPE", "core")
SERVICE_TAGS = [
    t.strip().lower()
    for t in os.getenv("SERVICE_TAGS", SERVICE_TYPE).split(",")
    if t.strip()
]
SERVICE_TOPOLOGY_TAGS = [
    t.strip().lower()
    for t in os.getenv(
        "SERVICE_TOPOLOGY_TAGS",
        "layer:cognition,domain:improvement,status:alpha",
    ).split(",")
    if t.strip()
]
_HUB_API_URL = os.getenv(
    "HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")

hub = HubClient(_HUB_API_URL)

# ── WebUI plugin (core module, «Sistema» section): Miglioramento ─────────────
# SPEC docs/work/2026-10-18-moduli-core-e-mcp-esterno §A2/A3. Bundle Hestia-Metis/ui → <dist>/webui/metis.js,
# built in the image and copied outside /code (the compose dev mount of app/ would hide it). Read only:
# insights, datasets and LoRA jobs through the existing /api/metis/ reads; training stays a chat/agenda action.
UI_DIST = os.getenv("METIS_UI_DIST", "/ui/dist")
ui = PluginClient("metis", title="Miglioramento", icon="flask", color="purple", kind="core", dist=UI_DIST,
                  description="Miglioramento continuo: dove Hestia sbaglia, dataset e training dei modelli.",
                  version=SERVICE_VERSION)
ui.webui(entry="metis.js", api_prefix="/api/metis/",
         pages=[page("miglioramento", "Miglioramento", element="metis-improvement", icon="chart", order=180,
                     help="Dove Hestia risponde peggio secondo i tuoi voti, i dataset raccolti e i training LoRA "
                          "(pianificati nella finestra notturna dell'agenda, in corso, finiti).")])

# ── Assistant agenda (Chronos) ────────────────────────────────────────────────
# Training is heavy (GPU/CPU for hours): non-user requests are planned as agenda
# tasks inside the "metis.training" window (default night). The user sees them
# in Hestia's agenda and can move/skip/cancel; user requests start immediately.
WINDOW_TRAINING = "metis.training"
agenda = AgendaClient("metis", _HUB_API_URL)
presence = PresenceClient("metis", _HUB_API_URL)

# ── Usage log, «Adesso», «Scopri» (dossier docs/work/2026-10-24-tutto-brainstorm-cindy W6) ─────────────────────
# Taps live in Archive ``metis-store`` (Hub-routed mirror); the suggestion engine is core/usage.py.
usage_store = Store(RoutedHub(_HUB_API_URL), "metis-store", name="metis")
usage = Usage(usage_store, usage_store.hub, tz_name=os.getenv("TZ") or "Europe/Rome", agenda=agenda)
# Training dataset (docs/work/2026-10-30-dataset-allenamento): chat turn traces in Archive ``dataset-store``.
traces = Traces(usage_store.hub, keep_days=traces_keep_days)
# Nightly correction by the teacher model (cloud, personal data masked) + «Da rivedere» (D2).
review = Review(usage_store.hub, llm=usage_store.hub.llm, auto_accept=review_auto_accept, batch=review_batch)
REVIEW_AT = "02:30"
# Hours the assistant writes fresh «Adesso» ideas: only the seed of agenda jobs, the user moves them in the agenda.
IDEAS_AT = ("07:00", "12:30", "18:00")
_DATA_DIR = Path(os.getenv("METIS_DATA_DIR", "/code/data"))
_JOBS_FILE = _DATA_DIR / "lora_jobs.json"
_jobs_lock = threading.Lock()


# Model of Oracle's default «veloce» chain: used only when Oracle does not answer.
_ORACLE_GENERIC_DEFAULT = "gemma4:e4b"


def _oracle_generic_model() -> str:
    """Model choice belongs to Oracle: ask it (via Hub) which generic model is in use."""
    model = hub.oracle_model("oracle.generale")
    if model:
        return model
    logger.warning("[🔄] event=metis_oracle_model_unknown fallback=%s", _ORACLE_GENERIC_DEFAULT)
    return _ORACLE_GENERIC_DEFAULT


def _agenda_rules() -> list[dict]:
    # 01–06 is only the seed of the agenda window: the user moves/skips it in Hestia's agenda
    # (Chronos owns scheduling; user edits win), so it is neither env nor a Themis setting.
    tz = os.getenv("TZ") or "Europe/Rome"
    return [daily_window(
        WINDOW_TRAINING, "Finestra per allenare i modelli", 1, 6,
        description="Training LoRA pianificati (non richiesti da te) partono qui. "
                    "Sposta/salta la finestra per rimandarli.")] + [
        job_rule(f"metis.adesso.{at.replace(':', '')}", "Idee per «Adesso»", service="metis",
                 path="/api/metis/adesso/refresh", recurrence="FREQ=DAILY", start_at=f"2026-01-01T{at}:00", tz=tz,
                 description="L'assistente pensa a tre cose utili per le prossime ore (e pulisce i tocchi vecchi).")
        for at in IDEAS_AT] + [
        job_rule("metis.dataset.review", "Rilettura delle risposte per l'allenamento", service="metis",
                 path="/api/metis/review/run", recurrence="FREQ=DAILY", start_at=f"2026-01-01T{REVIEW_AT}:00", tz=tz,
                 description="Un modello più forte rilegge le risposte del giorno (con i tuoi dati oscurati) e "
                             "corregge quelle sbagliate; i casi dubbi aspettano te in «Da rivedere».")]


def _load_jobs() -> dict:
    try:
        return json.loads(_JOBS_FILE.read_text(encoding="utf-8")) if _JOBS_FILE.exists() else {}
    except Exception:
        return {}


def _save_job(job: dict) -> None:
    with _jobs_lock:
        jobs = _load_jobs()
        jobs[job["job_id"]] = {**jobs.get(job["job_id"], {}), **job}
        for old in sorted(jobs, key=lambda k: jobs[k].get("updated_at", ""))[:-200]:
            jobs.pop(old, None)
        try:
            _DATA_DIR.mkdir(parents=True, exist_ok=True)
            _JOBS_FILE.write_text(json.dumps(jobs, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("event=metis_jobs_save_failed error=%s", exc)


def _pid_alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False

# ── Application ───────────────────────────────────────────────────────────────
app = FastAPI(title="Hestia-Metis", version=SERVICE_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok", "service": "hestia_metis"}


@app.get("/api/metis/insights")
def metis_insights(limit: int = 500, since: str | None = None):
    """Weak spots from graded feedback (consumed by Athena → Forge proposals)."""
    records = hub.fetch_feedback(limit=limit, since=since)
    if isinstance(records, dict):
        records = records.get("records") or records.get("items") or []
    return {"status": "ok", **build_insights(records if isinstance(records, list) else [])}


@app.get("/api/metis/lora/jobs")
def metis_lora_jobs():
    """Training jobs (scheduled in the agenda, running, finished)."""
    jobs = _load_jobs()
    for job in jobs.values():
        if job.get("status") == "running" and job.get("pid") and not _pid_alive(job["pid"]):
            job["status"] = "finished"
    return {"status": "ok", "window": WINDOW_TRAINING, "count": len(jobs),
            "jobs": sorted(jobs.values(), key=lambda j: j.get("updated_at", ""), reverse=True)}


@app.get("/api/logs")
def get_logs(limit: int = 200, level: str | None = None, contains: str | None = None):
    return {
        "service": "hestia_metis",
        "count": len(log_buffer.query(limit=limit, level=level, contains=contains)),
        "logs": log_buffer.query(limit=limit, level=level, contains=contains),
    }


@app.exception_handler(Invalid)
async def _invalid(_, exc: Invalid):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(StoreUnavailable)
async def _store_down(_, exc: StoreUnavailable):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=503, content={"detail": "registro non raggiungibile, riprova"})


@app.post("/api/metis/usage")
def metis_usage(body: dict):
    """Clients push taps: ``{taps: [{client, kind: tool|page|action, ref, label?, at?}]}`` or one tap."""
    taps = body.get("taps") if isinstance(body.get("taps"), list) else [body]
    return usage.record([t for t in taps if isinstance(t, dict)])


@app.get("/api/metis/usage/stats")
def metis_usage_stats(days: int = 30):
    return usage.stats(max(1, min(days, 365)))


@app.get("/api/metis/adesso")
def metis_adesso(client: str = "telegram", limit: int = 6):
    """What fits now: agenda, habits, recents and the assistant's ideas, each with its reason."""
    return usage.adesso(client, limit=max(1, min(limit, 12)))


@app.post("/api/metis/adesso/refresh")
def metis_adesso_refresh(body: dict | None = None):
    """Agenda job ``metis.adesso.*``: fresh ideas for each client + prune of old taps."""
    clients = [str((body or {}).get("client"))] if (body or {}).get("client") else ["telegram", "webui"]
    out = {c: usage.refresh_ideas(c) for c in clients if c in CLIENTS}
    out["pruned"] = usage.prune()
    try:
        out["pruned_traces"] = traces.prune()
    except Exception as exc:  # noqa: BLE001 — the next run retries
        logger.warning("[🔄] event=traces_prune_failed error=%s", exc)
    logger.info("event=metis_adesso_refresh clients=%s pruned=%s", ",".join(clients), out["pruned"])
    return out


def _traces_call(fn, *args):
    try:
        return fn(*args)
    except Invalid:
        raise
    except Exception as exc:  # noqa: BLE001 — Archive away
        from fastapi import HTTPException
        logger.warning("[🔄] event=traces_archive_failed fn=%s error=%s", fn.__name__, str(exc)[:200])
        raise HTTPException(status_code=503, detail="archivio non raggiungibile, riprova")


@app.post("/api/metis/traces")
def metis_traces_add(body: dict):
    """Oracle pushes one finished chat turn (what the model saw and did) for the training dataset."""
    return _traces_call(traces.receive, body)


@app.delete("/api/metis/traces")
def metis_traces_forget(session_id: str = ""):
    """The owner deleted a conversation or excluded it from training: its traces and signals go."""
    return _traces_call(traces.forget_session, session_id)


@app.get("/api/metis/traces/status")
def metis_traces_status():
    """How many turns are saved for the dataset (total, last 7 days), signals, last one."""
    return _traces_call(traces.status)


@app.get("/api/metis/traces/recent")
def metis_traces_recent(limit: int = 20):
    """Newest saved turns, short (no prompts, no tool results)."""
    return {"items": _traces_call(traces.recent, limit)}


@app.post("/api/metis/review/run")
def metis_review_run():
    """Agenda job ``metis.dataset.review``: the teacher re-reads the next batch of saved turns."""
    return _traces_call(review.run)


@app.get("/api/metis/review/pending")
def metis_review_pending(limit: int = 10):
    """«Da rivedere»: corrections waiting for the owner (original vs corrected)."""
    return _traces_call(review.pending, limit)


@app.post("/api/metis/review/{trace_id}")
def metis_review_decide(trace_id: str, body: dict):
    """The owner decides: ``{decision: accept | reject | edit, answer?}``."""
    return _traces_call(review.decide, trace_id, str(body.get("decision") or ""), str(body.get("answer") or ""))


def _review_card(limit: int = 1) -> dict:
    out = review.pending(limit)
    items = out["items"]
    if not items:
        return {**out, "display": display("Da rivedere", lines=["Niente da rivedere: le correzioni della notte sono "
                                                                "tutte sicure o non ce ne sono."])}
    i = items[0]
    lines = [f"Tu: {i['user'][:300]}", f"Risposta: {i['answer'][:400]}"]
    if i["fixed"]:
        lines.append(f"Correzione: {i['fixed'][:400]}")
    if i["remove"]:
        lines.append("Da togliere: " + ", ".join(t for t in i["remove"] if t))
    if i["needs_owner"]:
        lines.append("Il revisore non sa correggerla da solo: scrivi tu la risposta giusta.")
    acts = [action("Scarta", "metis_rivedi_decidi", {"trace_id": i["trace_id"], "decision": "reject"}),
            action("Correggi io", "metis_rivedi_decidi", {"trace_id": i["trace_id"], "decision": "edit"})]
    if not i["needs_owner"]:
        acts.insert(0, action("Accetta", "metis_rivedi_decidi", {"trace_id": i["trace_id"], "decision": "accept"},
                              style="primary"))
    return {**out, "display": display("Da rivedere", subtitle=f"motivi: {', '.join(i['reasons']) or '—'}",
                                      lines=lines, actions=acts)}


@app.get("/api/metis/scopri")
def metis_scopri(client: str = "webui", limit: int = 12):
    """Features never or rarely used, with what they do."""
    return usage.scopri(client, limit=max(1, min(limit, 50)))


def _adesso_card(client: str = "telegram") -> dict:
    out = usage.adesso(client if client in CLIENTS else "telegram")
    items = out["items"]
    return {**out, "display": display(
        "Adesso", lines=[] if items else ["Ancora niente da suggerire: più usi Hestia, più impara cosa ti serve."],
        items=[item(i["title"], [i["reason"]]) for i in items],
        actions=[action(i["title"], i["tool"], i["args"] or None) for i in items])}


def _scopri_card(client: str = "telegram") -> dict:
    out = usage.scopri(client if client in CLIENTS else "telegram", limit=8)
    items = out["items"]
    return {**out, "display": display(
        "Scopri", subtitle=f"{out['total']} funzioni poco usate su {out['tools']}",
        lines=[] if items else ["Hai già provato tutto."],
        items=[item(i["title"], [i["description"][:90], i["reason"]]) for i in items],
        actions=[action(i["title"], i["tool"]) for i in items[:6]])}


# ── MCP tools ─────────────────────────────────────────────────────────────────
try:
    from hestia_common.mcp_helpers import MCPTool, create_mcp_router

    # ── Handlers ────────────────────────────────────────────────────────────

    def _metis_dataset_build_handler(
        name: str = "",
        quality_labels: list = None,
        min_score: int = None,
        since: str = "",
        max_examples: int = 500,
        deduplicate: bool | None = None,
    ) -> dict:
        """Build a cleaned dataset from graded feedback records."""
        result = dataset_builder.build_dataset(
            hub=hub,
            name=str(name or "").strip() or "default",
            quality_labels=list(quality_labels or []) if quality_labels else None,
            min_score=int(min_score) if min_score else None,
            since=str(since or "").strip() or None,
            max_examples=int(max_examples) if max_examples else 500,
            deduplicate=None if deduplicate is None else bool(deduplicate),
        )
        return result

    def _metis_dataset_export_handler(
        name: str = "",
        format: str = "chatml",
    ) -> dict:
        """Export a built dataset as JSONL text."""
        t_de = time.perf_counter()
        examples = dataset_builder.get_dataset_examples(
            str(name or "").strip()
        )
        if not examples:
            logger.info(
                "event=dataset_export_done ms=%d format=%s count=0",
                int((time.perf_counter() - t_de) * 1000),
                format,
            )
            return {"status": "not_found", "name": name, "examples": 0}

        lines: list[str] = []
        for ex in examples:
            if format == "alpaca":
                record = {
                    "instruction": ex["user"],
                    "output": ex["assistant"],
                }
            elif format == "sharegpt":
                record = {
                    "conversations": [
                        {"from": "human", "value": ex["user"]},
                        {"from": "gpt", "value": ex["assistant"]},
                    ],
                }
            else:  # chatml
                record = {
                    "messages": [
                        {"role": "system", "content": (
                            "Sei Hestia. Rispondi in modo diretto, concreto. "
                            "Niente chiusure pushy, niente offerte di aiuto non richieste. "
                            "Vai al punto e fermati."
                        )},
                        {"role": "user", "content": ex["user"]},
                        {"role": "assistant", "content": ex["assistant"]},
                    ],
                }
            lines.append(json.dumps(record, ensure_ascii=False))

        logger.info(
            "event=dataset_export_done ms=%d format=%s count=%d",
            int((time.perf_counter() - t_de) * 1000),
            format,
            len(lines),
        )
        return {
            "status": "ok",
            "name": name,
            "format": format,
            "examples": len(lines),
            "jsonl": "\n".join(lines),
        }

    def _metis_dataset_status_handler(name: str = "") -> dict:
        """Show dataset statistics."""
        return dataset_builder.get_dataset_status(
            str(name or "").strip() or None
        )

    def _metis_benchmark_run_handler(
        candidate_model: str = "",
        dataset_name: str = "",
        baseline_model: str = "",
    ) -> dict:
        """Run a benchmark eval comparing candidate vs baseline on a held-out set."""
        tb = time.perf_counter()
        examples = dataset_builder.get_dataset_examples(
            str(dataset_name or "").strip()
        )
        if not examples:
            logger.info(
                "event=benchmark_run_done ms=%d dataset=%s status=no_dataset",
                int((time.perf_counter() - tb) * 1000),
                dataset_name,
            )
            return {
                "status": "no_dataset",
                "dataset_name": dataset_name,
                "message": "Dataset not found. Build it first with metis_dataset_build.",
            }

        # Honest placeholder: live candidate inference is not implemented yet
        # (TODO.md). It used to call the LLM just to echo a JSON and report
        # "completed", which wasted tokens and misled the caller.
        logger.info(
            "event=benchmark_run_done ms=%d candidate=%s dataset=%s status=not_implemented",
            int((time.perf_counter() - tb) * 1000), candidate_model, dataset_name,
        )
        return {
            "status": "not_implemented",
            "candidate_model": candidate_model,
            "baseline_model": baseline_model or _oracle_generic_model(),
            "dataset_name": dataset_name,
            "available_examples": len(examples),
            "message": "Benchmark runner needs live candidate inference (see Hestia-Metis/TODO.md).",
        }

    def _metis_loRA_train_handler(
        dataset_name: str = "",
        base_model: str = "",
        adapter_name: str = "",
        schedule: str = "auto",
        requested_by: str = "user",
        job_id: str = "",
    ) -> dict:
        """Orchestrate a LoRA fine-tuning run (triggers external script).

        ``schedule``: ``now`` | ``window`` | ``auto`` (user → now, modules → window).
        A deferred run becomes an agenda task in the ``metis.training`` window.
        """
        import uuid

        job_id = str(job_id or "").strip() or f"lora-{uuid.uuid4().hex[:12]}"
        ds_name = str(dataset_name or "").strip()
        mode = str(schedule or "auto").strip().lower()
        if mode == "auto":
            mode = "now" if str(requested_by or "user").lower() == "user" else "window"
        if mode == "window":
            win = agenda.window(WINDOW_TRAINING)
            window_open = bool(win and win.get("active"))
            # Assistant presence: a training holds the GPU for a long time → only when heavy local
            # work is allowed (e.g. "Sonno profondo", "Pisolino"); otherwise retry in 30 min.
            held_by_presence = window_open and not presence.allows("work.heavy", "allow", "local")
            if not window_open or held_by_presence:
                from datetime import datetime, timedelta, timezone
                start_at = (win or {}).get("next_open") if not window_open else None
                if held_by_presence:
                    start_at = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
                    logger.info("event=lora_train_held_by_presence job_id=%s retry_at=%s", job_id, start_at)
                if not start_at:
                    # Window missing/cancelled: plan in one hour (user can move it).
                    start_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
                # Each plan is a new one-off agenda task (a re-plan from a firing task must not reuse
                # the key that is completing); it fires with schedule=window so the checks run again.
                agenda_key = f"metis.train.{job_id}.{int(time.time())}"
                planned = agenda.plan(
                    agenda_key, f"Allena il modello: {ds_name or '?'}", start_at,
                    action={"service": "metis", "path": "/api/metis/lora/train", "method": "POST",
                            "body": {"dataset_name": ds_name, "base_model": base_model,
                                     "adapter_name": adapter_name, "schedule": "window",
                                     "requested_by": requested_by, "job_id": job_id},
                            "timeout_seconds": 60},
                    description=f"Richiesto da {requested_by}. Annulla o sposta dall'agenda di Hestia.",
                    params={"dataset_name": ds_name, "job_id": job_id})
                _save_job({"job_id": job_id, "status": "scheduled", "dataset_name": ds_name,
                           "requested_by": requested_by, "start_at": start_at,
                           "agenda_key": agenda_key if planned else None,
                           "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S")})
                return {"status": "scheduled" if planned else "schedule_failed", "job_id": job_id,
                        "start_at": start_at, "agenda_key": agenda_key,
                        "message": "Training pianificato nella finestra notturna dell'agenda di Hestia."
                        if planned else "Agenda non raggiungibile: riprova o usa schedule=now."}
        examples = dataset_builder.get_dataset_examples(ds_name)

        if not examples:
            return {
                "status": "no_dataset",
                "job_id": job_id,
                "message": (
                    f"Dataset '{ds_name}' not found. "
                    "Build it first with metis_dataset_build."
                ),
            }

        resolved_base = str(base_model or "").strip() or _oracle_generic_model()
        resolved_adapter = str(adapter_name or "").strip() or f"metis-{ds_name}"

        # Export to JSONL for the training script
        export_result = _metis_dataset_export_handler(ds_name, "chatml")
        jsonl_content = export_result.get("jsonl", "")

        training_script = os.getenv(
            "METIS_TRAINING_SCRIPT",
            str(_DATA_DIR / "train_lora.py"),
        )
        script_exists = os.path.exists(training_script) if training_script else False
        pid = None
        dataset_path = ""
        if script_exists:
            # Actually launch the external trainer (it used to report
            # "triggered" without starting anything).
            import subprocess
            data_dir = _DATA_DIR
            data_dir.mkdir(parents=True, exist_ok=True)
            dataset_path = str(data_dir / f"{job_id}.jsonl")
            Path(dataset_path).write_text(jsonl_content, encoding="utf-8")
            log_file = open(data_dir / f"{job_id}.log", "w", encoding="utf-8")
            proc = subprocess.Popen(
                [sys.executable, training_script, "--dataset", dataset_path,
                 "--base_model", resolved_base, "--adapter_name", resolved_adapter],
                stdout=log_file, stderr=subprocess.STDOUT)
            pid = proc.pid
            # "Occupato: addestramento" while the trainer runs (GPU busy for the local model).
            presence.activity_start(f"metis.training.{job_id}", label="addestramento", load="heavy",
                                    resource="gpu", ttl_seconds=12 * 3600)

            def _wait_trainer(p=proc, log=log_file, key=f"metis.training.{job_id}"):
                try:
                    p.wait()
                finally:
                    log.close()
                    presence.activity_stop(key)
            threading.Thread(target=_wait_trainer, daemon=True, name=f"metis-train-{job_id}").start()
        logger.info(
            "event=lora_train_triggered job_id=%s dataset=%s base=%s adapter=%s "
            "examples=%s script_exists=%s pid=%s",
            job_id, ds_name, resolved_base, resolved_adapter,
            len(examples), script_exists, pid,
        )
        _save_job({"job_id": job_id, "status": "running" if pid else "no_training_script",
                   "pid": pid, "dataset_name": ds_name, "adapter_name": resolved_adapter,
                   "base_model": resolved_base, "requested_by": requested_by,
                   "log": str(_DATA_DIR / f"{job_id}.log") if pid else None,
                   "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S")})
        return {
            "status": "started" if pid else "no_training_script",
            "job_id": job_id,
            "pid": pid,
            "dataset_name": ds_name,
            "dataset_path": dataset_path,
            "base_model": resolved_base,
            "adapter_name": resolved_adapter,
            "examples": len(examples),
            "training_script": training_script,
            "note": (
                f"Training running; log: {_DATA_DIR}/{job_id}.log" if pid
                else f"Training script not found at {training_script}. "
                "Set METIS_TRAINING_SCRIPT to your Unsloth/QLoRA script."
            ),
        }

    _metis_mcp_tools = [
        MCPTool(
            name="metis_dataset_build",
            description=(
                "Build a cleaned, deduplicated, balanced dataset from graded "
                "feedback records. Pulls from Archive via Hub routing, applies "
                "quality filters, removes near-duplicates."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Dataset name/version label"},
                    "quality_labels": {
                        "type": "array", "items": {"type": "string"},
                        "description": "Quality labels to include. Default: excellent, good",
                    },
                    "min_score": {"type": "integer", "minimum": 1, "maximum": 5},
                    "since": {"type": "string", "description": "ISO date filter"},
                    "max_examples": {
                        "type": "integer", "minimum": 1, "maximum": 10000,
                        "description": "Cap total examples",
                    },
                    "deduplicate": {
                        "type": "boolean",
                        "description": "Remove near-duplicate user messages",
                    },
                },
                "required": ["name"],
            },
            handler=_metis_dataset_build_handler,
            title="Crea dataset",
            method="POST",
            path="/api/metis/dataset/build",
            clients=["telegram", "ui"],
            response_mode="oracle_natural",
            response_prompt=(
                "Riporta il numero di esempi raccolti, distribuzione per "
                "dominio e per qualità. Eventuali esempi scartati. Conciso."
            ),
            telegram_visible=True,
            telegram_group="sviluppo",
                telegram={"section": "Dataset e training"}),
        MCPTool(
            name="metis_dataset_export",
            description=(
                "Export a built dataset as JSONL for LoRA fine-tuning. "
                "Supports ChatML, Alpaca, and ShareGPT formats."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Dataset name to export"},
                    "format": {
                        "type": "string",
                        "enum": ["chatml", "alpaca", "sharegpt"],
                        "description": "Output format",
                    },
                },
                "required": ["name"],
            },
            handler=_metis_dataset_export_handler,
            title="Esporta dataset",
            method="GET",
            path="/api/metis/dataset/export",
            clients=["telegram", "ui"],
            response_mode="raw_json",
            telegram_visible=True,
            telegram_group="sviluppo",
                telegram={"section": "Dataset e training"}),
        MCPTool(
            name="metis_dataset_status",
            description=(
                "Show statistics for built datasets: example count, quality "
                "distribution, domain coverage, last build date."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Dataset name. Omit to list all."},
                },
                "required": [],
            },
            handler=_metis_dataset_status_handler,
            title="Stato dataset",
            method="GET",
            path="/api/metis/dataset/status",
            clients=["telegram", "ui"],
            response_mode="oracle_natural",
            response_prompt=(
                "Elenca i dataset disponibili con numero di esempi, "
                "distribuzione qualità, domini coperti. Tabellare e conciso."
            ),
            telegram_visible=True,
            telegram_group="sviluppo",
                telegram={"section": "Dataset e training"}),
        MCPTool(
            name="metis_benchmark_run",
            description=(
                "Run a benchmark evaluation comparing a candidate model "
                "against the current baseline on a held-out test set."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "candidate_model": {
                        "type": "string", "description": "Model name to evaluate",
                    },
                    "dataset_name": {
                        "type": "string", "description": "Held-out dataset for evaluation",
                    },
                    "baseline_model": {
                        "type": "string",
                        "description": "Current production model to compare against",
                    },
                },
                "required": ["candidate_model", "dataset_name"],
            },
            handler=_metis_benchmark_run_handler,
            title="Esegui benchmark",
            method="POST",
            path="/api/metis/benchmark/run",
            clients=["telegram", "ui"],
            response_mode="oracle_natural",
            response_prompt=(
                "Riporta i risultati del benchmark: punteggi su stile, "
                "accuratezza, concisione. Indica il vincitore o se è pareggio."
            ),
            telegram_visible=True,
            telegram_group="sviluppo",
                telegram={"section": "Dataset e training"}),
        MCPTool(
            name="metis_loRA_train",
            description=(
                "Orchestrate a LoRA fine-tuning run on the built dataset. "
                "Triggers an external training script. Returns a job ID."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "dataset_name": {
                        "type": "string", "description": "Dataset to train on",
                    },
                    "base_model": {
                        "type": "string",
                        "description": "Base model to fine-tune",
                    },
                    "adapter_name": {
                        "type": "string",
                        "description": "Name for the output LoRA adapter",
                    },
                    "schedule": {
                        "type": "string", "enum": ["auto", "now", "window"],
                        "description": "now = subito; window = nella finestra notturna dell'agenda; "
                                       "auto = subito se lo chiede l'utente",
                    },
                    "requested_by": {"type": "string", "description": "user | athena | ..."},
                },
                "required": ["dataset_name", "adapter_name"],
            },
            handler=_metis_loRA_train_handler,
            title="Avvia training LoRA",
            method="POST",
            path="/api/metis/lora/train",
            clients=["telegram", "ui"],
            response_mode="oracle_natural",
            response_prompt=(
                "Conferma l'avvio del training: dataset, modello base, "
                "nome adapter. Indica il job ID. Il training è asincrono."
            ),
            telegram_visible=True,
            telegram_group="sviluppo",
                telegram={"section": "Dataset e training"}),
        MCPTool(
            name="metis_rivedi",
            description="Le correzioni notturne delle risposte che aspettano te prima di entrare nel dataset di "
                        "allenamento: risposta originale, correzione, Accetta / Scarta / Correggi io.",
            parameters={"type": "object", "properties": {}, "required": []},
            handler=lambda: _traces_call(_review_card),
            title="Da rivedere", method="GET", path="/api/metis/tools/rivedi", clients=["telegram", "ui"],
            response_mode="raw_json", telegram_visible=True, telegram_group="sviluppo",
            telegram={"section": "Dataset e training"}),
        MCPTool(
            name="metis_rivedi_decidi",
            description="Decidi una correzione del dataset di allenamento: accept (va bene), reject (scarta il "
                        "turno), edit (la risposta giusta la scrivi tu in answer).",
            parameters={"type": "object", "properties": {
                "trace_id": {"type": "string", "description": "Turno da decidere"},
                "decision": {"type": "string", "enum": ["accept", "reject", "edit"]},
                "answer": {"type": "string", "description": "Con edit: la risposta giusta"}},
                "required": ["trace_id", "decision"]},
            handler=lambda trace_id="", decision="", answer="": {
                **_traces_call(review.decide, trace_id, decision, answer),
                "next": _traces_call(_review_card).get("display")},
            title="Decidi una correzione", method="POST", path="/api/metis/tools/rivedi_decidi",
            clients=["telegram", "ui"], response_mode="raw_json", telegram_group="sviluppo",
            telegram={"section": "Dataset e training"}),
        MCPTool(
            name="metis_adesso",
            description="Cosa ti serve adesso: azioni che usi di solito a quest'ora, quelle in agenda nelle "
                        "prossime ore e qualche idea dell'assistente, ognuna con il perché.",
            parameters={"type": "object", "properties": {
                "client": {"type": "string", "enum": list(CLIENTS), "description": "Dove le mostri"}},
                "required": []},
            handler=lambda client="telegram": _adesso_card(client),
            title="Adesso", method="GET", path="/api/metis/tools/adesso", clients=["telegram", "ui"],
            response_mode="raw_json", telegram_visible=True, telegram_group="giornata",
            telegram={"section": "Adesso", "primary": 1}),
        MCPTool(
            name="metis_scopri",
            description="Funzioni di Hestia che non hai mai usato o quasi, con cosa fanno e un pulsante per provarle.",
            parameters={"type": "object", "properties": {
                "client": {"type": "string", "enum": list(CLIENTS), "description": "Dove le mostri"}},
                "required": []},
            handler=lambda client="telegram": _scopri_card(client),
            title="Scopri", method="GET", path="/api/metis/tools/scopri", clients=["telegram", "ui"],
            response_mode="raw_json", telegram_visible=True, telegram_group="giornata",
            telegram={"section": "Scopri"}),
    ]

    app.include_router(
        create_mcp_router(_metis_mcp_tools, service_name="metis")
    )
    logger.info(
        "event=mcp_router_mounted service=metis tools=%d",
        len(_metis_mcp_tools),
    )
except ModuleNotFoundError:
    logger.info(
        "event=mcp_router_skipped service=metis "
        "reason=hestia_common_not_available"
    )

app.include_router(create_log_control_router("hestia_metis"))
app.include_router(ui.router())   # GET /api/ui/manifest · GET /ui/webui/<file>
app.include_router(metis_settings.router())   # GET /api/settings/effective, POST /api/settings/reload

# ── Hub registration ──────────────────────────────────────────────────────────
_HUB_REGISTRATION_PAYLOAD = {
    "name": SERVICE_NAME,
    "base_url": SERVICE_BASE_URL,
    "health_endpoint": "/health",
    "service_type": SERVICE_TYPE,
    "service_version": SERVICE_VERSION,
    "tags": SERVICE_TAGS,
    "topology_tags": SERVICE_TOPOLOGY_TAGS,
    "capabilities": {
        "when_to_use": "cosa fare adesso, funzioni da scoprire, come migliora l'assistente (voti, dataset, training)",
        "manual": "Adesso: metis_adesso (abitudini, agenda, idee). Scopri: metis_scopri (funzioni mai usate). "
                  "Miglioramento: dataset dai voti, benchmark e training LoRA.",
        "usage": "/api/metis/usage",
        "adesso": "/api/metis/adesso",
        "scopri": "/api/metis/scopri",
        "mcp_endpoint": f"{SERVICE_BASE_URL.rstrip('/')}/mcp",
        "dataset_build": "/api/metis/dataset/build",
        "dataset_export": "/api/metis/dataset/export",
        "dataset_status": "/api/metis/dataset/status",
        "benchmark_run": "/api/metis/benchmark/run",
        "loRA_train": "/api/metis/lora/train",
        "lora_jobs": "/api/metis/lora/jobs",
        "agenda_windows": [WINDOW_TRAINING],
        **ui.capabilities(SERVICE_BASE_URL),   # WebUI plugin manifest (Sistema)
        **llm_capabilities([usecase(IDEAS_USE, "Adesso · idee", chain="veloce",
                                    help="Tre azioni utili per le prossime ore, diverse dalle abitudini."),
                            usecase(REVIEW_USE, "Revisione del dataset", chain="cloud", thinking="true",
                                    help="Di notte rilegge le risposte e corregge quelle sbagliate. Scegli un modello "
                                         "più forte di quello locale: i tuoi dati personali vengono oscurati.")]),
    },
}


@app.on_event("startup")
def register_on_hub_startup():
    """Register with Hub on startup (best-effort)."""
    try:
        resp = requests.post(
            f"{_HUB_API_URL}/registry/register",
            json=_HUB_REGISTRATION_PAYLOAD,
            timeout=4,
        )
        if resp.status_code < 400:
            logger.info(
                "event=registered_on_hub hub=%s base_url=%s",
                _HUB_API_URL, SERVICE_BASE_URL,
            )
        else:
            logger.warning(
                "event=hub_registration_non_success status=%s body=%s",
                resp.status_code, resp.text[:200],
            )
    except Exception as exc:
        logger.warning(
            "event=hub_registration_failed_non_fatal error=%s", exc
        )

    # Periodic keepalive
    def _hub_keepalive():
        import time
        while True:
            time.sleep(60)
            try:
                requests.post(
                    f"{_HUB_API_URL}/registry/register",
                    json=_HUB_REGISTRATION_PAYLOAD,
                    timeout=4,
                )
            except Exception:
                pass

    threading.Thread(
        target=_hub_keepalive, daemon=True, name="metis-hub-keepalive",
    ).start()
    agenda.register_async(_agenda_rules)
    metis_settings.start()
    threading.Thread(target=usage_store.refresh, kwargs={"force": True}, daemon=True,
                     name="metis-usage-warm").start()


# Serve declared REST paths of MCP-only tools (Hub/Telegram/MCP gateway call
# tools by path; without this they got 404). Must stay at the end of the file.
try:
    from hestia_common.mcp_helpers import mount_missing_rest_routes
    mount_missing_rest_routes(app, _metis_mcp_tools, service_name="metis")
except (ModuleNotFoundError, NameError):
    pass
