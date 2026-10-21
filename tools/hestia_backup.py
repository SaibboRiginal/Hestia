"""Backup of Hestia from a terminal (host side). Runs the Archive container's backup CLI with ``docker exec``.

  python tools/hestia_backup.py list                     # backups on Google Drive
  python tools/hestia_backup.py status
  python tools/hestia_backup.py restore <name>           # roll back to a backup on Drive (asks RIPRISTINA)
  python tools/hestia_backup.py restore --file <path>    # a .enc file downloaded by hand (copied in first)
  python tools/hestia_backup.py undo                     # back to the data just before the last restore
  python tools/hestia_backup.py decrypt <path>           # .enc → .dump next to it (needs the passphrase in .env)

The panel in the WebUI (Impostazioni → Sistema → Archivio → Backup) does the same. SPEC:
docs/work/2026-10-20-backup-drive/SPEC.md §3.4.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

CONTAINER = "hestia_archive"
IMPORT_DIR = "/code/backups/import"


def _docker(*args: str, interactive: bool = False) -> int:
    cmd = ["docker", *args]
    if interactive:
        cmd = ["docker", args[0], "-it", *args[1:]] if sys.stdin.isatty() else cmd
    return subprocess.call(cmd)


def _copy_in(path: str) -> str:
    src = Path(path)
    if not src.is_file():
        sys.exit(f"{src} non esiste.")
    _docker("exec", CONTAINER, "mkdir", "-p", IMPORT_DIR)
    if _docker("cp", str(src), f"{CONTAINER}:{IMPORT_DIR}/{src.name}") != 0:
        sys.exit("Copia nel container non riuscita: Hestia è avviata?")
    return src.name


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    args = list(argv)
    if args[0] == "restore" and "--file" in args:
        i = args.index("--file")
        if i + 1 >= len(args):
            sys.exit("restore --file: manca il percorso")
        args[i:i + 2] = ["--local", _copy_in(args[i + 1])]
    if args[0] == "decrypt" and len(args) > 1:
        src = Path(args[1])
        name = _copy_in(args[1])
        rc = _docker("exec", CONTAINER, "python", "-m", "app.backup.cli", "decrypt", name)
        if rc == 0:
            out = src.with_name(src.name + ".dump")
            rc = _docker("cp", f"{CONTAINER}:{IMPORT_DIR}/{name}.dump", str(out))
            _docker("exec", CONTAINER, "rm", "-f", f"{IMPORT_DIR}/{name}.dump")
            if rc == 0:
                print(f"Scritto {out}")
        return rc
    return _docker("exec", CONTAINER, "python", "-m", "app.backup.cli", *args, interactive=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
