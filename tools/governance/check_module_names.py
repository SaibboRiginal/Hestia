"""No module names in the texts people read (docs/work/2026-11-27-webui-rethink, piece 2; Marko's rule: user texts
never name modules — «Not available», never «Athena not reachable»).

Scans the people texts of the web clients — the literals passed to ``tr(...)`` in the WebUI and in every module
plugin — for a module's own name (Athena, Hermes, Oracle…). People read the module's people name instead
(``hestia_common.areas.MODULE_LABELS``: «Thoughts», «Notifications», «Assistant»…). Comments and ids are not checked.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLIENT_DIRS = [ROOT / "Hestia-WebUI/frontend/src", ROOT / "Hestia-Shared/webui-sdk/src",
               *sorted(ROOT.glob("Hestia-*/ui/src"))]
# Module names that are not also everyday words (Archive, Echo, Atlas, Hub are words: left out).
NAMES = ["Aphrodite", "Apollo", "Argus", "Athena", "Calliope", "Chronos", "Demeter", "Hecate", "Hephaestus", "Hera",
         "Hercules", "Hermes", "Hygieia", "Iris", "Kairos", "Lares", "Metis", "Oracle", "Plutus", "Psyche", "Scout",
         "Themis"]
WORD = re.compile(r"\b(" + "|".join(NAMES) + r")\b")
TR = re.compile(r"""\btr\(\s*(?:"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)'|`((?:[^`\\]|\\.)*)`)""")


def main() -> int:
    bad: list[str] = []
    for base in CLIENT_DIRS:
        for path in sorted(base.rglob("*.ts")):
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if line.lstrip().startswith(("//", "*", "/*")):
                    continue
                for m in TR.finditer(line):
                    text = next(g for g in m.groups() if g is not None)
                    hit = WORD.search(text)
                    if hit:
                        bad.append(f"{path.relative_to(ROOT)}:{n}: «{text[:80]}» names {hit.group(1)}")
    if bad:
        print("check_module_names: FAILED — people read the module's people name (MODULE_LABELS), never its own name")
        print("\n".join(f"- {b}" for b in bad))
        return 1
    print("check_module_names: no module name in the people texts of the web clients")
    return 0


if __name__ == "__main__":
    sys.exit(main())
