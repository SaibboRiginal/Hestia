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

# ── Shared imports ────────────────────────────────────────────────────────────
try:
    from hestia_common.logging_utils import create_log_control_router, setup_service_logging
except ModuleNotFoundError:
    _workspace_root = Path(__file__).resolve().parents[2]
    _shared_pkg = _workspace_root / "Hestia-Shared"
    if str(_shared_pkg) not in sys.path:
        sys.path.insert(0, str(_shared_pkg))
    from hestia_common.logging_utils import create_log_control_router, setup_service_logging

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
        deduplicate: bool = True,
    ) -> dict:
        """Build a cleaned dataset from graded feedback records."""
        result = dataset_builder.build_dataset(
            hub=hub,
            name=str(name or "").strip() or "default",
            quality_labels=list(quality_labels or []) if quality_labels else None,
            min_score=int(min_score) if min_score else None,
            since=str(since or "").strip() or None,
            max_examples=int(max_examples) if max_examples else 500,
            deduplicate=bool(deduplicate),
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

        sample = examples[: min(len(examples), 10)]
        prompt_text = (
            "Valuta queste coppie di risposte (BASELINE vs CANDIDATE) "
            "per la stessa richiesta utente. Per ogni coppia, scegli il "
            "vincitore per: stile (niente chiusure pushy, conciso), "
            "accuratezza (fatti corretti), utilità (risponde alla domanda).\n\n"
        )
        for i, ex in enumerate(sample):
            prompt_text += (
                f"[{i}] UTENTE: {ex['user']}\n"
                f"    BASELINE: {ex['assistant']}\n"
                f"    CANDIDATE: [would be generated by {candidate_model}]\n\n"
            )
        prompt_text += (
            "Poiché il candidate model non è accessibile in questo momento, "
            "riporta che la valutazione richiede l'inferenza live del candidate "
            "model. Questo è un placeholder per il benchmark runner completo.\n"
            "Rispondi con JSON: {\"status\": \"needs_live_inference\", "
            "\"samples\": " + str(len(sample)) + "}"
        )

        llm_response = hub.call_oracle_llm(
            prompt_text, timeout=60,
            model=os.getenv("METIS_BENCHMARK_MODEL", ""),
            provider=os.getenv("METIS_BENCHMARK_PROVIDER", ""),
        )

        logger.info(
            "event=benchmark_run_done ms=%d candidate=%s dataset=%s samples=%d",
            int((time.perf_counter() - tb) * 1000),
            candidate_model,
            dataset_name,
            len(sample),
        )
        return {
            "status": "completed",
            "candidate_model": candidate_model,
            "baseline_model": baseline_model or os.getenv(
                "MODEL_USECASE_GENERIC_MODEL", "gemma4:e4b"),
            "dataset_name": dataset_name,
            "samples_evaluated": len(sample),
            "llm_response": llm_response[:2000] if llm_response else "",
        }

    def _metis_loRA_train_handler(
        dataset_name: str = "",
        base_model: str = "",
        adapter_name: str = "",
    ) -> dict:
        """Orchestrate a LoRA fine-tuning run (triggers external script)."""
        import uuid

        job_id = f"lora-{uuid.uuid4().hex[:12]}"
        ds_name = str(dataset_name or "").strip()
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

        resolved_base = str(base_model or "").strip() or os.getenv(
            "MODEL_USECASE_GENERIC_MODEL", "gemma4:e4b")
        resolved_adapter = str(adapter_name or "").strip() or f"metis-{ds_name}"

        # Export to JSONL for the training script
        export_result = _metis_dataset_export_handler(ds_name, "chatml")
        jsonl_content = export_result.get("jsonl", "")

        training_script = os.getenv(
            "METIS_TRAINING_SCRIPT",
            "/app/train_lora.py",
        )
        script_exists = os.path.exists(training_script) if training_script else False

        logger.info(
            "event=lora_train_triggered job_id=%s dataset=%s base=%s adapter=%s "
            "examples=%s script_exists=%s",
            job_id, ds_name, resolved_base, resolved_adapter,
            len(examples), script_exists,
        )

        return {
            "status": "triggered" if script_exists else "no_training_script",
            "job_id": job_id,
            "dataset_name": ds_name,
            "base_model": resolved_base,
            "adapter_name": resolved_adapter,
            "examples": len(examples),
            "training_script": training_script,
            "note": (
                "Training orchestrated asynchronously. "
                "Check logs for progress." if script_exists
                else f"Training script not found at {training_script}. "
                "Set METIS_TRAINING_SCRIPT env var to the path of your "
                "Unsloth/QLoRA training script."
            ),
            "jsonl_ready": bool(jsonl_content),
        }

    # ── Tool definitions ────────────────────────────────────────────────────

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
