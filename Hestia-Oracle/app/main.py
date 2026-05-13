import uuid
import os
import requests
import logging
from pathlib import Path
import sys
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from typing import Any, Literal, Optional
from core.oracle_engine import OracleEngine

try:
    from hestia_common.logging_utils import setup_service_logging
except ModuleNotFoundError:
    _workspace_root = Path(__file__).resolve().parents[2]
    _shared_pkg = _workspace_root / "Hestia-Shared"
    if str(_shared_pkg) not in sys.path:
        sys.path.insert(0, str(_shared_pkg))
    from hestia_common.logging_utils import setup_service_logging

logger, log_buffer = setup_service_logging("hestia_oracle")

app = FastAPI(title="Hestia Oracle Microservice", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=[
                   "*"], allow_methods=["*"], allow_headers=["*"])
engine = OracleEngine()


@app.on_event("startup")
def register_on_hub_startup():
    hub_api_url = os.getenv(
        "HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
    service_base_url = os.getenv(
        "ORACLE_SERVICE_BASE_URL", "http://hestia_oracle:19004")
    payload = {
        "name": "oracle",
        "base_url": service_base_url,
        "health_endpoint": "/health",
        "service_type": "core",
        "service_version": os.getenv("ORACLE_SERVICE_VERSION", "1.0.0"),
        "tags": ["core", "chat"],
        "topology_tags": ["layer:cognition", "domain:llm", "status:stable"],
        "capabilities": {
            "chat_endpoint": "/api/chat",
        },
    }
    try:
        resp = requests.post(
            f"{hub_api_url}/registry/register", json=payload, timeout=4)
        if resp.status_code < 400:
            logger.info("event=registered_hub_hub_base_url Registered on Hub | hub=%s base_url=%s",
                        hub_api_url, service_base_url)
        else:
            logger.warning("event=hub_registration_non_success_status Hub registration non-success | status=%s body=%s",
                           resp.status_code, resp.text[:200])
    except Exception as exc:
        logger.warning(
            "event=hub_registration_failed_non_fatal Hub registration failed (non-fatal): %s", exc)


class ChatRequest(BaseModel):
    message: str
    # 🆕 The frontend now passes an ID, not the whole history!
    session_id: Optional[str] = None
    notify_target: Optional[str] = None
    force_notification_compiler: Optional[bool] = False
    client_instructions: Optional[str] = None
    # Set False for service-to-service calls (Argus, Hermes)
    save_history: bool = True


class ChatResponse(BaseModel):
    reply: str
    domain_used: str
    session_id: str  # 🆕 We return it so the frontend can remember it


class FormatRequest(BaseModel):
    command: str
    payload: object
    response_prompt: Optional[str] = None
    client_instructions: Optional[str] = None
    thinking: bool = False
    max_length: Optional[int] = None
    locale: str = "it"


class FormatResponse(BaseModel):
    text: str


class NotificationCompileRequest(BaseModel):
    message: str
    session_id: str
    notify_target: Optional[str] = None


class NotificationCompileResponse(BaseModel):
    ok: bool
    message: str
    signals: list[dict]


class QuestionAnswerRequest(BaseModel):
    session_id: str
    question_id: str
    answer: str
    client: Optional[str] = None  # e.g. "telegram", "web", "voice"


class UserControlsPatch(BaseModel):
    proactive_enabled: Optional[bool] = None
    allowed_categories: Optional[list[str]] = None
    quiet_hours: Optional[dict] = None
    reminder_aggressiveness: Optional[str] = None
    dont_ask_again: Optional[list[str]] = None
    reset_scope: Optional[str] = None


QualityLabel = Literal["excellent", "good", "mixed", "poor", "rejected"]


class FeedbackRequest(BaseModel):
    session_id: Optional[str] = None
    interaction_id: Optional[str] = None
    source_client: Optional[str] = None
    quality_label: Optional[str] = None
    quality_score: Optional[int] = Field(default=None, ge=1, le=5)
    outcome_label: Optional[str] = None
    feedback_text: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)


class FeedbackResponse(BaseModel):
    ok: bool
    feedback: dict[str, Any]


class ActionApprovalResponseRequest(BaseModel):
    approval_token: str
    approve: bool
    actor: Optional[str] = None
    client_instructions: Optional[str] = None


class AthenaHintIngestRequest(BaseModel):
    hint_id: Optional[str] = None
    source: str = "athena"
    hint_type: str = "focus_brief"
    session_id: Optional[str] = None
    domain: Optional[str] = None
    domains: list[str] = Field(default_factory=list)
    priority: str = "normal"
    summary: str
    brief: dict[str, Any] = Field(default_factory=dict)
    gate: dict[str, Any] = Field(default_factory=dict)
    retrospective: dict[str, Any] = Field(default_factory=dict)
    ttl_seconds: Optional[int] = None
    trace_id: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


@app.get("/health")
def health_endpoint():
    return {"status": "ok", "service": "hestia_oracle"}


@app.get("/api/logs")
def get_logs(limit: int = 200, level: str | None = None, contains: str | None = None):
    rows = log_buffer.query(limit=limit, level=level, contains=contains)
    return {
        "service": "hestia_oracle",
        "count": len(rows),
        "logs": rows,
    }


@app.get("/api/tasks")
def list_background_tasks(
    limit: int = 100,
    task_type: str | None = None,
    lifecycle_state: str | None = None,
):
    rows = engine.list_background_tasks(
        limit=limit,
        task_type=task_type,
        lifecycle_state=lifecycle_state,
    )
    return {
        "count": len(rows),
        "tasks": rows,
    }


@app.get("/api/tasks/{task_id}")
def get_background_task(task_id: str):
    row = engine.get_background_task(task_id)
    if not row:
        raise HTTPException(
            status_code=404, detail=f"task '{task_id}' not found")
    return {"task": row}


@app.post("/api/athena/hints")
def ingest_athena_hint_endpoint(req: AthenaHintIngestRequest, request: Request):
    """Ingest advisory hints produced by Athena through Hub-routed calls."""
    try:
        trace_id = str(
            request.headers.get("X-Trace-Id") or req.trace_id or "").strip() or None
        result = engine.ingest_athena_hint(
            hint_payload=req.model_dump(exclude_none=True),
            trace_id=trace_id,
        )
        return result
    except Exception as e:
        logger.exception(
            "event=unhandled_error_ingest_athena_hint_endpoint Unhandled error in Athena hint ingest endpoint")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/athena/hints")
def list_athena_hints_endpoint(session_id: str | None = None, limit: int = 20):
    try:
        rows = engine.list_athena_hints(session_id=session_id, limit=limit)
        return {
            "count": len(rows),
            "hints": rows,
        }
    except Exception as e:
        logger.exception(
            "event=unhandled_error_list_athena_hints_endpoint Unhandled error in Athena hints list endpoint")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat")
def chat_endpoint(req: ChatRequest):
    try:
        current_session = req.session_id if req.session_id else str(
            uuid.uuid4())

        # Return the Engine's output as a continuous stream
        # This streams the "yield" statements from oracle_engine.py directly to Telegram
        return StreamingResponse(
            engine.chat(req.message, current_session,
                        notify_target=req.notify_target,
                        force_notification_compiler=bool(
                            req.force_notification_compiler),
                        client_instructions=req.client_instructions,
                        save_history=req.save_history),
            media_type="application/x-ndjson"
        )
    except Exception as e:
        logger.exception(
            "event=unhandled_error_chat_endpoint_session Unhandled error in chat endpoint | session=%s", req.session_id)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat/document")
async def chat_document_endpoint(
    message: str = Form(default=""),
    session_id: Optional[str] = Form(default=None),
    notify_target: Optional[str] = Form(default=None),
    client_instructions: Optional[str] = Form(default=None),
    filename: Optional[str] = Form(default=None),
    file: UploadFile = File(...),
):
    """Accept any file type and stream an NDJSON analysis back to the caller.

    Accepts: images, PDFs, audio, video, office docs, text/code files.
    Capability-aware: uses model vision/audio features when available,
    falls back to local extraction (WhisperX, CLIP, YOLO, python-docx, etc.)
    otherwise.
    """
    ACCEPTED_MIMES = {
        # Images
        "image/jpeg", "image/jpg", "image/png", "image/webp",
        "image/gif", "image/heic", "image/heif", "image/bmp",
        "image/tiff", "image/svg+xml",
        # PDFs
        "application/pdf",
        # Audio
        "audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav",
        "audio/ogg", "audio/vorbis", "audio/flac", "audio/aac",
        "audio/x-aac", "audio/m4a", "audio/mp4",
        # Video
        "video/mp4", "video/mpeg", "video/webm", "video/ogg",
        "video/quicktime", "video/x-msvideo",
        # Office docs
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
        "application/vnd.oasis.opendocument.text",
        "application/vnd.oasis.opendocument.spreadsheet",
        "application/vnd.oasis.opendocument.presentation",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        # Text / code / data
        "text/plain", "text/csv", "text/markdown", "text/html",
        "text/xml", "application/xml",
        "application/json",
        "application/x-yaml", "application/yaml",
    }
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    # Accept unknown subtypes of text/ and application/ gracefully
    is_text_like = content_type.startswith("text/") or content_type in (
        "application/json", "application/xml", "application/yaml", "application/x-yaml"
    )
    if content_type not in ACCEPTED_MIMES and not is_text_like:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type: '{content_type}'. Send images, PDFs, audio, video, or office/text documents.",
        )
    try:
        file_bytes = await file.read()
        current_session = session_id if session_id else str(uuid.uuid4())
        resolved_filename = filename or file.filename or None

        # Infer a sensible default message per file category
        default_message = "Analizza questo file."
        if content_type.startswith("audio/") or content_type.startswith("video/"):
            default_message = "Trascrivi e riassumi questo file audio/video."
        elif content_type.startswith("image/"):
            default_message = "Descrivi questa immagine."
        elif content_type == "application/pdf":
            default_message = "Riassumi e analizza questo documento."

        return StreamingResponse(
            engine.analyze_document(
                file_bytes=file_bytes,
                mime_type=content_type,
                user_message=message.strip() or default_message,
                session_id=current_session,
                notify_target=notify_target,
                client_instructions=client_instructions,
                filename=resolved_filename,
            ),
            media_type="application/x-ndjson",
        )
    except Exception as exc:
        logger.exception(
            "event=unhandled_error_document_endpoint Unhandled error in document endpoint")
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/format", response_model=FormatResponse)
def format_endpoint(req: FormatRequest, request: Request):
    trace_id = str(request.headers.get("X-Trace-Id") or "").strip()
    if trace_id:
        logger.info(
            "event=format_request_received trace_id=%s command=%s payload_type=%s",
            trace_id,
            req.command,
            type(req.payload).__name__,
        )
    try:
        text = engine.format_payload(
            command=req.command,
            payload=req.payload,
            response_prompt=req.response_prompt,
            client_instructions=req.client_instructions,
            thinking=req.thinking,
            max_length=req.max_length,
            locale=req.locale,
            variant_seed=trace_id or None,
        )
        if trace_id:
            logger.info(
                "event=format_request_completed trace_id=%s command=%s output_chars=%s",
                trace_id,
                req.command,
                len(text or ""),
            )
        return {"text": text}
    except Exception as e:
        logger.exception(
            "event=unhandled_error_format_endpoint trace_id=%s Unhandled error in format endpoint",
            trace_id,
        )
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/subscriptions/compile", response_model=NotificationCompileResponse)
def compile_subscription_endpoint(req: NotificationCompileRequest):
    try:
        result = engine.compile_notification_shortcut(
            user_message=req.message,
            session_id=req.session_id,
            notify_target=req.notify_target,
        )
        return result
    except Exception as e:
        logger.exception(
            "event=unhandled_error_compile_endpoint Unhandled error in compile endpoint")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat/question-answer")
def question_answer_endpoint(req: QuestionAnswerRequest):
    """Receive a user's answer to a previously emitted question frame.

    Used by any client (Telegram, web, voice) to close out a pending question.
    Returns 200 with {resolved: true} or 404 if question_id is unknown.
    """
    try:
        resolved = engine.answer_question(req.question_id, req.answer)
        if not resolved:
            raise HTTPException(
                status_code=404,
                detail=f"Question '{req.question_id}' not found or already resolved.",
            )
        return {"resolved": True, "question_id": req.question_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "event=unhandled_error_question_answer_endpoint Unhandled error in question-answer endpoint")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/actions/approval/respond")
def action_approval_response_endpoint(req: ActionApprovalResponseRequest):
    """Resolve a pending high-impact action approval token."""
    try:
        result = engine.respond_high_impact_action_approval(
            approval_token=req.approval_token,
            approve=req.approve,
            actor=req.actor,
            client_instructions=req.client_instructions,
        )
        status = str(result.get("status") or "")
        if status == "not_found":
            raise HTTPException(
                status_code=404, detail="approval token not found or expired")
        if status == "invalid":
            raise HTTPException(status_code=400, detail=str(
                result.get("error") or "invalid approval payload"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "event=unhandled_error_action_approval_response_endpoint Unhandled error in action approval response endpoint")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/user/controls")
def get_user_controls_endpoint():
    """Read durable user controllability settings."""
    try:
        return {"controls": engine.get_user_controls()}
    except Exception as e:
        logger.exception(
            "event=unhandled_error_get_user_controls Unhandled error in get user controls endpoint")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/user/controls")
def update_user_controls_endpoint(req: UserControlsPatch):
    """Apply partial updates to durable user controllability settings."""
    try:
        controls, saved = engine.update_user_controls(
            req.model_dump(exclude_none=True),
            source="api",
        )
        return {"updated": bool(saved), "controls": controls}
    except Exception as e:
        logger.exception(
            "event=unhandled_error_update_user_controls Unhandled error in update user controls endpoint")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/feedback", response_model=FeedbackResponse)
def create_feedback_endpoint(req: FeedbackRequest):
    """Capture explicit quality feedback and store it in Archive via Hub route."""
    try:
        record = engine.submit_feedback(
            quality_label=req.quality_label or "mixed",
            quality_score=req.quality_score,
            session_id=req.session_id,
            interaction_id=req.interaction_id,
            source_client=req.source_client,
            outcome_label=req.outcome_label,
            feedback_text=req.feedback_text,
            tags=req.tags,
            payload=req.payload,
        )
        if not record:
            raise HTTPException(
                status_code=502,
                detail="feedback persistence unavailable",
            )
        return {"ok": True, "feedback": record}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "event=unhandled_error_feedback_endpoint Unhandled error in feedback endpoint")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/feedback")
def list_feedback_endpoint(
    session_id: Optional[str] = None,
    quality_label: Optional[QualityLabel] = None,
    source_client: Optional[str] = None,
    limit: int = 200,
):
    """List feedback records for dashboarding or audits."""
    try:
        rows = engine.list_feedback(
            session_id=session_id,
            quality_label=quality_label,
            source_client=source_client,
            limit=limit,
        )
        return {"count": len(rows), "feedback": rows}
    except Exception as e:
        logger.exception(
            "event=unhandled_error_list_feedback_endpoint Unhandled error in list feedback endpoint")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/feedback/export/jsonl")
def export_feedback_jsonl_endpoint(
    session_id: Optional[str] = None,
    quality_label: Optional[QualityLabel] = None,
    source_client: Optional[str] = None,
    limit: int = 1000,
):
    """Export feedback as JSONL for offline quality analysis/training."""
    try:
        jsonl_payload = engine.export_feedback_jsonl(
            session_id=session_id,
            quality_label=quality_label,
            source_client=source_client,
            limit=limit,
        )
        return Response(content=jsonl_payload, media_type="application/x-ndjson")
    except Exception as e:
        logger.exception(
            "event=unhandled_error_feedback_export_endpoint Unhandled error in feedback export endpoint")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/llm/generate")
def llm_generate_endpoint(req: dict):
    """
    Ollama-compatible LLM endpoint for services.
    Accepts: {"prompt": "...", "model": "...", "provider": "..."}
    Returns: {"response": "..."}
    """
    from agents.universal_agent import UniversalAgent
    try:
        prompt = req.get("prompt", "").strip()
        if not prompt:
            raise HTTPException(status_code=400, detail="prompt required")

        # Resolve defaults from env (same source as AgentFactory) so we never
        # reference the non-existent engine.models dict.
        default_provider = os.getenv(
            "ANALYST_PROVIDER", os.getenv("LLM_PROVIDER", "gemini"))
        default_model = os.getenv("ANALYST_MODEL", os.getenv(
            "LLM_MODEL", "gemini-2.5-flash"))

        model = req.get("model") or default_model
        provider = req.get("provider") or default_provider

        agent = UniversalAgent(
            role_prompt="", provider=provider, model_name=model)
        response_text = agent.ask(prompt)

        return {"response": response_text, "model": model, "provider": provider}
    except Exception as e:
        logger.exception(
            "event=unhandled_error_llm_generate_endpoint Unhandled error in llm/generate endpoint")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/chat/{session_id}")
def clear_chat_endpoint(session_id: str):
    try:
        engine.delete_chat_history(session_id)
        return {"status": "cleared", "session_id": session_id}
    except Exception as e:
        logger.exception(
            "event=unhandled_error_clearing_chat_history Unhandled error clearing chat history | session_id=%s", session_id)
        raise HTTPException(status_code=500, detail=str(e))
