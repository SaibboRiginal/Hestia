"""assistant_profile: Hestia's persona + the user's instructions + memory for another AI (mod «hestia» in Claude).

SPEC docs/work/2026-10-30-hestia-in-claude §3.3. No LLM, Themis and Archive mocked."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.services import assistant_profile, oracle_settings


def _memory(facts):
    svc = MagicMock()
    svc.recall.return_value = (True, [{"fact": f} for f in facts])
    return svc


def _build(memory=None, *, max_tokens=1500, instructions=None):
    with patch.object(oracle_settings, "get_int", return_value=max_tokens), \
            patch.object(oracle_settings, "chat_instructions", return_value=instructions or []):
        return assistant_profile.build(memory)


@pytest.mark.unit
class TestProfile:
    def test_persona_without_telegram_formatting(self):
        text = _build()["text"]
        assert "Sei Hestia" in text
        assert "FORMATO HTML TELEGRAM" not in text and "{conversation_style_contract}" not in text
        assert "SEI HESTIA DENTRO CLAUDE" in text and "memory_note" in text

    def test_user_instructions_and_memory(self):
        out = _build(_memory(["Va in palestra il martedì", "Non mangia latticini"]),
                     instructions=["Tono: diretto, essenziale, niente preamboli.", "Istruzioni dell'utente: breve"])
        assert "Tono: diretto" in out["text"] and "Istruzioni dell'utente: breve" in out["text"]
        assert "- Va in palestra il martedì" in out["text"] and out["memories"] == 2

    def test_cap_drops_memory_first(self):
        facts = [f"Fatto numero {i} " + "x" * 200 for i in range(20)]
        out = _build(_memory(facts), max_tokens=1200)
        assert len(out["text"]) <= 1200 * 4 + 200   # fixed parts are never cut, memory fills what is left
        assert out["memories"] < 20

    def test_revision_follows_content(self):
        a = _build(_memory(["A"]))["revision"]
        assert a == _build(_memory(["A"]))["revision"]
        assert a != _build(_memory(["B"]))["revision"]

    def test_memory_down_still_answers(self):
        svc = MagicMock()
        svc.recall.side_effect = RuntimeError("archive down")
        out = _build(svc)
        assert out["memories"] == 0 and "Sei Hestia" in out["text"]

    def test_unknown_client_falls_back_to_claude(self):
        with patch.object(oracle_settings, "get_int", return_value=1500), \
                patch.object(oracle_settings, "chat_instructions", return_value=[]):
            assert assistant_profile.build(None, client="altro")["client"] == "claude"
