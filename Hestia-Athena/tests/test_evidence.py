"""First observe, then propose: improvements and setting changes wait for proof on several days.
SPEC docs/work/2026-11-13-prima-osserva-poi-propone. Marker: unit."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from core import athena_settings as S
from core.athena_settings import settings
from core.evidence import Evidence
from core.reflection import local_day
from core.schemas import ActionCandidate

pytestmark = pytest.mark.unit
DAY0 = datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)


def _evidence(monkeypatch, *, min_days=5, seen_days=3, window=14, rows=None):
    monkeypatch.setitem(settings._effective, S.EVIDENCE_MIN_DAYS, min_days)
    monkeypatch.setitem(settings._effective, S.EVIDENCE_SEEN_DAYS, seen_days)
    monkeypatch.setitem(settings._effective, S.EVIDENCE_WINDOW_DAYS, window)
    ev = Evidence("http://hub/api")
    ev.reader = MagicMock()
    ev.reader.rows.return_value = [{"data": r} for r in (rows or [])]
    ev._session = MagicMock()
    return ev


def _improvement(title="Errori ricorrenti nel modulo meteo"):
    return ActionCandidate(kind="improvement", title=title, reasoning="tre timeout")


def test_first_days_she_only_observes(monkeypatch):
    ev = _evidence(monkeypatch)
    for day in range(5):
        out = ev.weigh(_improvement(), now=DAY0 + timedelta(days=day))
        assert out["ready"] is False
    assert "Sto ancora osservando: 4 giorni su 5" in out["note"]
    out = ev.weigh(_improvement(), now=DAY0 + timedelta(days=5))
    assert out["ready"] is True and "Visto in 6 giorni diversi dal 1/11" in out["note"]


def test_once_is_not_enough_it_must_come_back_on_different_days(monkeypatch):
    ev = _evidence(monkeypatch, rows=[{"key": "_start", "first_day": "2026-10-01"}])
    c = ActionCandidate(kind="setting", setting_key="oracle.chat.timeout", setting_value="90")
    assert ev.weigh(c, now=DAY0)["ready"] is False
    again = ev.weigh(c, now=DAY0 + timedelta(hours=3))                # same day: still one day
    assert again["ready"] is False and again["seen_days"] == 1
    assert "visto in 1 giorno su 3" in again["note"]
    assert ev.weigh(c, now=DAY0 + timedelta(days=2))["ready"] is False
    assert ev.weigh(c, now=DAY0 + timedelta(days=4))["ready"] is True
    # Proposed: it starts again from zero, no proposal every day.
    assert ev.weigh(c, now=DAY0 + timedelta(days=5))["ready"] is False


def test_old_sightings_stop_counting(monkeypatch):
    ev = _evidence(monkeypatch, window=7, rows=[{"key": "_start", "first_day": "2026-10-01"}])
    c = _improvement()
    ev.weigh(c, now=DAY0)
    ev.weigh(c, now=DAY0 + timedelta(days=1))
    out = ev.weigh(c, now=DAY0 + timedelta(days=20))
    assert out["ready"] is False and out["seen_days"] == 1


def test_the_same_finding_in_other_words_is_the_same(monkeypatch):
    ev = _evidence(monkeypatch, rows=[{"key": "_start", "first_day": "2026-10-01"}])
    ev.weigh(_improvement("Errori ricorrenti nel modulo meteo"), now=DAY0)
    ev.weigh(_improvement("Modulo meteo: errori ricorrenti di timeout"), now=DAY0 + timedelta(days=1))
    out = ev.weigh(_improvement("Errori ricorrenti del modulo meteo"), now=DAY0 + timedelta(days=2))
    assert out["ready"] is True
    other = ev.weigh(_improvement("Risposte troppo lunghe nella chat vocale"), now=DAY0 + timedelta(days=2))
    assert other["ready"] is False and other["seen_days"] == 1


def test_faults_never_wait_and_pensa_ora_skips_the_wait(monkeypatch):
    ev = _evidence(monkeypatch)
    assert ev.weigh(ActionCandidate(kind="remediation", title="Hermes non risponde"), now=DAY0) == {
        "ready": True, "note": ""}
    out = ev.weigh(_improvement(), on_demand=True, now=DAY0)
    assert out["ready"] is True and "Chiesto da te" in out["note"]


def test_ledger_survives_a_restart_and_is_stored(monkeypatch):
    ev = _evidence(monkeypatch, rows=[{"key": "_start", "first_day": "2026-10-01"}])
    ev.weigh(_improvement(), now=DAY0)
    body = ev._session.post.call_args.kwargs["json"]
    assert body["method"] == "PUT" and body["body"]["rows"][0]["kind"] == "evidence"
    stored = body["body"]["rows"][0]["data"]
    again = _evidence(monkeypatch, rows=[{"key": "_start", "first_day": "2026-10-01"}, stored])
    assert again.weigh(_improvement(), now=DAY0 + timedelta(days=1))["seen_days"] == 2
    assert again.list()[0]["title"] == "Errori ricorrenti nel modulo meteo"
    assert again.known_days(DAY0) == 31


def test_unreadable_ledger_proposes_nothing(monkeypatch):
    ev = _evidence(monkeypatch)
    ev.reader.rows.side_effect = RuntimeError("archive down")
    out = ev.weigh(_improvement(), now=DAY0)
    assert out["ready"] is False and "non leggibile" in out["note"]
    assert ev.known_days(DAY0) == 0 and ev.list() == []
