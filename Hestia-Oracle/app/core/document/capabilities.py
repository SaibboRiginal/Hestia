"""Model capability detection for Oracle's analyst agents.

Single responsibility: determine what media types a given LLM model can
process natively, based on model name prefixes configured via env vars.

Open/Closed: set ORACLE_VISION_MODEL_PREFIXES / ORACLE_AUDIO_MODEL_PREFIXES
to add new capable models without touching any other module.
"""
import os

# ── Known multimodal-capable model prefixes ───────────────────────────────────

_DEFAULT_VISION = (
    "gemma-3,gemma4,gemma3,gemini,gpt-4o,gpt-4-vision,claude-3,"
    "llava,bakllava,moondream,minicpm-v,phi-3-vision,phi3v,"
    "qwen2-vl,qwen-vl,internvl"
)
_DEFAULT_AUDIO = "gemini-1.5,gemini-2"

VISION_MODEL_PREFIXES: tuple[str, ...] = tuple(
    p.strip().lower() for p in os.getenv(
        "ORACLE_VISION_MODEL_PREFIXES", _DEFAULT_VISION).split(",") if p.strip()
)

AUDIO_NATIVE_MODEL_PREFIXES: tuple[str, ...] = tuple(
    p.strip().lower() for p in os.getenv(
        "ORACLE_AUDIO_MODEL_PREFIXES", _DEFAULT_AUDIO).split(",") if p.strip()
)


def model_supports_vision(model_name: str) -> bool:
    """Return True if *model_name* is known to support image/PDF vision input."""
    normalised = (model_name or "").lower().replace("_", "-")
    return any(normalised.startswith(pfx.lower().replace("_", "-")) for pfx in VISION_MODEL_PREFIXES)


def model_supports_audio(model_name: str) -> bool:
    """Return True if *model_name* supports raw audio input natively."""
    normalised = (model_name or "").lower()
    return any(normalised.startswith(pfx.lower()) for pfx in AUDIO_NATIVE_MODEL_PREFIXES)
