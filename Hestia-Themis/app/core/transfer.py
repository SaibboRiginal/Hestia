"""Settings in export / import (hestia_common.transfer, dossier 2026-10-20-import-export).

Themis owns the values, so it exports every module's settings: one section per module (id = module name), each
value a record ``{key: "<setting>|<scope>|<scope_id>", setting, scope, scope_id, value}``. System, profile and
client layers travel; session copies never do. A value is validated against this Hestia's schema on import
(unknown setting or bad value → reported, skipped) and written with history actor ``import``.
"""
from __future__ import annotations

from typing import Any

from hestia_common.transfer import Section
from .service import SELF_OWNER, Themis, ThemisError
from .validation import SettingValueError, validate

SCOPES = ("system", "profile", "client")
ACTOR = "import"


def _short(value: Any) -> str:
    text = value if isinstance(value, str) else repr(value)
    return text if len(text) <= 60 else text[:57] + "…"


class SettingsSection(Section):
    def __init__(self, themis: Themis, module: str):
        label = "Impostazioni personali" if module == "themis" else "Impostazioni"
        super().__init__(module, label, icon="settings")
        self.themis = themis
        self.module = module

    def records(self, *, deleted: bool = False) -> list[dict]:
        out = []
        for row in self.themis._stored(prefix=f"{self.module}."):
            scope = row.get("scope") or "system"
            if scope not in SCOPES or not self.themis.registry.definition(row["key"]):
                continue
            sid = row.get("scope_id") or ""
            out.append({"key": f"{row['key']}|{scope}|{sid}", "setting": row["key"], "scope": scope, "scope_id": sid,
                        "value": row.get("value"), "updated_at": row.get("updated_at")})
        return out

    def refs(self, rec: dict) -> set[str]:
        return set()

    def title(self, rec: dict) -> str:
        d = self.themis.registry.definition(rec.get("setting") or "") or {}
        return f"{d.get('label') or rec.get('setting')}: {_short(rec.get('value'))}"

    def subtitle(self, rec: dict) -> str:
        d = self.themis.registry.definition(rec.get("setting") or "") or {}
        layer = {"system": "", "profile": "profilo", "client": f"client {rec.get('scope_id')}"}.get(rec.get("scope"), "")
        return " · ".join(x for x in (d.get("group"), layer) if x)

    def same(self, a: dict, b: dict) -> bool:
        return a.get("value") == b.get("value")

    def check(self, rec: dict) -> str | None:
        d = self.themis.registry.definition(rec.get("setting") or "")
        if not d:
            return "impostazione non presente qui"
        if rec.get("scope") not in SCOPES:
            return "livello non importabile"
        try:
            validate(d, rec.get("value"))
            self.themis._target(d, rec.get("scope"), rec.get("scope_id") or None)
        except (SettingValueError, ThemisError) as exc:
            return str(exc)
        return None

    def write(self, records: list[dict], deletes: list[dict], *, mode: str) -> None:
        for r in records:
            self.themis.set(r["setting"], r.get("value"), scope=r.get("scope"), scope_id=r.get("scope_id") or None,
                            actor=ACTOR, reason="importazione")
        for d in deletes:
            self.themis.reset(d["setting"], scope=d.get("scope"), scope_id=d.get("scope_id") or None, actor=ACTOR)


def settings_sections(themis: Themis) -> list[SettingsSection]:
    """One section per module that declared settings (Themis' own = personal settings)."""
    modules = set(themis.registry.modules()) | {SELF_OWNER}
    return [SettingsSection(themis, m) for m in sorted(modules)]
