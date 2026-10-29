"""B9 spoken evening diary (dossier docs/work/2026-10-24-tutto-brainstorm-cindy W4): the transcript becomes the day's
«giornata» entry, the evening recap offers «Racconta la giornata» until the day is told, reflection gets a signal.
Markers: unit
"""
import pytest

from app.core import signals as signals_engine
from app.core.service import DIARY_AREA, DIARY_TOOL, Invalid

from .test_hygieia import hy  # noqa: F401 — fixture

pytestmark = pytest.mark.unit


def test_voice_entry_keeps_transcript_and_audio(hy):  # noqa: F811
    row = hy.journal_voice({"text": " Oggi palestra e cena con amici ", "blob_id": "b1", "duration_s": 12.5})
    assert row["area"] == DIARY_AREA and row["note"] == "Oggi palestra e cena con amici"
    assert row["tags"] == ["voce"] and row["source"] == "voce"
    assert row["audio_id"] == "b1" and row["duration_s"] == 12.5


def test_voice_entry_needs_words(hy):  # noqa: F811
    with pytest.raises(Invalid):
        hy.journal_voice({"text": "  "})


def test_recap_offers_diary_until_told(hy):  # noqa: F811
    today = hy.today()
    from datetime import timedelta
    first = hy.recap(today, today + timedelta(days=1))
    assert first["actions"] == [{"label": "Racconta la giornata", "command": DIARY_TOOL}]
    assert "actions" not in hy.recap(today - timedelta(days=1), today)          # only the evening of today
    hy.journal_voice({"text": "Giornata tranquilla"})
    assert "actions" not in hy.recap(today, today + timedelta(days=1))


def test_signal_and_detail_for_reflection(hy):  # noqa: F811
    hy.journal_voice({"text": "Stanco ma contento"})
    found = [s for s in signals_engine.evaluate(hy)[0] if s["key"] == "diario"]
    assert found and "Stanco ma contento" in found[0]["text"]
    assert "Stanco ma contento" in signals_engine.detail(hy, "diario")
