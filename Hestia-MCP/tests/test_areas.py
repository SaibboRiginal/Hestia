"""Tests — areas and texts for people (hestia_common.areas, dossier docs/work/2026-10-29-revisione-e-test-frontend §6.1)."""
from __future__ import annotations

import pytest

from core.ui_tools import as_command
from hestia_common.areas import area, area_of, for_people

pytestmark = pytest.mark.unit


def test_for_people_drops_model_notes():
    text = ("Agenda di Hestia stessa (NON il calendario dell'utente): cosa l'assistente ha pianificato — finestre "
            "(es. Claude Pro di notte), job periodici. Usala quando l'utente chiede cosa fa Hestia.")
    out = for_people(text)
    assert "(" not in out and "NON" not in out and "Usala" not in out
    assert out.startswith("Agenda di Hestia stessa") and out.endswith(".")
    assert for_people("Le scadenze aperte (days = entro quanti giorni; category).") == "Le scadenze aperte."
    assert for_people({"summary": "Scritto a mano", "description": "x (y)"}) == "Scritto a mano"


def test_area_from_group_alias_or_module():
    assert area_of({"telegram_group": "fitness"})["label"] == "Allenamento"
    assert area_of({}, "kairos")["label"] == "Scadenze"
    assert area_of({"telegram_group": "nonesiste"}, "nessuno")["key"] == "altro"
    assert area("Cura di sé")["key"] == "selfcare"


def test_comandi_command_carries_area_and_summary():
    tool = {"name": "scadenze_list", "title": "Scadenze", "description": "Le scadenze aperte (days; status).",
            "_meta": {"hestia": {"service": "kairos", "telegram_group": "scadenze"}}}
    cmd = as_command(tool)
    assert (cmd["area_label"], cmd["summary"]) == ("Scadenze", "Le scadenze aperte.")
