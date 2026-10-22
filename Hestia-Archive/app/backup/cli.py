"""Backup from a terminal, inside the Archive container (SPEC docs/work/2026-10-20-backup-drive §3.4).

For a PC without the WebUI yet, or a backup file downloaded from Drive by hand. Host side:
``python tools/hestia_backup.py …`` (it runs this with ``docker exec``). It talks to this same Archive through its
own API, so a rollback still goes through the maintenance gate and the data epoch, exactly like the panel.

    python -m app.backup.cli list
    python -m app.backup.cli status
    python -m app.backup.cli restore <name>          # a backup on Drive (name from «list»)
    python -m app.backup.cli restore --local <name>  # a file in /code/backups/import/
    python -m app.backup.cli undo
    python -m app.backup.cli decrypt <name>          # import/<name> → import/<name>.dump (pg_restore format)
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import requests

API = os.getenv("ARCHIVE_LOCAL_API", "http://localhost:19002/api/backup")
CONFIRM_WORD = "RIPRISTINA"


def _call(method: str, path: str, body: dict | None = None) -> dict:
    resp = requests.request(method, f"{API}{path}", json=body, timeout=60)
    data = resp.json() if resp.content else {}
    if resp.status_code >= 400:
        detail = data.get("detail") if isinstance(data, dict) else data
        msg = detail.get("message") if isinstance(detail, dict) else detail
        raise SystemExit(f"Errore {resp.status_code}: {msg}")
    return data


def _wait() -> dict:
    """Follow the background job until it ends, printing each step."""
    last = None
    while True:
        st = _call("GET", "/status")
        job = st.get("job")
        if not job:
            return st
        if job.get("step") != last:
            last = job.get("step")
            print(f"  … {job.get('kind')}: {last}")
        time.sleep(1.5)


def _confirm(what: str, assume_yes: bool) -> None:
    print(what)
    if assume_yes:
        return
    try:
        answer = input(f"Scrivi {CONFIRM_WORD} per continuare: ").strip()
    except EOFError:
        answer = ""
    if answer != CONFIRM_WORD:
        raise SystemExit("Annullato, nessun dato è cambiato.")


def cmd_list(_args) -> None:
    data = _call("GET", "/list")
    if data.get("error"):
        print(f"Google Drive: {data['error']}")
    for p in data.get("pending") or []:
        print(f"  {p['created_at']}  {p.get('size', 0):>12}  in attesa di Drive  {p.get('name', '')}")
    for it in data.get("items") or []:
        mark = {"ok": "verificato", "fail": "verifica fallita"}.get(it.get("verify") or "", "")
        print(f"  {it['name']}  {it.get('size', 0):>12}  {'mensile ' if it.get('monthly') else ''}{mark}")
    if not (data.get("items") or data.get("pending")):
        print("Nessun backup.")


def cmd_status(_args) -> None:
    st = _call("GET", "/status")
    for key in ("passphrase_set", "drive", "last_backup", "last_verify", "last_restore", "problem", "job",
                "undo_available"):
        print(f"{key}: {st.get(key)}")


def _report_restore(st: dict) -> None:
    r = st.get("last_restore") or {}
    if r.get("ok"):
        print(f"Fatto: dati ripristinati da {r.get('name')}. «undo» li riporta a prima.")
    else:
        raise SystemExit(f"Ripristino non riuscito: {r.get('error')}. I dati non sono cambiati.")


def cmd_restore(args) -> None:
    if args.local:
        name = Path(args.local).name
        body = {"local": name, "confirm": True}
        label = f"del file {name}"
    else:
        items = _call("GET", "/list").get("items") or []
        match = [it for it in items if it["name"] == args.name or it["id"] == args.name]
        if not match:
            raise SystemExit(f"Backup {args.name} non trovato su Google Drive (vedi «list»).")
        body = {"file_id": match[0]["id"], "confirm": True}
        label = f"di {match[0]['name']}"
    _confirm(f"Ripristino {label}: tutti i dati tornano a quel momento, quello cambiato dopo viene sostituito.",
             args.yes)
    _call("POST", "/restore", body)
    _report_restore(_wait())


def cmd_undo(args) -> None:
    before = (_call("GET", "/status").get("last_restore") or {}).get("undo_at")
    _confirm("Annullo l'ultimo ripristino: i dati tornano com'erano subito prima.", args.yes)
    _call("POST", "/undo", {"confirm": True})
    r = _wait().get("last_restore") or {}
    if r.get("undo_at") == before:
        raise SystemExit("Annullamento non riuscito: vedi i log (docker logs hestia_archive).")
    print("Fatto: dati di prima del ripristino." if r.get("undone") else "Fatto: di nuovo i dati del backup ripristinato.")


def cmd_decrypt(args) -> None:
    from .container import unseal
    from .. import maintenance

    src = Path(maintenance.BACKUP_DIR) / "import" / Path(args.name).name
    pw = os.getenv("HESTIA_BACKUP_PASSPHRASE", "")
    if not pw:
        raise SystemExit("Manca HESTIA_BACKUP_PASSPHRASE.")
    if not src.is_file():
        raise SystemExit(f"{src} non esiste.")
    out = src.with_name(src.name + ".dump")
    manifest = unseal(src, out, pw)
    print(f"{out} (pg_restore) — creato {manifest.get('created_at')}, {len(manifest.get('counts') or {})} tabelle")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="hestia_backup", description="Backup di Hestia su Google Drive")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").set_defaults(fn=cmd_list)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    r = sub.add_parser("restore")
    r.add_argument("name", nargs="?")
    r.add_argument("--local")
    r.add_argument("--yes", action="store_true")
    r.set_defaults(fn=cmd_restore)
    u = sub.add_parser("undo")
    u.add_argument("--yes", action="store_true")
    u.set_defaults(fn=cmd_undo)
    d = sub.add_parser("decrypt")
    d.add_argument("name")
    d.set_defaults(fn=cmd_decrypt)
    args = ap.parse_args(argv)
    if args.cmd == "restore" and not (args.name or args.local):
        ap.error("restore: indica il nome del backup oppure --local <file>")
    args.fn(args)


if __name__ == "__main__":
    main(sys.argv[1:])
