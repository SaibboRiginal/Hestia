"""Visual grammar, persisted state, inputs from the schema, results without the model
(docs/work/2026-10-23-telegram-da-zero §3, §5.5, §5.8, §6)."""
from __future__ import annotations

from datetime import date

import pytest


# ── ui ───────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestUi:
    def test_card_has_one_marker_on_the_title_only(self):
        from telegram_bot import ui
        html = ui.card("Spese del mese", [ui.item("Bar", ["12,50 €"])], subtitle="ottobre", marker="💶")
        lines = html.split("\n")
        assert lines[0] == "💶 <b>Spese del mese</b>"
        assert lines[1] == "<i>ottobre</i>"
        assert lines[2] == "• Bar · 12,50 €"

    def test_tone_dot_wins_over_area_marker(self):
        from telegram_bot import ui
        assert ui.title_line("Crema solare", marker="✨", tone="warning") == "🟠 <b>Crema solare</b>"

    def test_crumbs_and_escape(self):
        from telegram_bot import ui
        assert ui.title_line("A & B", crumbs=["Aree"]) == "<b>Aree › A &amp; B</b>"

    def test_label_strips_emoji_and_cuts_on_a_word(self):
        from telegram_bot import ui
        assert ui.label("🏋️ Allenamento di oggi") == "Allenamento di oggi"
        cut = ui.label("Registra una misura del corpo molto lunga")
        assert len(cut) <= ui.LABEL_MAX and cut.endswith("…") and " " not in cut[-2:]

    def test_error_never_shows_the_exception(self):
        from telegram_bot import ui
        assert ui.error("Non sono riuscita a creare l'evento").startswith("🔴 <b>Non sono riuscita")

    def test_buttons_style_copy_disabled(self):
        from telegram_bot import ui
        b = ui.button("Elimina", "f:ok", style="danger")
        assert b.style == "danger" and b.callback_data == "f:ok"
        c = ui.button("Copia il codice", copy="abc")
        assert c.copy_text.text == "abc" and c.callback_data is None
        d = ui.button("Fatto · da WebUI", disabled=True)
        assert d.disabled is not None and d.callback_data is None
        assert len(ui.button("x", "y" * 100).callback_data) == 64

    def test_grid_two_per_row_long_alone(self):
        from telegram_bot import ui
        rows = ui.grid([ui.button("Oggi", "a"), ui.button("Domani", "b"),
                        ui.button("Una etichetta davvero lunga lunga", "c"), ui.button("X", "d")])
        assert [len(r) for r in rows] == [2, 1, 1]


# ── store ────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestStore:
    def test_short_ids_are_stable_and_survive_a_restart(self, _ui_store, tmp_path):
        store = _ui_store
        short = store.sid("fitness_log_measurement")
        assert len(short) == 6 and store.sid("fitness_log_measurement") == short
        store.reset_for_tests(str(tmp_path / "telegram_ui.json"))       # "restart": state read back from disk
        assert store.resolve(short) == "fitness_log_measurement"

    def test_flow_persisted_and_cleared(self, _ui_store, tmp_path):
        store = _ui_store
        store.set_flow(1, {"kind": "action", "tool": "finance_add", "values": {"amount": 12.5}})
        store.reset_for_tests(str(tmp_path / "telegram_ui.json"))
        assert store.get_flow(1)["values"] == {"amount": 12.5}
        store.clear_flow(1)
        assert store.get_flow(1) is None

    def test_most_used(self, _ui_store):
        for name in ("a", "b", "b", "c", "c", "c"):
            _ui_store.count_use(name)
        assert _ui_store.most_used(2) == ["c", "b"]
        assert _ui_store.most_used(5, {"a", "b"}) == ["b", "a"]


# ── inputs ───────────────────────────────────────────────────────────────────

def _tool(props, required=()):
    from telegram_bot.catalog import Tool
    return Tool(name="t", title="T", schema={"type": "object", "properties": props, "required": list(required)})


@pytest.mark.unit
class TestInputs:
    def test_fields_in_words_required_first(self):
        from telegram_bot import inputs
        fields = inputs.fields(_tool({"note": {"type": "string"}, "amount": {"type": "number"},
                                      "session_id": {"type": "string"}}, ["amount"]))
        assert [f.name for f in fields] == ["amount", "note"]          # session_id is filled by Telegram
        assert fields[0].label == "Importo" and fields[0].kind == "number" and fields[0].required

    def test_enum_becomes_buttons(self):
        from telegram_bot import inputs
        f = inputs.fields(_tool({"kind": {"type": "string", "enum": ["run", "bike"]}}))[0]
        assert f.kind == "choice" and inputs.quick_values(f) == [("Run", "run"), ("Bike", "bike")]

    def test_parse_numbers_dates_times(self):
        from telegram_bot import inputs
        today = date(2026, 10, 24)
        assert inputs.parse_date("domani", today) == date(2026, 10, 25)
        assert inputs.parse_date("25/10", today) == date(2026, 10, 25)
        assert inputs.parse_time("18.30") == "18:30"
        assert inputs.parse_datetime("domani 18:30", today) == ("2026-10-25T18:30:00", True)
        assert inputs.parse_datetime("domani", today) == ("2026-10-25", False)
        f = inputs.Field("amount", "Importo", "number")
        assert inputs.parse(f, "12,50 €") == (True, 12.5, "")
        assert inputs.parse(f, "dodici")[0] is False

    def test_date_alone_for_datetime_asks_the_time(self):
        from telegram_bot import inputs
        ok, value, problem = inputs.parse(inputs.Field("start_at", "Inizio", "datetime"), "dopodomani")
        assert ok and problem == "time" and len(value) == 10

    def test_human_datetime(self):
        from telegram_bot import inputs
        today = date(2026, 10, 24)
        assert inputs.human_datetime("2026-10-24T18:30:00", today) == "oggi 18:30"
        assert inputs.human_datetime("2026-10-27", today) == "mar 27 ott"


# ── render ───────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestRender:
    def test_display_block_wins(self):
        from telegram_bot.render import render
        r = render({"data": 1, "display": {"title": "Allenamento di oggi", "subtitle": "Push A",
                                           "items": [{"title": "Panca", "meta": ["4×8", "62,5 kg"]}],
                                           "actions": [{"label": "Inizia", "tool": "fitness_start", "style": "primary"}]}},
                   "x", "🏋️")
        assert r.html.startswith("🏋️ <b>Allenamento di oggi</b>\n<i>Push A</i>\n• Panca · 4×8 · 62,5 kg")
        assert r.actions[0].tool == "fitness_start" and r.actions[0].style == "primary"

    def test_generic_list_and_fields_without_ids(self):
        from telegram_bot.render import render
        r = render({"total": 42.5, "id": "abc", "items": [{"id": 1, "title": "Bar", "amount": 3.2,
                                                         "date": "2026-10-24"}]}, "Spese", "💶")
        assert "abc" not in r.html and "Totale: 42,5 €" in r.html
        assert "• Bar · " in r.html and "n/d" not in r.html

    def test_empty_and_text(self):
        from telegram_bot.render import render
        assert "Niente da mostrare" in render([], "Case").html
        assert render("Fatto tutto", "Ok").html.endswith("Fatto tutto")

    def test_error_payload_is_red(self):
        from telegram_bot.render import render
        assert render({"ok": False, "message": "Non trovato"}, "Cerca").html.startswith("🔴")
