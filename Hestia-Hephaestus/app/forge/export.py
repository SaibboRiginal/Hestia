"""«Copia per AI» of the Sviluppo page (SPEC docs/work/2026-10-18-moduli-core-e-mcp-esterno §B5).

Markdown of some Forge tasks for an AI working elsewhere (claude.ai, a PC checkout…): request, state, error,
dossier path and how to hand a fix back through Hestia's MCP (forge_task_note / forge_submit_branch). Built from the
same views as the MCP tools forge_tasks (``brief``) and forge_task (``overview``), so both paths say the same thing.
Returned to the browser only (clipboard or .md download): nothing is written to the repo — task text can carry
personal data and the repo is public.
"""
from __future__ import annotations

from typing import Any

MAX_EXPORT = 50

_STATE_IT = {
    "new": "nuovo", "proposed": "da approvare", "scheduled": "programmato", "queued": "in coda",
    "running": "in lavorazione", "awaiting_review": "diff da rivedere", "approved": "merge in corso",
    "merging": "merge in corso", "merged": "applicato", "deployed": "in produzione", "failed": "fallito",
    "rejected": "rifiutato", "rolled_back": "annullato (rollback)", "no_changes": "nessuna modifica",
}


def _clip(text: Any, n: int) -> str:
    s = str(text or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _task_md(t: dict, branch_states: set[str], user_sources: set[str]) -> list[str]:
    tid = str(t.get("id") or "")
    state = str(t.get("state") or "?")
    out = [f"## Task `{tid[:6]}` — {_STATE_IT.get(state, state)}", ""]
    out.append(f"- **Id**: `{tid}`")
    out.append(f"- **Stato**: `{state}`")
    src = t.get("source") or "user"
    out.append(f"- **Origine**: {'proposto da ' + str(src) if src not in user_sources else 'chiesto dal proprietario'}"
               f" (via {src})")
    if t.get("engine"):
        out.append(f"- **Motore**: {t['engine']}")
    services = t.get("services") or t.get("touched_services") or []
    if services:
        out.append(f"- **Servizi**: {', '.join(map(str, services))}")
    if t.get("workdoc"):
        out.append(f"- **Dossier**: `docs/work/{t['workdoc']}/` (SPEC.md, PROGRESS.md, CHANGELOG.md)")
    if t.get("branch"):
        out.append(f"- **Ramo Forge**: `{t['branch']}`")
    if t.get("merge_sha"):
        out.append(f"- **Merge**: `{str(t['merge_sha'])[:12]}`")
    if t.get("parent_task"):
        out.append(f"- **Segue il task**: `{str(t['parent_task'])[:6]}`")
    tests = t.get("tests")
    if isinstance(tests, dict) and tests.get("ok") is not None:
        out.append(f"- **Test**: {'passati' if tests.get('ok') else 'falliti'}")
    out += ["", "### Richiesta", "", str(t.get("request") or "").strip() or "(vuota)", ""]
    if t.get("context"):
        out += ["### Contesto", "", str(t["context"]).strip(), ""]
    if t.get("error"):
        out += ["### Errore", "", "```", _clip(t["error"], 3000), "```", ""]
    if isinstance(tests, dict) and tests.get("ok") is False and tests.get("tail"):
        out += ["### Coda dei test", "", "```", _clip(tests["tail"], 1500), "```", ""]
    if t.get("summary"):
        out += ["### Riepilogo del motore", "", _clip(t["summary"], 2000), ""]
    ext = t.get("external_branch")
    if isinstance(ext, dict) and ext.get("branch"):
        out += ["### Branch già consegnato", "",
                f"`{ext['branch']}` da {ext.get('by') or '?'} ({ext.get('at') or ''}): {_clip(ext.get('summary'), 500)}", ""]
    notes = t.get("notes") or []
    if notes:
        out += ["### Note", ""]
        out += [f"- {n.get('at') or n.get('ts') or ''} · {n.get('by') or '?'}: {_clip(n.get('text'), 800)}"
                for n in notes[-10:] if isinstance(n, dict)]
        out.append("")
    history = t.get("history") or []
    if history:
        out += ["### Ultimi passaggi", ""]
        out += [f"- {h.get('ts') or ''} · {h.get('state') or ''}" + (f" — {_clip(h.get('note'), 200)}" if h.get("note") else "")
                for h in history[-6:] if isinstance(h, dict)]
        out.append("")
    out += ["### Come consegnare una correzione", ""]
    out.append(f"- Dettagli aggiornati: MCP `forge_task(task_id=\"{tid[:6]}\")`"
               + (f", dossier `forge_dossier(name=\"{t['workdoc']}\")`" if t.get("workdoc") else "")
               + (", diff `forge_task_diff`" if t.get("branch") else "") + ".")
    out.append(f"- Analisi o indicazioni: `forge_task_note(task_id=\"{tid[:6]}\", text=\"…\")` — il motore la usa "
               "quando il task parte o viene riprovato.")
    if state in branch_states:
        out.append(f"- Correzione pronta: push di un branch su origin (non `auto/forge/*`), poi "
                   f"`forge_submit_branch(task_id=\"{tid[:6]}\", branch=\"<nome>\", summary=\"…\")`. Forge esegue i "
                   "suoi test e chiede l'approvazione al proprietario; merge, riavvio e rollback restano a Forge.")
    else:
        out.append(f"- In stato `{state}` Forge non accetta un branch: consegnabile solo in "
                   f"{', '.join(sorted(branch_states))}. Lascia una nota.")
    out.append("")
    return out


def export_markdown(tasks: list[dict], brief_lines: list[str], branch_states: set[str],
                    user_sources: set[str], missing: list[str] | None = None) -> str:
    """``tasks`` = forge_task views (``router.overview``), ``brief_lines`` = forge_tasks lines of the same tasks."""
    out = ["# Task di sviluppo di Hestia (Forge)", "",
           "Hestia si sviluppa da sola con Forge (Hephaestus). Lavora secondo `CLAUDE.md` del repo: dossier in "
           "`docs/work/<nome>/` (SPEC, PROGRESS, CHANGELOG), test con pytest, nessun segreto nei file. "
           "Approvazione, merge e rollback li fa solo Forge dopo l'ok del proprietario.", ""]
    if brief_lines:
        out += ["Riepilogo:", ""] + [f"- {line}" for line in brief_lines] + [""]
    for t in tasks:
        out += _task_md(t, branch_states, user_sources)
    if missing:
        out += [f"_Task non trovati: {', '.join(missing)}_", ""]
    return "\n".join(out).rstrip() + "\n"
