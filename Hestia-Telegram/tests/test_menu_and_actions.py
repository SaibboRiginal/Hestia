"""Menus as configuration, every function reachable, the action flow, every button handled, no stray emoji
(docs/work/2026-10-23-telegram-da-zero §5, acceptance criteria)."""
from __future__ import annotations

import ast
import re
import sys
from collections import deque
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "Hestia-Telegram" / "app"
sys.path.insert(0, str(ROOT / "tools" / "governance"))


def _module_tools():
    from check_telegram import module_tools
    from telegram_bot import catalog, local_actions
    tools = [catalog.Tool(name=t["name"], title=t["title"], service=t["service"],
                          group=str(t["telegram_group"]).lower(), hints=t["telegram"] or {}, index=i,
                          writes=t["method"] != "GET", schema=t["parameters"])
             for i, t in enumerate(module_tools(ROOT))]
    return tools + local_actions.tools()


@pytest.fixture
def ui_env(monkeypatch):
    """Fake bot that remembers the markup of the last card; the catalog = every module's tools."""
    import telegram_bot.core as core
    from telegram_bot import catalog
    from telegram_bot.menu import model
    bot = _fake_bot()
    core.bot = bot
    tools = _module_tools()
    catalog.set_tools(tools)
    layout: dict = {}
    monkeypatch.setattr(model, "layout", lambda: layout)
    monkeypatch.setattr(catalog, "run", lambda tool, chat, args, timeout=30: (False, None))
    monkeypatch.setattr(catalog, "route", lambda *a, **kw: (False, None))
    yield bot, tools, layout
    catalog.set_tools([])


def _last_markup(bot):
    calls = [c for c in bot.method_calls if c[0] in ("edit_message_text", "send_message")]
    return calls[-1].kwargs.get("reply_markup") if calls else None


def _callbacks(markup) -> list[str]:
    if markup is None:
        return []
    return [b.callback_data for row in markup.keyboard for b in row if getattr(b, "callback_data", None)]


def _fake_bot():
    bot = MagicMock()
    bot.send_message.return_value = MagicMock(message_id=500)
    return bot


def _call(data):
    return MagicMock(data=data, id="cb", message=MagicMock(chat=MagicMock(id=12345), message_id=77),
                     from_user=MagicMock(id=99999))


def _walk(bot):
    """From «Aree», follow every navigation button; returns {tool name: taps from the keyboard}."""
    from telegram_bot import nav, store
    nav.aree(12345)
    queue = deque([(cb, 2) for cb in _callbacks(_last_markup(bot))])
    seen, reached = set(), {}
    while queue:
        data, taps = queue.popleft()
        if data in seen:
            continue
        seen.add(data)
        if data.startswith("t:"):
            reached.setdefault(store.resolve(data.split(":")[1]), taps)
            continue
        if not data.startswith("n:"):
            continue
        nav.handle(_call(data))
        queue.extend((cb, taps + 1) for cb in _callbacks(_last_markup(bot)))
    return reached


@pytest.mark.unit
class TestReachability:
    def test_every_tool_of_every_module_is_reachable(self, ui_env):
        bot, tools, _ = ui_env
        from telegram_bot.menu import model
        menu = model.current()
        reached = _walk(bot)
        missing = [t.name for t in tools if t.name not in menu.hidden and t.name not in reached]
        assert not missing, missing
        assert len(tools) >= 165
        # Hidden = steps reached only from a result card (confirm after a preview / a backup list), never a function.
        assert set(menu.hidden) <= {"feedback_submit", "voce_on", "voce_off", "importa_conferma", "importa_annulla",
                                    "ripristina_conferma"}
        # Aree › area › Tutte le azioni › section › action (+ «Altre ›» pages)
        assert max(reached.values()) <= 8

    def test_sample_layout_moves_renames_and_loses_nothing(self, ui_env):
        bot, tools, layout = ui_env
        layout.update({"areas": {"spese": {"label": "Soldi", "emoji": "💰", "primary": ["finance_add"]},
                                 "viaggi": {"label": "Viaggi", "emoji": "🧳", "order": 5}},
                       "tools": {"wardrobe_packing": {"area": "viaggi", "label": "Valigia"},
                                 "non_esiste": {"area": "viaggi"}}})
        from telegram_bot.menu import model
        menu = model.current()
        assert menu.areas[0].key == "viaggi" and menu.area("viaggi").names == ["wardrobe_packing"]
        assert menu.area("spese").label == "Soldi" and menu.area("spese").primary == ["finance_add"]
        assert menu.label("wardrobe_packing") == "Valigia"
        reached = _walk(bot)
        assert all(t.name in reached for t in tools if t.name not in menu.hidden)

    def test_unknown_area_goes_to_altro_never_dropped(self):
        from telegram_bot.catalog import Tool
        from telegram_bot.menu import model
        menu = model.build([Tool(name="x_strano", title="Strano", group="area_che_non_esiste")], {})
        assert menu.tool_area["x_strano"] == "altro" and menu.area("altro").names == ["x_strano"]

    def test_slash_menu_has_ten_entries(self):
        from telegram_bot.menu import model
        assert [c for c, _ in model.build([], {}).commands] == [
            "oggi", "aree", "adesso", "scopri", "notifiche", "impostazioni", "nuova", "voce", "stato", "aiuto"]

    def test_adesso_and_scopri_commands_open_their_tools(self, ui_env, monkeypatch):
        import telegram_runtime
        from telegram_bot import actions
        opened = []
        monkeypatch.setattr(actions, "from_command", lambda chat, name, args: opened.append(name) or True)
        assert telegram_runtime.open_command(12345, "adesso") and telegram_runtime.open_command(12345, "scopri")
        assert opened == ["metis_adesso", "metis_scopri"]


@pytest.mark.unit
class TestActionFlow:
    def _tool(self, writes=True, destructive=False):
        from telegram_bot import catalog
        return catalog.Tool(name="finance_add", title="Registra spesa", group="spese", writes=writes,
                            destructive=destructive, schema={"type": "object", "required": ["amount", "category"],
                                                             "properties": {
                                                                 "amount": {"type": "number"},
                                                                 "category": {"type": "string",
                                                                              "enum": ["bar", "spesa"]},
                                                                 "note": {"type": "string"}}})

    def test_ask_in_words_buttons_confirm_run_result(self, monkeypatch):
        import telegram_bot.core as core
        from telegram_bot import actions, catalog, store
        from telegram_bot.menu import model
        bot = _fake_bot()
        core.bot = bot
        tool = self._tool()
        catalog.set_tools([tool])
        monkeypatch.setattr(model, "layout", lambda: {})
        ran = []
        monkeypatch.setattr(catalog, "run", lambda t, chat, args, timeout=30: ran.append(args) or (
            True, {"display": {"title": "Spesa registrata", "items": [{"title": "Bar", "meta": ["2,50 €"]}]}}))

        actions.start(12345, "finance_add")
        first = bot.send_message.call_args
        assert "<b>Importo</b>" in first[0][1] and "Passo 1 di 2" in first[0][1]
        assert "amount" not in first[0][1]                                    # never the technical name
        assert actions.on_text(12345, "due euro") is True                     # not a number: asked again
        assert "Scrivi un numero" in bot.edit_message_text.call_args[0][0]
        assert actions.on_text(12345, "2,50") is True
        markup = bot.edit_message_text.call_args.kwargs["reply_markup"]
        assert [b.text for b in markup.keyboard[0]] == ["Bar", "Spesa"]
        actions.handle_flow(_call("f:v:0"))
        confirm = bot.edit_message_text.call_args
        assert "Confermi?" in confirm[0][0] and "Importo: 2,5" in confirm[0][0]
        ok_button = confirm.kwargs["reply_markup"].keyboard[0][0]
        assert ok_button.text == "Conferma" and ok_button.style == "success"
        actions.handle_flow(_call("f:ok"))
        assert ran == [{"amount": 2.5, "category": "bar"}]
        assert "Spesa registrata" in bot.edit_message_text.call_args[0][0]
        assert store.get_flow(12345)["mode"] == "done"
        catalog.set_tools([])

    def test_destructive_says_elimina_in_red(self, monkeypatch):
        import telegram_bot.core as core
        from telegram_bot import actions, catalog
        from telegram_bot.menu import model
        core.bot = _fake_bot()
        tool = catalog.Tool(name="finance_delete", title="Elimina movimento", writes=True, destructive=True,
                            schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]})
        catalog.set_tools([tool])
        monkeypatch.setattr(model, "layout", lambda: {})
        actions.start(12345, "finance_delete", preset={"id": "m1"})
        button = core.bot.send_message.call_args.kwargs["reply_markup"].keyboard[0][0]
        assert button.text == "Elimina" and button.style == "danger"
        catalog.set_tools([])

    def test_typed_command_fills_the_first_value(self, monkeypatch):
        import telegram_bot.core as core
        from telegram_bot import actions, catalog, store
        from telegram_bot.menu import model
        core.bot = _fake_bot()
        catalog.set_tools([self._tool()])
        monkeypatch.setattr(model, "layout", lambda: {})
        assert actions.from_command(12345, "finance_add", "12,50 category=bar")
        assert store.get_flow(12345)["values"] == {"category": "bar", "amount": 12.5}
        assert store.get_flow(12345)["mode"] == "confirm"
        catalog.set_tools([])

    def test_keyboard_tap_ends_the_flow_and_says_so(self, monkeypatch, fake_message):
        import telegram_bot.core as core
        import telegram_runtime
        from telegram_bot import actions, catalog, nav, store
        from telegram_bot.menu import model
        core.bot = _fake_bot()
        catalog.set_tools([self._tool()])
        monkeypatch.setattr(model, "layout", lambda: {})
        actions.start(12345, "finance_add")
        monkeypatch.setattr(nav, "open_door", lambda chat, door: True)
        telegram_runtime.on_message(fake_message(text="Oggi"))
        assert store.get_flow(12345) is None
        assert "Ho lasciato perdere: Registra spesa" in core.bot.edit_message_text.call_args[0][0]
        catalog.set_tools([])


@pytest.mark.unit
class TestAdesso:
    def test_oggi_shows_adesso_with_reasons_and_buttons(self, ui_env, monkeypatch):
        bot, _, _ = ui_env
        from telegram_bot import catalog, nav, store
        items = {"items": [{"tool": "metis_scopri", "reason": "Di solito a quest'ora"},
                           {"tool": "non_esiste", "reason": "x"}]}
        monkeypatch.setattr(catalog, "route", lambda svc, path, *a, **kw: (True, items) if path ==
                            "api/metis/adesso" else (False, None))
        nav.oggi(12345)
        html = bot.send_message.call_args.args[1]
        assert "Adesso" in html and "Di solito a quest'ora" in html and "non_esiste" not in html
        assert f"t:{store.sid('metis_scopri')}" in _callbacks(_last_markup(bot))

    def test_oggi_keeps_fixed_actions_when_metis_is_away(self, ui_env):
        bot, _, _ = ui_env
        from telegram_bot import nav, store
        nav.oggi(12345)
        assert f"t:{store.sid('agenda_today')}" not in _callbacks(_last_markup(bot))
        assert any(c.startswith("t:") for c in _callbacks(_last_markup(bot)))

    def test_starting_an_action_pushes_a_tap(self, ui_env, monkeypatch):
        from telegram_bot import actions, usage
        taps = []
        monkeypatch.setattr(usage, "tap", lambda ref, kind="tool", label="": taps.append(ref))
        monkeypatch.setattr(actions, "_advance", lambda chat, flow: None)
        actions.start(12345, "metis_scopri")
        assert taps == ["metis_scopri"]


@pytest.mark.unit
class TestCallbacks:
    def test_every_drawn_button_has_a_handler(self, ui_env, monkeypatch):
        bot, _, _ = ui_env
        import telegram_runtime
        from telegram_bot import nav
        from telegram_bot.menu import editor
        drawn: set[str] = set()
        for draw in (lambda: nav.aree(12345), lambda: nav.impostazioni(12345), lambda: nav.oggi(12345),
                     lambda: editor.root(12345), lambda: editor.area(12345, "spese"),
                     lambda: editor.primary(12345, "spese")):
            draw()
            drawn |= set(_callbacks(_last_markup(bot)))
        stale = []
        monkeypatch.setattr(nav, "stale", lambda chat, mid=None: stale.append(mid))
        prefixes = {d.split(":")[0] for d in drawn}
        assert prefixes >= {"n", "t", "m", "set"}
        for data in sorted(drawn):
            telegram_runtime._route_callback(_call(data))
        assert not stale

    def test_old_buttons_answer_with_a_fresh_menu(self, monkeypatch):
        import telegram_bot.core as core
        import telegram_runtime
        from telegram_bot import nav
        core.bot = _fake_bot()
        shown = []
        monkeypatch.setattr(nav, "aree", lambda chat, mid=None: shown.append(chat))
        telegram_runtime._route_callback(_call("grp:fitness"))
        core.bot.answer_callback_query.assert_called_with("cb", "Questo menu è vecchio")
        assert shown == [12345]


# ── strings: no emoji except the allowed markers ─────────────────────────────

ALLOWED = set("🔴🟠🟢🔵👍👎🔄")
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿⭐⭕⏩-⏺⌚⌛✅❌⚠ℹ]")


def _strings(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = {id(n.body[0].value) for n in ast.walk(tree)
                  if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef))
                  and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            yield node.lineno, node.value


@pytest.mark.format
def test_client_strings_have_no_stray_emoji():
    bad = []
    for path in sorted(APP.rglob("*.py")):
        if path.name == "defaults.py":           # the area emoji live here, once
            continue
        for line, text in _strings(path):
            if "event=" in text:                 # log lines
                continue
            stray = {ch for ch in EMOJI.findall(text)} - ALLOWED
            if stray:
                bad.append(f"{path.relative_to(APP)}:{line} {''.join(sorted(stray))} {text[:50]!r}")
    assert not bad, "\n".join(bad)


@pytest.mark.format
def test_user_texts_name_no_module():
    modules = re.compile(r"\b(Oracle|Hermes|Themis|Chronos|Archive|Hecate|Hephaestus|Forge|Argus|Athena|Metis|"
                         r"Hercules|Hygieia|Plutus|Scout|Iris|Atlas|Echo)\b")
    bad = []
    for path in sorted(APP.rglob("*.py")):
        for line, text in _strings(path):
            if "event=" in text or text.startswith(("http", "/api", "api/")) or "_" in text.split(" ")[0]:
                continue
            if modules.search(text) and " " in text:
                bad.append(f"{path.relative_to(APP)}:{line} {text[:60]!r}")
    assert not bad, "\n".join(bad)
