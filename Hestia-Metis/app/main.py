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
from .core.metis_settings import settings as metis_settings

# ── Shared imports ────────────────────────────────────────────────────────────
try:
    from hestia_common.logging_utils import create_log_control_router, setup_service_logging
except ModuleNotFoundError:
    _workspace_root = Path(__file__).resolve().parents[2]
    _shared_pkg = _workspace_root / "Hestia-Shared"
    if str(_shared_pkg) not in sys.path:
        sys.path.insert(0, str(_shared_pkg))
    from hestia_common.logging_utils import create_log_control_router, setup_service_logging
from hestia_common.agenda_client import AgendaClient, daily_window

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

# ── Assistant agenda (Chronos) ────────────────────────────────────────────────
# Training is heavy (GPU/CPU for hours): non-user requests are planned as agenda
# tasks inside the "metis.training" window (default night). The user sees them
# in Hestia's agenda and can move/skip/cancel; user requests start immediately.
WINDOW_TRAINING = "metis.training"
agenda = AgendaClient("metis", _HUB_API_URL)
_DATA_DIR = Path(os.getenv("METIS_DATA_DIR", "/code/data"))
_JOBS_FILE = _DATA_DIR / "lora_jobs.json"
_jobs_lock = threading.Lock()


# Oracle's declared default for oracle.models.generic.model: used only when Oracle does not answer.
_ORACLE_GENERIC_DEFAULT = "gemma4:e4b"


def _oracle_generic_model() -> str:
    """Model choice belongs to Oracle: ask it (via Hub) which generic model is in use."""
    model = hub.oracle_model("generic")
    if model:
        return model
    logger.warning("[🔄] event=metis_oracle_model_unknown fallback=%s", _ORACLE_GENERIC_DEFAULT)
    return _ORACLE_GENERIC_DEFAULT


def _agenda_rules() -> list[dict]:
    # 01–06 is only the seed of the agenda window: the user moves/skips it in Hestia's agenda
    # (Chronos owns scheduling; user edits win), so it is neither env nor a Themis setting.
    return [daily_window(
        WINDOW_TRAINING, "Metis: finestra training modelli", 1, 6,
        description="Training LoRA pianificati (non richiesti da te) partono qui. "
                    "Sposta/salta la finestra per rimandarli.")]


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
            if not (win and win.get("active")):
                start_at = (win or {}).get("next_open")
                if not start_at:
                    # Window missing/cancelled: plan in one hour (user can move it).
                    from datetime import datetime, timedelta, timezone
                    start_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
                planned = agenda.plan(
                    f"metis.train.{job_id}", f"Metis: training LoRA {ds_name or '?'}", start_at,
                    action={"service": "metis", "path": "/api/metis/lora/train", "method": "POST",
                            "body": {"dataset_name": ds_name, "base_model": base_model,
                                     "adapter_name": adapter_name, "schedule": "now",
                                     "requested_by": requested_by, "job_id": job_id},
                            "timeout_seconds": 60},
                    description=f"Richiesto da {requested_by}. Annulla o sposta dall'agenda di Hestia.",
                    params={"dataset_name": ds_name, "job_id": job_id})
                _save_job({"job_id": job_id, "status": "scheduled", "dataset_name": ds_name,
                           "requested_by": requested_by, "start_at": start_at,
                           "agenda_key": f"metis.train.{job_id}" if planned else None,
                           "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S")})
                return {"status": "scheduled" if planned else "schedule_failed", "job_id": job_id,
                        "start_at": start_at, "agenda_key": f"metis.train.{job_id}",
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
            title="🏗️ Build dataset",
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
        ),
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
            title="📦 Esporta dataset",
            method="GET",
            path="/api/metis/dataset/export",
            clients=["telegram", "ui"],
            response_mode="raw_json",
            telegram_visible=True,
            telegram_group="sviluppo",
        ),
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
            title="📈 Stato dataset",
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
        ),
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
            title="🧪 Esegui benchmark",
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
        ),
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
            title="🦾 Avvia training LoRA",
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
        ),
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
        "mcp_endpoint": f"{SERVICE_BASE_URL.rstrip('/')}/mcp",
        "dataset_build": "/api/metis/dataset/build",
        "dataset_export": "/api/metis/dataset/export",
        "dataset_status": "/api/metis/dataset/status",
        "benchmark_run": "/api/metis/benchmark/run",
        "loRA_train": "/api/metis/lora/train",
        "lora_jobs": "/api/metis/lora/jobs",
        "agenda_windows": [WINDOW_TRAINING],
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


# Serve declared REST paths of MCP-only tools (Hub/Telegram/MCP gateway call
# tools by path; without this they got 404). Must stay at the end of the file.
try:
    from hestia_common.mcp_helpers import mount_missing_rest_routes
    mount_missing_rest_routes(app, _metis_mcp_tools, service_name="metis")
except (ModuleNotFoundError, NameError):
    pass
