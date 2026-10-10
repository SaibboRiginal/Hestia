"""Metis settings declared to Themis (central settings).

Dataset defaults (size cap, dedup, quality labels) and the "good" labels of the insights
report replace the old ``METIS_*`` env vars; all live (read at use time). The training window
``metis.training`` is NOT a setting: it is an assistant-agenda window (Chronos), edited there.
Env keeps infrastructure only: service identity, Hub URL, ``METIS_DATA_DIR``, ``METIS_TRAINING_SCRIPT``.
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    from hestia_common.settings_client import SettingsClient, setting
except ModuleNotFoundError:  # local runs without PYTHONPATH
    _shared = Path(__file__).resolve().parents[3] / "Hestia-Shared"
    if str(_shared) not in sys.path:
        sys.path.insert(0, str(_shared))
    from hestia_common.settings_client import SettingsClient, setting

MAX_EXAMPLES = "metis.dataset.max_examples"
DEDUPLICATE = "metis.dataset.deduplicate"
QUALITY_LABELS = "metis.dataset.quality_labels"
GOOD_LABELS = "metis.insights.good_labels"

_GROUP = "Miglioramento continuo"

settings = SettingsClient("metis")
settings.declare([
    setting(MAX_EXAMPLES, "Esempi massimi per dataset", "int", 5000, group=_GROUP, min=1, max=100000, order=0,
            help="Tetto agli esempi raccolti quando costruisco un dataset di addestramento."),
    setting(DEDUPLICATE, "Rimuovi i doppioni", "bool", True, group=_GROUP, order=1,
            help="Scarta le conversazioni quasi identiche quando non indicato diversamente."),
    setting(QUALITY_LABELS, "Qualità incluse nel dataset", "list", ["excellent", "good"], group=_GROUP,
            order=2, help="Quali voti delle risposte (es. excellent, good) entrano nel dataset di addestramento."),
    setting(GOOD_LABELS, "Voti considerati buoni", "list", ["excellent", "good"], group=_GROUP, order=3,
            advanced=True,
            help="Nel resoconto dei punti deboli, le risposte con questi voti non contano come errori."),
]).declare_log_level()


def labels(key: str) -> list[str]:
    """A list setting as clean lowercase-preserving strings (accepts a comma string too)."""
    raw = settings.get(key)
    items = raw.split(",") if isinstance(raw, str) else (raw or [])
    return [str(x).strip() for x in items if str(x).strip()]


def max_examples() -> int:
    try:
        return max(1, int(settings.get(MAX_EXAMPLES)))
    except (TypeError, ValueError):
        return 5000


def deduplicate() -> bool:
    value = settings.get(DEDUPLICATE)
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(value)
