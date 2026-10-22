"""Export and import per module — one contract for every module (dossier ``docs/work/2026-10-20-import-export``).

A module lists *sections* of its own data; a client (WebUI page «Esporta e importa», ``tools/hestia_transfer.py``)
picks modules → sections → single items, writes one ``.hestia`` file and imports it elsewhere with a mode:

- ``append``  (Aggiungi)   new records only; existing ones stay as they are;
- ``merge``   (Unisci)     new records + existing ones only when the file's copy is newer (``updated_at``);
- ``replace`` (Sostituisci) the file wins; records only in the target are deleted (only for a section exported
  whole: a partial section — chosen items or «solo modifiche dal» — never deletes).

Every import can run as a dry run (preview: same report, nothing written).

    from hestia_common.transfer import Transfer, StoreSection

    transfer = Transfer("hercules", hub, sections=[
        StoreSection("esercizi", "Esercizi", store, ["exercise"], icon="dumbbell"),
        StoreSection("sessioni", "Sessioni", store, ["session", "set"], item_kinds=["session"],
                     depends_on=["esercizi", "schede"]),
    ])
    app.include_router(transfer.router())                 # /api/transfer/*
    caps.update(transfer.capabilities())                  # Hub registration

Rules
- A module exports only its own data; settings travel through Themis (it owns the values).
- Never secrets, tokens, keys, logs or runtime state: a section lists only what the user made.
- Files (photos) are Archive blobs of the module: exported only on request (``include_files``) and uploaded
  one by one on import (``POST /api/transfer/files``); references are rewritten with the new blob ids.
- Dependencies: a section names the sections it refers to (``depends_on``); exporting chosen items pulls in the
  records they mention (an id found anywhere in the record), so the target never gets a dangling reference.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

logger = logging.getLogger("hestia_common.transfer")

FORMAT = 1
MODES = ("append", "merge", "replace")
REPORT_ITEMS = 200            # item titles listed per outcome in a report


class TransferError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _strings(value: Any, out: set[str]) -> set[str]:
    """Every string found in a record (ids are looked up among them)."""
    if isinstance(value, str):
        if value:
            out.add(value)
    elif isinstance(value, dict):
        for v in value.values():
            _strings(v, out)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _strings(v, out)
    return out


def _remap(value: Any, mapping: dict[str, str]) -> Any:
    if isinstance(value, str):
        return mapping.get(value, value)
    if isinstance(value, dict):
        return {k: _remap(v, mapping) for k, v in value.items()}
    if isinstance(value, list):
        return [_remap(v, mapping) for v in value]
    return value


# ── sections ────────────────────────────────────────────────────────────────

class Section:
    """One block of a module's data. Records are dicts ``{key, updated_at, deleted?, …}``; ``key`` is unique in the
    section and is what an import matches on. Subclasses implement ``records``, ``write`` and the titles."""

    schema = 1

    def __init__(self, id: str, label: str, *, icon: str = "", depends_on: Iterable[str] = (),
                 has_files: bool = False, help: str = "", schema: int | None = None, deletes: bool = True):
        self.id, self.label, self.icon, self.help = id, label, icon, help
        self.depends_on = list(depends_on)
        self.has_files = has_files
        self.deletes = deletes          # False: replace never removes target records (e.g. shared entities)
        if schema is not None:
            self.schema = schema

    # what the module implements
    def records(self, *, deleted: bool = False) -> list[dict]:
        raise NotImplementedError

    def write(self, records: list[dict], deletes: list[dict], *, mode: str) -> None:
        """Write ``records`` (new or updated; for ``replace`` they must win) and remove ``deletes``."""
        raise NotImplementedError

    def title(self, rec: dict) -> str:
        return str(rec.get("key"))

    def subtitle(self, rec: dict) -> str:
        return ""

    def is_item(self, rec: dict) -> bool:
        """Records shown in the item picker (others travel with their item, e.g. a session's sets)."""
        return True

    def children(self, rec: dict, chosen: set[str]) -> bool:
        """True when ``rec`` belongs to an item in ``chosen`` (keys) and must travel with it."""
        return False

    def ref(self, rec: dict) -> str:
        """The id other records use to point at this one."""
        return str(rec.get("key"))

    def refs(self, rec: dict) -> set[str]:
        """Strings in ``rec`` that may be ids of other records (default: every string)."""
        return _strings({k: v for k, v in rec.items() if k not in ("key", "updated_at", "deleted")}, set())

    def files(self, rec: dict) -> list[str]:
        """Blob ids this record needs (only for ``has_files`` sections)."""
        return []

    def migrate(self, records: list[dict], from_schema: int) -> list[dict]:
        return records

    def check(self, rec: dict) -> str | None:
        """A reason this record cannot be imported here (reported as a problem, record skipped)."""
        return None

    def same(self, a: dict, b: dict) -> bool:
        strip = ("updated_at",)
        return {k: v for k, v in a.items() if k not in strip} == {k: v for k, v in b.items() if k not in strip}

    # generic parts
    def describe(self) -> dict:
        live = [r for r in self.records() if self.is_item(r)]
        return {"id": self.id, "label": self.label, "icon": self.icon, "help": self.help, "count": len(live),
                "depends_on": self.depends_on, "has_files": self.has_files, "schema": self.schema}

    def items(self, q: str = "", limit: int = 200, offset: int = 0) -> dict:
        q = (q or "").strip().lower()
        rows = [r for r in self.records() if self.is_item(r)]
        rows.sort(key=lambda r: str(r.get("updated_at") or ""), reverse=True)
        out = []
        for r in rows:
            title, sub = self.title(r), self.subtitle(r)
            if q and q not in f"{title} {sub}".lower():
                continue
            out.append({"key": r["key"], "title": title, "subtitle": sub, "updated_at": r.get("updated_at")})
        return {"items": out[offset:offset + max(1, min(int(limit), 2000))], "total": len(out)}


class StoreSection(Section):
    """Rows of a module store (``hercules-store`` and the like: ``{kind, id, parent_id, ref_id, at, data,
    updated_at, deleted}``) grouped by ``kinds``. ``store`` has ``refresh``, ``all(kind, deleted=)`` and ``write``."""

    def __init__(self, id: str, label: str, store, kinds: Iterable[str], *, item_kinds: Iterable[str] | None = None,
                 title: Callable[[dict], str] | None = None, subtitle: Callable[[dict], str] | None = None,
                 file_fields: Iterable[str] = (), **kw):
        super().__init__(id, label, has_files=bool(file_fields) or kw.pop("has_files", False), **kw)
        self.store = store
        self.kinds = list(kinds)
        self.item_kinds = list(item_kinds or kinds)
        self._title, self._subtitle = title, subtitle
        self.file_fields = list(file_fields)

    def records(self, *, deleted: bool = False) -> list[dict]:
        self.store.refresh()
        out = []
        for kind in self.kinds:
            for r in self.store.all(kind, deleted=deleted):
                out.append({"key": f"{kind}:{r['id']}", "kind": kind, "id": r["id"], "parent_id": r.get("parent_id"),
                            "ref_id": r.get("ref_id"), "at": r.get("at"), "data": r.get("data") or {},
                            "updated_at": r.get("updated_at"), "deleted": bool(r.get("deleted"))})
        return out

    def ref(self, rec: dict) -> str:
        return str(rec.get("id"))

    def refs(self, rec: dict) -> set[str]:
        return _strings([rec.get("parent_id"), rec.get("ref_id"), rec.get("data")], set())

    def is_item(self, rec: dict) -> bool:
        return rec.get("kind") in self.item_kinds

    def children(self, rec: dict, chosen: set[str]) -> bool:
        ids = {k.split(":", 1)[1] for k in chosen if ":" in k}
        return rec.get("kind") not in self.item_kinds and (rec.get("parent_id") in ids or rec.get("ref_id") in ids)

    def title(self, rec: dict) -> str:
        if self._title:
            try:
                return str(self._title(rec) or rec["id"])
            except Exception:
                pass
        d = rec.get("data") or {}
        return str(d.get("name") or d.get("title") or d.get("label") or d.get("description") or rec["id"])

    def subtitle(self, rec: dict) -> str:
        if self._subtitle:
            try:
                return str(self._subtitle(rec) or "")
            except Exception:
                return ""
        return str(rec.get("at") or "")[:10]

    def files(self, rec: dict) -> list[str]:
        d = rec.get("data") or {}
        out: list[str] = []
        for f in self.file_fields:
            v = d.get(f)
            out += [x for x in (v if isinstance(v, list) else [v]) if isinstance(x, str) and x]
        return out

    def same(self, a: dict, b: dict) -> bool:
        keys = ("parent_id", "ref_id", "data", "deleted")
        return all(a.get(k) == b.get(k) for k in keys) and str(a.get("at") or "")[:19] == str(b.get("at") or "")[:19]

    def write(self, records: list[dict], deletes: list[dict], *, mode: str) -> None:
        stamp = now_iso()
        rows = []
        for r in records:
            row = {k: r.get(k) for k in ("kind", "id", "parent_id", "ref_id", "at", "data")}
            row["deleted"] = bool(r.get("deleted"))
            # replace must win over a newer target copy (Archive is last-write-wins)
            row["updated_at"] = stamp if mode == "replace" else (r.get("updated_at") or stamp)
            rows.append(row)
        for r in deletes:
            rows.append({**{k: r.get(k) for k in ("kind", "id", "parent_id", "ref_id", "at", "data")},
                         "deleted": True, "updated_at": stamp})
        if rows:
            self.store.write(rows)


# ── module side ─────────────────────────────────────────────────────────────

class Transfer:
    """The module's ``/api/transfer/*`` endpoints over its sections. ``hub`` has ``ok(service, method, path,
    body=, query=, timeout=)`` (only needed for files: the module's own Archive blobs)."""

    def __init__(self, module: str, hub=None, *, sections: Iterable[Section] | Callable[[], Iterable[Section]]):
        self.module = module
        self.hub = hub
        self._sections = sections if callable(sections) else list(sections)

    @property
    def sections(self) -> dict[str, Section]:
        """Fixed list, or built on each call (Themis: one section per module with settings)."""
        src = self._sections() if callable(self._sections) else self._sections
        return {s.id: s for s in src}

    def section(self, sid: str) -> Section:
        s = self.sections.get(sid)
        if not s:
            raise TransferError(f"sezione {sid} sconosciuta", 404)
        return s

    def capabilities(self) -> dict:
        return {"transfer": {"endpoint": "/api/transfer", "format": FORMAT,
                             "sections": {s.id: s.schema for s in self.sections.values()}}}

    # ── describe / items ────────────────────────────────────────────────────
    def describe(self) -> dict:
        out = []
        for s in self.sections.values():
            try:
                out.append(s.describe())
            except Exception as exc:
                logger.warning("[🔄] event=transfer_describe_failed module=%s section=%s error=%s",
                               self.module, s.id, exc)
                out.append({"id": s.id, "label": s.label, "icon": s.icon, "count": None, "error": str(exc),
                            "depends_on": s.depends_on, "has_files": s.has_files, "schema": s.schema})
        return {"module": self.module, "format": FORMAT, "sections": out}

    # ── export ──────────────────────────────────────────────────────────────
    def export(self, selection: dict | None = None, *, since: str | None = None,
               include_files: bool = False) -> dict:
        """``selection`` = ``{section: {"keys": [..]} | {} }`` (empty or missing = every section, whole)."""
        selection = selection if isinstance(selection, dict) and selection else {s: {} for s in self.sections}
        since_dt = parse_dt(since)
        picked: dict[str, dict[str, dict]] = {}
        partial: dict[str, bool] = {}
        pulled: dict[str, list[str]] = {}
        cache: dict[str, list[dict]] = {}

        def all_of(sid: str) -> list[dict]:
            if sid not in cache:
                cache[sid] = self.section(sid).records(deleted=since_dt is not None)
            return cache[sid]

        for sid, choice in selection.items():
            s = self.section(sid)
            if s.has_files and not include_files and not (choice or {}).get("keys"):
                continue
            keys = set((choice or {}).get("keys") or [])
            rows = all_of(sid)
            if keys:
                rows = [r for r in rows if r["key"] in keys or s.children(r, keys)]
            if since_dt:
                rows = [r for r in rows if (parse_dt(r.get("updated_at")) or since_dt) >= since_dt]
            else:
                rows = [r for r in rows if not r.get("deleted")]
            picked[sid] = {r["key"]: r for r in rows}
            partial[sid] = bool(keys) or since_dt is not None

        # dependencies: records named by what was picked (transitively, inside depends_on)
        changed = True
        while changed:
            changed = False
            for sid in list(picked):
                s = self.section(sid)
                wanted: set[str] = set()
                for r in picked[sid].values():
                    wanted |= s.refs(r)
                for dep in s.depends_on:
                    if dep not in self.sections:
                        continue
                    ds = self.section(dep)
                    if ds.has_files and not include_files:
                        continue
                    have = picked.setdefault(dep, {})
                    if dep not in partial:
                        partial[dep] = True
                    for r in all_of(dep):
                        if r.get("deleted") or r["key"] in have or ds.ref(r) not in wanted:
                            continue
                        have[r["key"]] = r
                        pulled.setdefault(dep, []).append(r["key"])
                        changed = True
                        for c in all_of(dep):           # e.g. a session pulls its sets
                            if c["key"] not in have and not c.get("deleted") and ds.children(c, {r["key"]}):
                                have[c["key"]] = c
        files: list[str] = []
        sections = {}
        for sid, rows in picked.items():
            s = self.section(sid)
            if s.has_files:            # only picked with include_files or chosen by hand
                for r in rows.values():
                    files += [f for f in s.files(r) if f not in files]
            sections[sid] = {"schema": s.schema, "label": s.label, "partial": partial.get(sid, False),
                             "records": list(rows.values())}
        logger.info("event=transfer_export module=%s sections=%s records=%d files=%d since=%s", self.module,
                    ",".join(sections), sum(len(v["records"]) for v in sections.values()), len(files), since or "-")
        return {"module": self.module, "format": FORMAT, "exported_at": now_iso(), "since": since,
                "sections": sections, "pulled": pulled, "files": files}

    # ── files (the module's own Archive blobs) ─────────────────────────────
    def file_get(self, blob_id: str) -> dict:
        meta = self.hub.ok("archive", "GET", f"api/blobs/{blob_id}/meta", timeout=10) or {}
        if str(meta.get("owner_module") or "") != self.module:
            raise TransferError("file non di questo modulo", 404)
        data = self.hub.ok("archive", "GET", f"api/blobs/{blob_id}/base64", timeout=60) or {}
        return {"id": blob_id, "mime": data.get("mime") or meta.get("content_type"), "sha256": meta.get("sha256"),
                "meta": meta.get("meta") or {}, "data_b64": data.get("data_b64")}

    def file_put(self, body: dict) -> dict:
        old = str(body.get("id") or "")
        if not old or not body.get("data_b64"):
            raise TransferError("id e data_b64 obbligatori")
        r = self.hub.ok("archive", "POST", "api/blobs", body={
            "owner_module": self.module, "content_type": body.get("mime") or "application/octet-stream",
            "data_base64": body["data_b64"], "meta": body.get("meta") or {}}, timeout=60) or {}
        return {"old_id": old, "new_id": r.get("blob_id") or old}

    # ── import ──────────────────────────────────────────────────────────────
    def import_(self, payload: dict, *, mode: str = "merge", modes: dict | None = None, dry_run: bool = True,
                selection: dict | None = None, files_map: dict | None = None) -> dict:
        """``payload`` = the module block of the file (``export`` output). ``modes`` per section override
        ``mode``; ``selection`` narrows to sections/keys like export."""
        if mode not in MODES:
            raise TransferError(f"modo {mode}: ammessi {', '.join(MODES)}")
        sections_in = (payload or {}).get("sections") or {}
        if int((payload or {}).get("format") or FORMAT) > FORMAT:
            raise TransferError("file di una versione di Hestia più recente: aggiorna Hestia", 422)
        files_map = {str(k): str(v) for k, v in (files_map or {}).items() if k and v}
        report: dict[str, Any] = {"module": self.module, "dry_run": dry_run, "sections": {}}
        for sid, block in sections_in.items():
            sel = (selection or {}).get(sid) if selection else {}
            if selection and sid not in selection:
                continue
            smode = (modes or {}).get(sid) or mode
            if smode not in MODES:
                raise TransferError(f"modo {smode}: ammessi {', '.join(MODES)}")
            report["sections"][sid] = self._import_section(sid, block or {}, smode, dry_run, sel or {}, files_map)
        totals = {k: sum(int(s.get(k) or 0) for s in report["sections"].values())
                  for k in ("added", "updated", "unchanged", "skipped", "deleted", "problems")}
        report["totals"] = totals
        logger.info("event=transfer_import module=%s dry_run=%s mode=%s added=%d updated=%d skipped=%d deleted=%d "
                    "problems=%d", self.module, dry_run, mode, totals["added"], totals["updated"], totals["skipped"],
                    totals["deleted"], totals["problems"])
        return report

    def _import_section(self, sid: str, block: dict, mode: str, dry_run: bool, sel: dict,
                        files_map: dict[str, str]) -> dict:
        out: dict[str, Any] = {"mode": mode, "added": 0, "updated": 0, "unchanged": 0, "skipped": 0, "deleted": 0,
                               "problems": 0, "related": 0, "items": {"added": [], "updated": [], "skipped": [], "deleted": [],
                                                        "problems": []}}

        def note(kind: str, text: str) -> None:
            out[kind] += 1
            if len(out["items"][kind]) < REPORT_ITEMS:
                out["items"][kind].append(text)

        def tally(kind: str, item: bool, text: str) -> None:
            if item:                    # records travelling with an item (a session's sets) are not counted
                note(kind, text)
            else:
                out["related"] += 1

        s = self.sections.get(sid)
        if not s:
            note("problems", f"sezione «{sid}» non presente qui")
            return out
        schema = int(block.get("schema") or 1)
        if schema > s.schema:
            note("problems", "sezione di una versione di Hestia più recente: aggiorna Hestia")
            return out
        incoming = [r for r in (block.get("records") or []) if isinstance(r, dict) and r.get("key")]
        if schema < s.schema:
            incoming = s.migrate(incoming, schema)
        keys = set(sel.get("keys") or [])
        if keys:
            incoming = [r for r in incoming if r["key"] in keys or s.children(r, keys)]
        if files_map:
            incoming = [_remap(r, files_map) for r in incoming]
        current = {r["key"]: r for r in s.records(deleted=True)}
        writes, deletes = [], []
        for r in incoming:
            have = current.get(r["key"])
            label = s.title(r)
            item = s.is_item(r)
            problem = s.check(r)
            if problem:
                note("problems", f"{label}: {problem}")
                continue
            if have is None:
                if r.get("deleted"):            # a deletion of something the target never had
                    out["unchanged"] += int(item)
                    continue
                writes.append(r)
                tally("added", item, label)
                continue
            if s.same(have, r):
                out["unchanged"] += int(item)
                continue
            if mode == "append":
                tally("skipped", item, f"{label} ({'eliminato qui' if have.get('deleted') else 'già presente'})")
                continue
            if mode == "merge":
                a, b = parse_dt(r.get("updated_at")), parse_dt(have.get("updated_at"))
                if a and b and a <= b:
                    tally("skipped", item, f"{label} (qui è più recente)")
                    continue
            writes.append(r)
            if r.get("deleted"):
                tally("deleted", item, label)
            else:
                tally("added" if have.get("deleted") else "updated", item, label)
        partial = bool(block.get("partial")) or bool(keys)
        if mode == "replace" and not partial and s.deletes:
            present = {r["key"] for r in incoming}
            for key, have in current.items():
                if key in present or have.get("deleted"):
                    continue
                deletes.append(have)
                tally("deleted", s.is_item(have), s.title(have))
        out["partial"] = partial
        if not dry_run and (writes or deletes):
            try:
                s.write(writes, deletes, mode=mode)
            except TransferError:
                raise
            except Exception as exc:
                logger.warning("[🔄] event=transfer_import_write_failed module=%s section=%s error=%s",
                               self.module, sid, exc)
                raise TransferError(f"{s.label}: scrittura non riuscita ({exc})", 503)
        return out

    # ── HTTP ────────────────────────────────────────────────────────────────
    def router(self):
        from fastapi import APIRouter, HTTPException

        router = APIRouter(prefix="/api/transfer", tags=["transfer"])

        def guard(fn, *a, **kw):
            try:
                return fn(*a, **kw)
            except TransferError as exc:
                raise HTTPException(status_code=exc.status, detail=str(exc))

        @router.get("/describe")
        def transfer_describe():
            return self.describe()

        @router.post("/items")
        def transfer_items(body: dict):
            body = body or {}
            return guard(lambda: self.section(str(body.get("section") or "")).items(
                str(body.get("q") or ""), int(body.get("limit") or 200), int(body.get("offset") or 0)))

        @router.post("/export")
        def transfer_export(body: dict | None = None):
            body = body or {}
            return guard(self.export, body.get("sections"), since=body.get("since"),
                         include_files=bool(body.get("include_files")))

        @router.get("/files/{blob_id}")
        def transfer_file(blob_id: str):
            return guard(self.file_get, blob_id)

        @router.post("/files")
        def transfer_file_upload(body: dict):
            return guard(self.file_put, body or {})

        @router.post("/import")
        def transfer_import(body: dict):
            body = body or {}
            return guard(self.import_, body.get("data") or {}, mode=str(body.get("mode") or "merge"),
                         modes=body.get("modes"), dry_run=bool(body.get("dry_run", True)),
                         selection=body.get("sections"), files_map=body.get("files_map"))

        return router
