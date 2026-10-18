"""Model capability detection for Oracle's analyst agents.

Single responsibility: determine what media types a given LLM model can
process natively, based on model name prefixes.

Prefixes are central settings (``oracle.documents.vision_models`` /
``oracle.documents.audio_models``), read at every check: add a new capable model
family in Impostazioni → Oracle → Documenti.
"""


def _prefixes(which: str) -> tuple[str, ...]:
    from core.services import oracle_settings  # lazy: settings import the provider registry
    key = oracle_settings.VISION_MODELS if which == "vision" else oracle_settings.AUDIO_MODELS
    return tuple(oracle_settings.get_list(key, lower=True))


def model_supports_vision(model_name: str) -> bool:
    """Return True if *model_name* is known to support image/PDF vision input."""
    normalised = (model_name or "").lower().replace("_", "-")
    return any(normalised.startswith(pfx.lower().replace("_", "-")) for pfx in _prefixes("vision"))


def model_supports_audio(model_name: str) -> bool:
    """Return True if *model_name* supports raw audio input natively."""
    normalised = (model_name or "").lower()
    return any(normalised.startswith(pfx.lower()) for pfx in _prefixes("audio"))
