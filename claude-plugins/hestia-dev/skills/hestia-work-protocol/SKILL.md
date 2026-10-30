---
name: hestia-work-protocol
description: Use for any task in the Hestia repo (new feature, fix, refactor, docs) — the mandatory dossier, changelog, docs-follow-code and precheck steps.
---

Source of truth: `CLAUDE.md` at the repo root and `docs/REGOLE-DI-MARKO.md`. Read them first; this is the checklist.

1. Dossier `docs/work/<YYYY-MM-DD>-<slug>/`. Exists → read `PROGRESS.md`, continue from the first open box.
2. `SPEC.md` from `docs/work/SPEC-TEMPLATE.md` **before code**: Version, Source, Status, goal, scope, acceptance,
   the new-feature checklist (R1–R6).
3. `PROGRESS.md` `- [ ]` / `- [x]`, updated after every step: a stop midway must say exactly what is left.
4. `CHANGELOG.md` in the dossier for every SPEC change: `vX.Y — date — change — reason — source`.
5. Root `CHANGELOG.md`: one line under the date, ending with `[ext-chat]`, `[forge:<task>]` or `[ai]`.
6. Docs follow code: behaviour → `Hestia-<Name>/hestia-<name>.md`; endpoint → `Hestia-Swagger/swagger.yml`;
   env → `.env.example` + compose comments; global rule → `docs/ARCHITECTURE.md`; contract → `architecture-and-flow-map.md`.
7. Tests: `python -m pytest -q -m "unit or api or format" Hestia-<Name>/tests`; a regression test per bug.
8. Commit, then `python tools/governance/precheck.py`; push only at 0 failed. Inside Forge: do not commit/push.
