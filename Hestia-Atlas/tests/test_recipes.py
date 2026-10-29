"""Site recipes (Cindy 12): validation, binding, execution on a fake page, breakage report."""
from __future__ import annotations

import asyncio
import logging

import pytest

from app import recipes

pytestmark = pytest.mark.unit


class _Node:
    def __init__(self, text, attrs=None):
        self.text, self.attrs = text, attrs or {}

    async def inner_text(self):
        return self.text

    async def get_attribute(self, name):
        return self.attrs.get(name)


class _Page:
    url = "https://example.test/"

    def __init__(self, dom, fail_on=None):
        self.dom, self.fail_on, self.calls = dom, fail_on, []

    async def goto(self, url, **kw):
        self.calls.append(("goto", url))

    async def wait_for_selector(self, selector, **kw):
        if selector == self.fail_on:
            raise TimeoutError(f"timeout waiting for {selector}")

    async def query_selector_all(self, selector):
        return self.dom.get(selector, [])


def _runner(page):
    return lambda work, timeout: asyncio.run(work(page))


def test_repo_recipes_are_valid():
    loaded = recipes.load_all()
    assert {"duckduckgo", "pagina"} <= set(loaded)


def test_validation_rejects_bad_recipes():
    good = {"name": "x_site", "params": {"q": {}}, "steps": [{"op": "goto", "url": "https://a/?q={q}"}],
            "extract": {"t": {"selector": "h1"}}}
    recipes.validate(good)
    for bad in ({**good, "name": "Bad Name"}, {**good, "steps": [{"op": "hover", "selector": "a"}]},
                {**good, "steps": [{"op": "goto", "url": "https://a/?q={missing}"}]},
                {**good, "steps": [{"op": "wait"}]}, {**good, "extract": {}}):
        with pytest.raises(recipes.RecipeError):
            recipes.validate(bad)


def test_run_extracts_fields_and_quotes_url_params():
    recipe = recipes.load_all()["duckduckgo"]
    page = _Page({".result__a": [_Node("Uno", {"href": "https://1"}), _Node("Due", {"href": "https://2"})],
                  ".result__snippet": [_Node("  primo\n risultato ")]})
    status, out = recipes.run("duckduckgo", {"q": "a b&c"}, _runner(page), recipes={"duckduckgo": recipe})
    assert status == 200 and out["status"] == "ok"
    assert out["fields"]["titles"] == ["Uno", "Due"] and out["fields"]["links"] == ["https://1", "https://2"]
    assert out["fields"]["snippets"] == ["primo risultato"]
    assert page.calls[0] == ("goto", "https://html.duckduckgo.com/html/?q=a%20b%26c")


def test_missing_param_and_unknown_recipe():
    all_ = recipes.load_all()
    assert recipes.run("duckduckgo", {}, _runner(_Page({})), recipes=all_)[0] == 400
    assert recipes.run("nope", {}, _runner(_Page({})), recipes=all_)[0] == 404


def test_broken_recipe_is_logged_for_the_monitor(caplog):
    all_ = recipes.load_all()
    with caplog.at_level(logging.WARNING, logger="hestia_atlas.recipes"):
        status, out = recipes.run("duckduckgo", {"q": "x"}, _runner(_Page({}, fail_on=".result")), recipes=all_)
        assert status == 200 and out["status"] == "broken" and out["step"] == 1
        status, out = recipes.run("duckduckgo", {"q": "x"}, _runner(_Page({})), recipes=all_)
        assert out["status"] == "broken" and out["field"] == "titles"
    assert "event=atlas_recipe_broken" in caplog.text


def test_browser_unavailable():
    status, out = recipes.run("pagina", {"url": "https://a"}, lambda work, t: None, recipes=recipes.load_all())
    assert status == 503
