import uuid
import os
import requests
import logging
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
from core.oracle_engine import OracleEngine


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s"
)

app = FastAPI(title="Hestia Oracle Microservice", version="1.0")
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
        "capabilities": {
            "chat_endpoint": "/api/chat",
        },
    }
    try:
        requests.post(f"{hub_api_url}/registry/register",
                      json=payload, timeout=4)
    except Exception:
        pass


class ChatRequest(BaseModel):
    message: str
    # 🆕 The frontend now passes an ID, not the whole history!
    session_id: Optional[str] = None
    notify_target: Optional[str] = None
    force_notification_compiler: Optional[bool] = False
    client_instructions: Optional[str] = None


class ChatResponse(BaseModel):
    reply: str
    domain_used: str
    session_id: str  # 🆕 We return it so the frontend can remember it


class FormatRequest(BaseModel):
    command: str
    payload: object
    response_prompt: Optional[str] = None
    client_instructions: Optional[str] = None


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


@app.get("/health")
def health_endpoint():
    return {"status": "ok", "service": "hestia_oracle"}


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
                        client_instructions=req.client_instructions),
            media_type="application/x-ndjson"
        )
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat/document")
async def chat_document_endpoint(
    message: str = Form(default=""),
    session_id: Optional[str] = Form(default=None),
    notify_target: Optional[str] = Form(default=None),
    client_instructions: Optional[str] = Form(default=None),
    file: UploadFile = File(...),
):
    """Accept a file (image or PDF) with an optional text instruction and stream
    an NDJSON analysis back to the caller.

    Accepted MIME types: image/jpeg, image/png, image/webp, image/gif,
    application/pdf.
    """
    ACCEPTED_MIMES = {
        "image/jpeg", "image/png", "image/webp", "image/gif",
        "image/heic", "image/heif",
        "application/pdf",
    }
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in ACCEPTED_MIMES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type: {content_type}. Accepted: {', '.join(sorted(ACCEPTED_MIMES))}",
        )
    try:
        file_bytes = await file.read()
        current_session = session_id if session_id else str(uuid.uuid4())
        return StreamingResponse(
            engine.analyze_document(
                file_bytes=file_bytes,
                mime_type=content_type,
                user_message=message.strip() or "Analizza questo documento.",
                session_id=current_session,
                notify_target=notify_target,
                client_instructions=client_instructions,
            ),
            media_type="application/x-ndjson",
        )
    except Exception as exc:
        import traceback
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/format", response_model=FormatResponse)
def format_endpoint(req: FormatRequest): try:
        text = engine.format_payload(
            command=req.command,
            payload=req.payload,
            response_prompt=req.response_prompt,
            client_instructions=req.client_instructions,
        )
        return {"text": text}
    except Exception as e:
        import traceback
        print(traceback.format_exc())
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
        import traceback
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/llm/generate")
def llm_generate_endpoint(req: dict):
    """
    Ollama-compatible LLM endpoint for services.
    Accepts: {"prompt": "...", "model": "...", "provider": "..."}
    Returns: {"response": "..."}
    """
    try:
        prompt = req.get("prompt", "").strip()
        if not prompt:
            raise HTTPException(status_code=400, detail="prompt required")

        model = req.get("model", engine.models["analyst"]["mod"])
        provider = req.get("provider", engine.models["analyst"]["prov"])

        from agents.universal_agent import UniversalAgent
        agent = UniversalAgent(
            role_prompt="", provider=provider, model_name=model)
        response_text = agent.complete(prompt)

        return {"response": response_text, "model": model, "provider": provider}
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/chat/{session_id}")
def clear_chat_endpoint(session_id: str):
    try:
        engine.delete_chat_history(session_id)
        return {"status": "cleared", "session_id": session_id}
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))
