"""Lazy-loaded local model singletons: CLIP, YOLO, and WhisperX.

Single responsibility: manage optional heavy ML model lifecycles.

All three models are loaded at most once per process (singleton pattern).
Public functions are the only API consumers should call — the internal
state variables are module-private.

Open/Closed: add a new local model (e.g. a depth estimator) by adding a
new loader function and a new public inference function; no existing code
needs to change.
"""
import io
import logging
import os
import tempfile

logger = logging.getLogger(f"hestia_oracle.{__name__}")

# ── CLIP singleton ────────────────────────────────────────────────────────────
_CLIP_LOADED = False
_CLIP_MODEL = None
_CLIP_PROCESSOR = None
_CLIP_DEVICE = None

# Labels used for CLIP zero-shot classification
_CLIP_LABELS: list[str] = [
    "a photo of a person", "a photo of an animal", "a photo of a vehicle",
    "a photo of a building or architecture", "a photo of nature or landscape",
    "a photo of food or drink", "a photo of text or document", "a photo of art or painting",
    "a photo of electronics or technology", "a photo of furniture or interior",
    "a photo of sport or fitness activity", "a photo of medical or scientific content",
    "a photo of a map or diagram", "a photo of a chart or graph",
    "a screenshot of an interface or application",
]


def _load_clip():
    """Return (model, processor, device) loading CLIP once on first call."""
    global _CLIP_LOADED, _CLIP_MODEL, _CLIP_PROCESSOR, _CLIP_DEVICE
    if _CLIP_LOADED:
        return _CLIP_MODEL, _CLIP_PROCESSOR, _CLIP_DEVICE
    _CLIP_LOADED = True
    try:
        import torch
        from transformers import CLIPModel, CLIPProcessor as _CLIPProc
        _CLIP_DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
        _CLIP_MODEL = CLIPModel.from_pretrained(
            "openai/clip-vit-base-patch32").to(_CLIP_DEVICE)
        _CLIP_PROCESSOR = _CLIPProc.from_pretrained(
            "openai/clip-vit-base-patch32")
        _CLIP_MODEL.eval()
        logger.info("event=local_clip_loaded [LOCAL] CLIP loaded on %s", _CLIP_DEVICE)
    except Exception as exc:
        logger.info("event=local_clip_unavailable [LOCAL] CLIP unavailable: %s", exc)
    return _CLIP_MODEL, _CLIP_PROCESSOR, _CLIP_DEVICE


# ── YOLO singleton ────────────────────────────────────────────────────────────
_YOLO_LOADED = False
_YOLO_MODEL = None


def _load_yolo():
    """Return YOLOv8-nano model, loading once on first call."""
    global _YOLO_LOADED, _YOLO_MODEL
    if _YOLO_LOADED:
        return _YOLO_MODEL
    _YOLO_LOADED = True
    try:
        from ultralytics import YOLO as _YOLO
        _YOLO_MODEL = _YOLO("yolov8n.pt")
        logger.info("event=local_yolov8_nano_loaded [LOCAL] YOLOv8-nano loaded")
    except Exception as exc:
        logger.info("event=local_yolo_unavailable [LOCAL] YOLO unavailable: %s", exc)
    return _YOLO_MODEL


# ── WhisperX singleton ────────────────────────────────────────────────────────
_WHISPER_LOADED = False
_WHISPER_MODEL = None

_MIME_TO_EXT: dict[str, str] = {
    "audio/mpeg": ".mp3", "audio/mp3": ".mp3",
    "audio/wav": ".wav", "audio/x-wav": ".wav",
    "audio/ogg": ".ogg", "audio/vorbis": ".ogg",
    "audio/flac": ".flac",
    "audio/aac": ".aac", "audio/x-aac": ".aac",
    "audio/m4a": ".m4a", "audio/mp4": ".m4a",
    "video/mp4": ".mp4", "video/mpeg": ".mpeg",
    "video/webm": ".webm", "video/ogg": ".ogv",
    "video/quicktime": ".mov", "video/x-msvideo": ".avi",
}


def _load_whisper():
    """Return WhisperX model, loading once on first call."""
    global _WHISPER_LOADED, _WHISPER_MODEL
    if _WHISPER_LOADED:
        return _WHISPER_MODEL
    _WHISPER_LOADED = True
    try:
        import whisperx
        _WHISPER_MODEL = whisperx.load_model(
            os.getenv("WHISPER_MODEL", "base"),
            device="cpu",
            compute_type="int8",
        )
        logger.info("event=local_whisperx_model_loaded [LOCAL] WhisperX model loaded (%s)",
                    os.getenv("WHISPER_MODEL", "base"))
    except Exception as exc:
        logger.info("event=local_whisperx_unavailable [LOCAL] WhisperX unavailable: %s", exc)
    return _WHISPER_MODEL


# ── Public inference functions ────────────────────────────────────────────────

def analyze_image(file_bytes: bytes) -> dict:
    """Run CLIP zero-shot classification + YOLO object detection on *file_bytes*.

    Returns:
        description: human-readable summary of detections
        tags: list of detected labels / top CLIP categories (max 10)
        clip_available: whether CLIP was available and ran
        yolo_available: whether YOLO was available and ran
    """
    from PIL import Image as _PILImage

    try:
        pil_img = _PILImage.open(io.BytesIO(file_bytes)).convert("RGB")
    except Exception as exc:
        logger.warning("event=local_cannot_open_image [LOCAL] Cannot open image: %s", exc)
        return {"description": "", "tags": [], "clip_available": False, "yolo_available": False}

    tags: list[str] = []
    yolo_available = False
    clip_available = False
    yolo_lines: list[str] = []
    clip_lines: list[str] = []

    # YOLO object detection
    yolo = _load_yolo()
    if yolo is not None:
        yolo_available = True
        try:
            results = yolo(pil_img, verbose=False)
            detected: dict[str, int] = {}
            for result in results:
                for box in result.boxes:
                    cls_name = result.names[int(box.cls[0])].replace("_", " ")
                    detected[cls_name] = detected.get(cls_name, 0) + 1
            for obj, count in sorted(detected.items(), key=lambda x: -x[1]):
                tags.append(obj)
                yolo_lines.append(f"  - {count}× {obj}")
        except Exception as exc:
            logger.warning("event=local_yolo_inference_failed [LOCAL] YOLO inference failed: %s", exc)

    # CLIP zero-shot classification
    clip_model, clip_proc, clip_device = _load_clip()
    if clip_model is not None and clip_proc is not None:
        clip_available = True
        try:
            import torch
            inputs = clip_proc(text=_CLIP_LABELS, images=pil_img,
                               return_tensors="pt", padding=True)
            inputs = {k: v.to(clip_device) for k, v in inputs.items()}
            with torch.no_grad():
                outputs = clip_model(**inputs)
                probs = outputs.logits_per_image.softmax(dim=1)[0]
            top_idxs = probs.argsort(descending=True)[:3]
            for idx in top_idxs:
                if float(probs[idx]) > 0.05:
                    label = _CLIP_LABELS[idx].replace(
                        "a photo of ", "").replace("a screenshot of ", "")
                    clip_lines.append(f"  - {label} ({probs[idx]:.0%})")
                    short = label.split(" or ")[0].split(" and ")[0].strip()
                    if short not in tags:
                        tags.append(short)
        except Exception as exc:
            logger.warning("event=local_clip_inference_failed [LOCAL] CLIP inference failed: %s", exc)

    desc_parts: list[str] = []
    if yolo_lines:
        desc_parts.append("Detected objects:\n" + "\n".join(yolo_lines))
    if clip_lines:
        desc_parts.append("Visual scene categories:\n" + "\n".join(clip_lines))

    return {
        "description": "\n".join(desc_parts),
        "tags": tags[:10],
        "clip_available": clip_available,
        "yolo_available": yolo_available,
    }


def transcribe_audio(file_bytes: bytes, mime_type: str) -> str:
    """Transcribe audio (or audio track of a video) using WhisperX.

    Returns the transcribed text, or an empty string if WhisperX is
    unavailable or transcription fails.
    """
    ext = _MIME_TO_EXT.get(mime_type, ".audio")
    whisper = _load_whisper()
    if whisper is None:
        return ""
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
            f.write(file_bytes)
            tmp_path = f.name
        result = whisper.transcribe(tmp_path, batch_size=8)
        segments = result.get("segments") or []
        return " ".join(seg.get("text", "").strip() for seg in segments if seg.get("text", "").strip())
    except Exception as exc:
        logger.warning("event=local_whisperx_transcription_failed [LOCAL] WhisperX transcription failed: %s", exc)
        return ""
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
