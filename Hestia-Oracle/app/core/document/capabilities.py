"""Model capability detection for Oracle's analyst agents.

Single responsibility: determine what media types a given LLM model can
process natively, based on well-known model name prefixes.

Open/Closed: extend *_PREFIXES tuples to add new capable models without
touching any other module.
"""

# ── Known multimodal-capable model prefixes ───────────────────────────────────

# Models that support image and/or PDF vision input
VISION_MODEL_PREFIXES: tuple[str, ...] = (
    "gemma-3", "gemma4", "gemma3", "gemma 3", "gemma 4",
    "gemini", "gpt-4o", "gpt-4-vision", "claude-3",
    "llava", "bakllava", "moondream", "minicpm-v",
    "phi-3-vision", "phi3v",
    "qwen2-vl", "qwen-vl", "internvl",
)

# Models that can process raw audio data natively (very few)
AUDIO_NATIVE_MODEL_PREFIXES: tuple[str, ...] = (
    "gemini-1.5",
    "gemini-2",
)


def model_supports_vision(model_name: str) -> bool:
    """Return True if *model_name* is known to support image/PDF vision input."""
    normalised = (model_name or "").lower().replace("_", "-")
    return any(normalised.startswith(pfx.lower().replace("_", "-")) for pfx in VISION_MODEL_PREFIXES)


def model_supports_audio(model_name: str) -> bool:
    """Return True if *model_name* supports raw audio input natively."""
    normalised = (model_name or "").lower()
    return any(normalised.startswith(pfx.lower()) for pfx in AUDIO_NATIVE_MODEL_PREFIXES)
