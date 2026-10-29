"""Site recipes (Cindy 12, dossier docs/work/2026-10-24-tutto-brainstorm-cindy W3).

A recipe is a small declarative script for a site used often: go to → type → click → wait → extract. No model
looks at the page at every step: the assistant (tool ``atlas_ricetta``) or a module (Scout, via Hub
``POST /api/route/atlas/api/recipes/<name>/run``) only passes the parameters and gets the fields back.

Recipes are **code in the repo** (``Hestia-Atlas/recipes/<name>.json``, versioned, Forge fixes them), validated at
load. When a site changes and a recipe breaks (a step fails, or a required field comes back empty) Atlas logs
``event=atlas_recipe_broken`` at WARNING: Argus reads it like every module warning, alerts the owner and, when
it repeats, proposes the fix to Forge.

Shape::

    {"name": "duckduckgo", "title": "...", "description": "...",
     "params": {"q": {"description": "...", "required": true}},
     "steps": [{"op": "goto", "url": "https://.../?q={q}"}, {"op": "wait", "selector": ".result"}],
     "extract": {"results": {"selector": ".result__a", "all": true, "attr": "href", "required": true}}}

Ops: ``goto`` (url) · ``fill`` (selector, value) · ``click`` (selector) · ``press`` (selector, key) ·
``wait`` (selector or ms). ``{param}`` placeholders are replaced in url/value. Extract fields: selector, ``attr``
(default: text), ``all`` (list), ``required``, ``limit``.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

logger = logging.getLogger("hestia_atlas.recipes")

RECIPES_DIR = Path(__file__).resolve().parents[1] / "recipes"
OPS = {"goto": ("url",), "fill": ("selector", "value"), "click": ("selector",), "press": ("selector", "key"),
       "wait": ()}
_NAME = re.compile(r"^[a-z0-9_]{2,40}$")
_MAX_STEPS = 30
_MAX_TEXT = 2000


class RecipeError(ValueError):
    pass


def validate(recipe: dict) -> dict:
    """Raise RecipeError on a malformed recipe; returns it unchanged."""
    if not isinstance(recipe, dict) or not _NAME.match(str(recipe.get("name") or "")):
        raise RecipeError("name: 2-40 lowercase letters, digits or _")
    params = recipe.get("params") or {}
    if not isinstance(params, dict):
        raise RecipeError("params must be an object")
    steps = recipe.get("steps")
    if not isinstance(steps, list) or not steps or len(steps) > _MAX_STEPS:
        raise RecipeError(f"steps: 1-{_MAX_STEPS} steps")
    for i, step in enumerate(steps):
        op = step.get("op") if isinstance(step, dict) else None
        if op not in OPS:
            raise RecipeError(f"step {i}: unknown op {op!r}")
        missing = [k for k in OPS[op] if not step.get(k)]
        if missing or (op == "wait" and not step.get("selector") and not step.get("ms")):
            raise RecipeError(f"step {i} ({op}): missing {', '.join(missing) or 'selector or ms'}")
        for value in (step.get("url"), step.get("value")):
            for name in re.findall(r"\{(\w+)\}", str(value or "")):
                if name not in params:
                    raise RecipeError(f"step {i}: parameter {{{name}}} not declared")
    extract = recipe.get("extract")
    if not isinstance(extract, dict) or not extract:
        raise RecipeError("extract: at least one field")
    for field, spec in extract.items():
        if not isinstance(spec, dict) or not spec.get("selector"):
            raise RecipeError(f"extract.{field}: selector required")
    return recipe


def load_all(directory: Path = RECIPES_DIR) -> dict[str, dict]:
    """Every valid recipe of the folder; a broken file is skipped with a warning (the others still work)."""
    out: dict[str, dict] = {}
    for path in sorted(Path(directory).glob("*.json")):
        try:
            recipe = validate(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            logger.warning("event=atlas_recipe_invalid file=%s error=%s", path.name, exc)
            continue
        out[recipe["name"]] = recipe
    return out


def describe(recipe: dict) -> dict:
    return {"name": recipe["name"], "title": recipe.get("title") or recipe["name"],
            "description": recipe.get("description") or "", "site": recipe.get("site") or "",
            "params": recipe.get("params") or {}, "fields": sorted(recipe["extract"])}


def bind(recipe: dict, params: dict[str, Any]) -> dict[str, str]:
    """Check required parameters and return the values as strings (defaults applied)."""
    declared = recipe.get("params") or {}
    values: dict[str, str] = {}
    for name, spec in declared.items():
        spec = spec if isinstance(spec, dict) else {}
        value = params.get(name, spec.get("default"))
        if value in (None, "") and spec.get("required"):
            raise RecipeError(f"parameter {name} required")
        values[name] = "" if value is None else str(value)
    return values


def _fill(template: str, values: dict[str, str], *, url: bool) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: quote(values.get(m.group(1), ""), safe="") if url
                  else values.get(m.group(1), ""), template)


async def execute(page: Any, recipe: dict, values: dict[str, str], timeout_ms: int = 20000) -> dict:
    """Run the steps on a Playwright page. Returns ``{status: ok|broken, fields, step?, error?}``."""
    for i, step in enumerate(recipe["steps"]):
        op = step["op"]
        try:
            if op == "goto":
                await page.goto(_fill(step["url"], values, url=True), wait_until=step.get("until") or "domcontentloaded",
                                timeout=timeout_ms)
            elif op == "fill":
                await page.fill(step["selector"], _fill(step["value"], values, url=False), timeout=timeout_ms)
            elif op == "click":
                await page.click(step["selector"], timeout=timeout_ms)
            elif op == "press":
                await page.press(step["selector"], step["key"], timeout=timeout_ms)
            elif op == "wait":
                if step.get("selector"):
                    await page.wait_for_selector(step["selector"], timeout=int(step.get("ms") or timeout_ms))
                else:
                    await page.wait_for_timeout(int(step["ms"]))
        except Exception as exc:  # noqa: BLE001 — the site changed or is slow: the recipe is broken
            return {"status": "broken", "step": i, "op": op, "error": str(exc)[:300], "fields": {}}
    fields: dict[str, Any] = {}
    empty_required: list[str] = []
    for field, spec in recipe["extract"].items():
        try:
            nodes = await page.query_selector_all(spec["selector"])
            values_out = []
            for node in nodes[: int(spec.get("limit") or (50 if spec.get("all") else 1))]:
                raw = await (node.get_attribute(spec["attr"]) if spec.get("attr") else node.inner_text())
                if raw is not None and str(raw).strip():
                    values_out.append(re.sub(r"\s+", " ", str(raw)).strip()[:_MAX_TEXT])
        except Exception as exc:  # noqa: BLE001
            return {"status": "broken", "step": "extract", "field": field, "error": str(exc)[:300], "fields": fields}
        fields[field] = values_out if spec.get("all") else (values_out[0] if values_out else None)
        if spec.get("required") and not values_out:
            empty_required.append(field)
    if empty_required:
        return {"status": "broken", "step": "extract", "field": ",".join(empty_required),
                "error": "campi obbligatori vuoti", "fields": fields}
    return {"status": "ok", "fields": fields, "url": getattr(page, "url", None)}


def run(name: str, params: dict[str, Any], runner: Callable[..., Any], *, recipes: dict[str, dict] | None = None,
        timeout_seconds: int = 30) -> tuple[int, dict]:
    """Load, bind, run in Edge (``runner`` = ``fetcher.run_in_edge``). HTTP-like ``(status, body)``."""
    recipes = load_all() if recipes is None else recipes
    recipe = recipes.get(name)
    if recipe is None:
        return 404, {"status": "not_found", "available": sorted(recipes)}
    try:
        values = bind(recipe, params or {})
    except RecipeError as exc:
        return 400, {"status": "error", "error": str(exc)}
    result = runner(lambda page: execute(page, recipe, values, timeout_seconds * 1000), timeout_seconds)
    if result is None:
        logger.warning("[🔄] event=atlas_recipe_browser_unavailable recipe=%s fallback=none", name)
        return 503, {"status": "error", "error": "browser non disponibile"}
    if result["status"] == "broken":
        logger.warning("event=atlas_recipe_broken recipe=%s step=%s field=%s error=%s", name, result.get("step"),
                       result.get("field", "-"), result.get("error"))
        return 200, {**result, "recipe": name, "message": "La ricetta non funziona più: il sito è cambiato."}
    logger.info("event=atlas_recipe_ok recipe=%s fields=%d", name, len(result["fields"]))
    return 200, {**result, "recipe": name}
