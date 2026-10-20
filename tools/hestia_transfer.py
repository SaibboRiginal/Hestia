#!/usr/bin/env python3
"""Esporta e importa da terminale — the same `.hestia` file as the WebUI page (dossier docs/work/2026-10-20-import-export).

Talks only to Hub (``--hub``, default ``$HUB_API_URL`` or http://localhost:19001/api); every module exports/imports its own
data through ``/api/transfer/*``, Themis the settings.

    python tools/hestia_transfer.py modules
    python tools/hestia_transfer.py export -o casa.hestia                      # everything
    python tools/hestia_transfer.py export -o palestra.hestia hercules themis:hercules --since 2026-10-19 --files
    python tools/hestia_transfer.py preview casa.hestia --mode merge
    python tools/hestia_transfer.py import casa.hestia --mode merge            # asks before writing; saves a backup first

Selection: ``<module>`` (all its sections) or ``<module>:<section>[,<section>]``; settings are ``themis:<module>``.
The file holds personal data: keep it out of the repository (``*.hestia`` is git-ignored).
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib import request as urlrequest

FORMAT = 1


class Hub:
    def __init__(self, base: str):
        self.base = base.rstrip("/")

    def _post(self, url: str, body: dict, timeout: float) -> dict:
        req = urlrequest.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read() or b"{}")

    def call(self, service: str, method: str, path: str, body=None, timeout: float = 120):
        out = self._post(f"{self.base}/route/{service}/{path.lstrip('/')}",
                         {"method": method, "headers": {}, "query": {}, "body": body, "timeout_seconds": timeout},
                         timeout + 10)
        status, payload = int(out.get("status_code", 500)), out.get("payload")
        if status >= 400:
            detail = payload.get("detail") if isinstance(payload, dict) else payload
            raise SystemExit(f"{service}: {status} {detail}")
        return payload

    def modules(self) -> dict[str, dict]:
        with urlrequest.urlopen(f"{self.base}/registry/services", timeout=15) as resp:
            services = json.loads(resp.read()).get("services") or []
        return {s["name"]: s["capabilities"]["transfer"] for s in services
                if isinstance((s.get("capabilities") or {}).get("transfer"), dict)}


def read_file(path: str) -> dict:
    raw = Path(path).read_bytes()
    data = json.loads(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw)
    if data.get("hestia") != "transfer" or (data.get("format") or 1) > FORMAT:
        raise SystemExit("non è un file di Hestia, o è di una versione più recente")
    return data


def write_file(path: str, data: dict) -> None:
    Path(path).write_bytes(gzip.compress(json.dumps(data, ensure_ascii=False).encode()))


def selection(specs: list[str], available: dict) -> dict[str, dict]:
    """``["hercules", "themis:hercules,oracle"]`` → ``{owner: {section: {}}}`` ({} = every section)."""
    out: dict[str, dict] = {}
    for spec in specs or list(available):
        owner, _, sections = spec.partition(":")
        if owner not in available:
            raise SystemExit(f"{owner}: modulo senza esporta/importa (disponibili: {', '.join(sorted(available))})")
        out.setdefault(owner, {}).update({s: {} for s in sections.split(",") if s})
    return out


def build(hub: Hub, sel: dict, since: str | None, files: bool) -> dict:
    data = {"hestia": "transfer", "format": FORMAT, "exported_at": datetime.now(timezone.utc).isoformat(),
            "since": since, "include_files": files, "modules": {}, "files": {}}
    for owner, sections in sel.items():
        out = hub.call(owner, "POST", "api/transfer/export",
                       {"sections": sections or None, "since": since, "include_files": files})
        data["modules"][owner] = out
        for fid in out.get("files") or []:
            f = hub.call(owner, "GET", f"api/transfer/files/{fid}")
            data["files"].setdefault(owner, {})[fid] = {k: f.get(k) for k in ("mime", "sha256", "meta", "data_b64")}
        n = sum(len(b["records"]) for b in out["sections"].values())
        print(f"  {owner}: {n} record in {len(out['sections'])} sezioni, {len(out.get('files') or [])} file")
    return data


def run_import(hub: Hub, data: dict, mode: str, dry_run: bool, only: list[str]) -> dict:
    available = hub.modules()
    sel = selection(only, data["modules"]) if only else {o: {} for o in data["modules"]}
    reports = {}
    for owner, sections in sel.items():
        if owner not in available:
            print(f"  {owner}: non presente qui, saltato")
            continue
        files_map = {}
        if not dry_run:
            for fid, f in (data.get("files") or {}).get(owner, {}).items():
                r = hub.call(owner, "POST", "api/transfer/files", {"id": fid, **f})
                files_map[r["old_id"]] = r["new_id"]
        reports[owner] = rep = hub.call(owner, "POST", "api/transfer/import", {
            "data": data["modules"][owner], "mode": mode, "dry_run": dry_run, "sections": sections or None,
            "files_map": files_map})
        for sid, r in rep["sections"].items():
            parts = [f"{r[k]} {label}" for k, label in (("added", "nuovi"), ("updated", "aggiornati"),
                                                        ("skipped", "ignorati"), ("deleted", "eliminati"),
                                                        ("problems", "problemi")) if r.get(k)]
            print(f"  {owner}/{sid}: {', '.join(parts) or 'nessuna modifica'}")
            for p in r["items"]["problems"][:10]:
                print(f"      ! {p}")
    return reports


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hub", default=os.getenv("HUB_API_URL", "http://localhost:19001/api"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("modules")
    ex = sub.add_parser("export")
    ex.add_argument("select", nargs="*")
    ex.add_argument("-o", "--output", default=f"hestia-{datetime.now():%Y-%m-%d}.hestia")
    ex.add_argument("--since", help="solo modifiche da questa data (AAAA-MM-GG)")
    ex.add_argument("--files", action="store_true", help="includi le foto")
    for name in ("preview", "import"):
        p = sub.add_parser(name)
        p.add_argument("file")
        p.add_argument("select", nargs="*")
        p.add_argument("--mode", choices=("append", "merge", "replace"), default="merge")
        if name == "import":
            p.add_argument("--yes", action="store_true", help="non chiedere conferma")
    args = ap.parse_args()
    hub = Hub(args.hub)

    if args.cmd == "modules":
        for name, cap in sorted(hub.modules().items()):
            d = hub.call(name, "GET", "api/transfer/describe")
            print(f"{name}: " + ", ".join(f"{s['id']} ({s['count']})" for s in d["sections"] if s.get("count")))
        return
    if args.cmd == "export":
        since = f"{args.since}T00:00:00+00:00" if args.since and "T" not in args.since else args.since
        data = build(hub, selection(args.select, hub.modules()), since, args.files)
        write_file(args.output, data)
        print(f"scritto {args.output}")
        return
    data = read_file(args.file)
    print("anteprima:")
    run_import(hub, data, args.mode, True, args.select)
    if args.cmd == "preview":
        return
    if not args.yes and input(f"importare con modo {args.mode}? [s/N] ").strip().lower() not in ("s", "si", "sì", "y"):
        return
    backup = f"prima-di-importare-{datetime.now():%Y%m%d-%H%M%S}.hestia"
    owners = [o for o in data["modules"] if o in hub.modules()]
    sel = {o: {s: {} for s in data["modules"][o]["sections"]} for o in owners}
    write_file(backup, build(hub, sel, None, False))
    print(f"punto di ripristino: {backup}")
    run_import(hub, data, args.mode, False, args.select)
    print("fatto")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
