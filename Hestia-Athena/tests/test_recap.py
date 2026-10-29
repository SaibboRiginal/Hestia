"""Daily recap (docs/work/2026-10-20-recap-giornaliero): collect pieces from every module with
``recap_endpoint`` (Athena's own included), Oracle writes, template when it cannot, nothing on a quiet day,
Hermes delivery with ``replaces``, history in Archive."""
from __future__ import annotations

from datetime import date, datetime

import pytest

from core import athena_settings as S
from core.recap import (RecapComposer, build_prompt, clean_text, has_content, moment_days, piece_actions,
                         template_text)

pytestmark = pytest.mark.unit

HERCULES = {"module": "hercules", "title": "Allenamento", "emoji": "🏋️", "order": 30,
            "done": [{"text": "Push A: 18 serie, panca 80×5 (record)", "tone": "success"}],
            "next": [{"text": "Pull B alle 18:30"}]}
PLUTUS = {"module": "plutus", "title": "Spese", "order": 60, "done": [{"text": "Spesi 42 € (spesa 30 €)"}]}
ATHENA = {"module": "athena", "title": "Da tenere d'occhio", "order": 900,
          "done": [{"text": "Sonno corto 3 notti su 4"}]}


class _Resp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code, self.content = payload, status, b"x"

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeHub:
    """Hub registry + routes. ``pieces``: service → payload (or Exception); ``oracle``: text or None (down)."""

    def __init__(self, pieces, oracle="<b>Oggi</b> bene.", services=None):
        self.pieces, self.oracle, self.calls = pieces, oracle, []
        self.services = services if services is not None else [
            {"name": n, "status": "online", "capabilities": {"recap_endpoint": "/api/module/recap"}}
            for n in pieces] + [{"name": "hub", "capabilities": {}}]

    def get(self, url, timeout=None):
        assert url.endswith("/registry/services")
        return _Resp({"services": self.services})

    def post(self, url, json=None, timeout=None):
        service = url.split("/route/", 1)[1].split("/", 1)[0]
        self.calls.append((service, json))
        if service == "oracle":
            if self.oracle is None:
                return _Resp({"status_code": 503, "payload": {"detail": "down"}})
            return _Resp({"status_code": 200, "payload": {"response": self.oracle}})
        if service in {"hermes", "archive"}:
            return _Resp({"status_code": 200, "payload": {"ok": True}})
        value = self.pieces[service]
        if isinstance(value, Exception):
            raise value
        return _Resp({"status_code": 200, "payload": value})


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    for key, value in ((S.RECAP_STYLE, "amichevole"), (S.RECAP_MAX_CHARS, 900), (S.RECAP_PIECE_TIMEOUT, 2.0)):
        monkeypatch.setitem(S.settings._effective, key, value)


def _composer(hub):
    return RecapComposer("http://hub/api", session=hub, now=lambda: datetime(2026, 10, 20, 21, 30))


def test_moment_days():
    today = date(2026, 10, 20)
    assert moment_days("sera", today=today) == (date(2026, 10, 20), date(2026, 10, 21))
    assert moment_days("mattina", today=today) == (date(2026, 10, 19), date(2026, 10, 20))


def test_collects_every_piece_sorted_including_athena_and_skips_failures():
    hub = FakeHub({"athena": ATHENA, "plutus": PLUTUS, "hercules": HERCULES,
                   "wardrobe": RuntimeError("timeout"), "scout": {"module": "scout", "empty": True}})
    pieces = _composer(hub).collect(date(2026, 10, 20), date(2026, 10, 21))
    assert [p["module"] for p in pieces] == ["hercules", "plutus", "athena"]
    q = next(j for s, j in hub.calls if s == "hercules")
    assert q["method"] == "GET" and q["query"] == {"day": "2026-10-20", "next": "2026-10-21"}


def test_offline_services_are_not_asked():
    hub = FakeHub({"hercules": HERCULES}, services=[
        {"name": "hercules", "status": "offline", "capabilities": {"recap_endpoint": "/api/module/recap"}}])
    assert _composer(hub).collect(date(2026, 10, 20), date(2026, 10, 21)) == []


def test_compose_writes_with_oracle_delivers_and_stores():
    hub = FakeHub({"hercules": HERCULES, "plutus": PLUTUS})
    out = _composer(hub).compose(momento="sera", trigger="agenda")
    assert out["status"] == "ok" and out["text"] == "<b>Oggi</b> bene." and not out["fallback"]
    assert out["delivered"] and out["day"] == "2026-10-20"
    oracle = next(j for s, j in hub.calls if s == "oracle")
    assert oracle["body"]["use_case"] == "athena.recap"
    assert "[Allenamento|fatto] Push A" in oracle["body"]["prompt"]
    hermes = next(j for s, j in hub.calls if s == "hermes")["body"]
    assert hermes["payload"]["replaces"] == "athena.recap"
    assert hermes["payload"]["_link"] == {"module": "athena", "page": "recap"}
    assert hermes["payload"]["level"] == "info" and hermes["payload"]["target"] == "owner"
    archive = next(j for s, j in hub.calls if s == "archive")["body"]
    assert archive["domain"] == "recap" and archive["entity_id"] == "athena-recap-2026-10-20-sera"


def test_oracle_down_falls_back_to_template():
    hub = FakeHub({"hercules": HERCULES, "plutus": PLUTUS}, oracle=None)
    out = _composer(hub).compose(momento="sera")
    assert out["fallback"] and out["delivered"]
    assert "Push A" in out["text"] and "<b>Domani, mercoledì 21 ott</b>" in out["text"]
    assert "Pull B alle 18:30" in out["text"]


def test_quiet_day_sends_nothing():
    hub = FakeHub({"hercules": {"module": "hercules", "empty": True}})
    out = _composer(hub).compose(momento="sera")
    assert out["status"] == "empty" and not out["delivered"]
    assert not [s for s, _ in hub.calls if s in {"oracle", "hermes", "archive"}]


def test_chat_request_is_not_delivered_nor_stored():
    hub = FakeHub({"hercules": HERCULES})
    out = _composer(hub).compose(momento="mattina", deliver=False, trigger="chat")
    assert out["text"] and not out["delivered"]
    assert not [s for s, _ in hub.calls if s in {"hermes", "archive"}]
    assert out["day"] == "2026-10-19"


def test_prompt_is_caveman_and_has_no_module_names():
    prompt = build_prompt([HERCULES, PLUTUS], "sera", date(2026, 10, 20), date(2026, 10, 21), "asciutto", 600)
    assert "hercules" not in prompt.lower() and "plutus" not in prompt.lower()
    assert "Max 600 caratteri" in prompt and "asciutto" in prompt


def test_clean_text_keeps_bold_and_caps_length():
    text = clean_text("**Oggi**\n<p>riga</p>\n" + "x" * 50, 30)
    assert text.startswith("<b>Oggi</b>") and "<p>" not in text and len(text) <= 31


def test_template_escapes_html():
    out = template_text([{"title": "Spese", "done": [{"text": "A & B <x>"}]}], "sera",
                        date(2026, 10, 20), date(2026, 10, 21))
    assert "A &amp; B &lt;x&gt;" in out


def test_has_content():
    assert not has_content([]) and has_content([PLUTUS])


def test_piece_actions_ride_under_the_recap():
    """B9: a module piece (even an empty one) can ask for a button under the recap; ids unique per module."""
    pieces = [{"module": "hygieia", "empty": True, "actions": [{"label": "Racconta la giornata",
                                                                "command": "selfcare_diario_voce"}]},
              {"module": "hercules", "title": "Allenamento", "done": [{"text": "Push A"}]}]
    assert piece_actions(pieces) == [{"label": "Racconta la giornata", "command": "selfcare_diario_voce",
                                      "id": "hygieia0"}]
    assert has_content(pieces)
    assert "Racconta" not in template_text(pieces, "sera", date(2026, 10, 29), date(2026, 10, 30))
