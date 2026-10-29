"""Repo docs aligned with the code (Cindy 29, dossier docs/work/2026-10-24-tutto-brainstorm-cindy W3).

Deterministic, no model: what the running modules declare (MCP tools with their REST paths from Hestia-MCP,
settings keys from Themis) is compared with the repo's docs read through Forge's repo browser
(``Hestia-<Name>/hestia-<name>.md`` and ``Hestia-Swagger/swagger.yml``). Missing names become ONE Forge proposal per
module («aggiorna la documentazione»): Forge's permission modes decide, the owner approves the diff. Monthly agenda job
``athena.docs_check`` (movable, pausable) and tool ``docs_check``.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable

logger = logging.getLogger("hestia_athena.docs_check")

Route = Callable[..., tuple[int, Any]]
_MAX_NAMES = 25


def _norm_path(path: str) -> str:
    return re.sub(r"\{[^}]+\}|\$\w+", "{}", str(path or "")).rstrip("/")


def module_folders(route: Route) -> dict[str, str]:
    """``chronos`` → ``Hestia-Chronos`` (from the repo root listing)."""
    status, payload = route("hephaestus", "GET", "api/hephaestus/repo/tree")
    entries = (payload or {}).get("entries") or [] if status == 200 else []
    return {e["name"][len("Hestia-"):].lower(): e["name"] for e in entries
            if isinstance(e, dict) and e.get("type") == "tree" and str(e.get("name", "")).startswith("Hestia-")}


def _file(route: Route, path: str) -> str | None:
    status, payload = route("hephaestus", "GET", "api/hephaestus/repo/file", query={"path": path})
    return str((payload or {}).get("content") or "") if status == 200 and isinstance(payload, dict) else None


def declared(route: Route, list_tools: Callable[[], list[dict]]) -> dict[str, dict]:
    """Per module: tool names, tool REST paths, settings keys."""
    out: dict[str, dict] = {}
    for tool in list_tools():
        meta = ((tool.get("_meta") or {}).get("hestia") or {})
        svc = str(meta.get("service") or "").lower()
        if not svc:
            continue
        entry = out.setdefault(svc, {"tools": set(), "paths": set(), "settings": set()})
        entry["tools"].add(tool["name"])
        if meta.get("path"):
            entry["paths"].add((str(meta.get("method") or "GET").upper(), _norm_path(meta["path"])))
    status, payload = route("themis", "GET", "api/settings", query={"status": "false"})
    for item in (payload or {}).get("items") or [] if status == 200 else []:
        key = str(item.get("key") or "") if isinstance(item, dict) else ""
        owner = key.split(".", 1)[0]
        if key and owner and owner != "themis":
            out.setdefault(owner, {"tools": set(), "paths": set(), "settings": set()})["settings"].add(key)
    return out


def swagger_paths(text: str) -> set[str]:
    return {_norm_path(m) for m in re.findall(r"^  (/[^\s:]+):\s*$", text or "", re.M)}


def findings(route: Route, list_tools: Callable[[], list[dict]]) -> list[dict]:
    folders = module_folders(route)
    if not folders:
        logger.warning("[🔄] event=docs_check_repo_unreachable fallback=skip")
        return []
    swagger = swagger_paths(_file(route, "Hestia-Swagger/swagger.yml") or "")
    out = []
    for svc, names in sorted(declared(route, list_tools).items()):
        folder = folders.get(svc)
        if not folder:
            continue
        doc_path = f"{folder}/hestia-{svc}.md"
        doc = _file(route, doc_path)
        if doc is None:
            out.append({"module": svc, "doc": doc_path, "missing_doc": True, "tools": [], "settings": [],
                        "swagger": []})
            continue
        tools = sorted(t for t in names["tools"] if t not in doc)
        settings = sorted(k for k in names["settings"] if k not in doc)
        missing_swagger = sorted(f"{m} {p}" for m, p in names["paths"] if swagger and p not in swagger)
        if tools or settings or missing_swagger:
            out.append({"module": svc, "doc": doc_path, "missing_doc": False, "tools": tools[:_MAX_NAMES],
                        "settings": settings[:_MAX_NAMES], "swagger": missing_swagger[:_MAX_NAMES]})
    return out


def request_text(f: dict) -> str:
    if f["missing_doc"]:
        return f"Scrivi la documentazione mancante {f['doc']} del modulo {f['module']} seguendo il codice."
    parts = []
    if f["tools"]:
        parts.append("tool non descritti: " + ", ".join(f["tools"]))
    if f["settings"]:
        parts.append("impostazioni non descritte: " + ", ".join(f["settings"]))
    if f["swagger"]:
        parts.append("endpoint mancanti in Hestia-Swagger/swagger.yml: " + ", ".join(f["swagger"]))
    return (f"Aggiorna la documentazione del modulo {f['module']} ({f['doc']}) perché segua il codice: "
            + "; ".join(parts) + ". Solo documenti, nessun cambio di comportamento.")
