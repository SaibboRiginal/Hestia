# Consistency check of the 2026-10-17 workstreams

| | |
|---|---|
| **Version** | 1.2 |
| **Source** | user via external chat (Marko: «sono tutti completati? sono tutti consistenti tra di loro?») |
| **Status** | Implemented on branch `claude/project-thread-w9loez` 2026-10-18 — waiting Marko's ok to merge into main |

## Goal
Check that the work built in parallel threads follows one standard: client plugins (Scout as plugin), Hercules,
Hygieia, Wardrobe, Hermes one-live-reminder. Fix small, clear inconsistencies; list the bigger ones.

## Checked (consistent)
- Storage: each module one Archive table + `/api/<x>-store` with the same LWW + seq cursor protocol (routers identical).
- Hub registration: `SERVICE_TYPE=module`, tags `module,<domain>,context`, `layer:domain`, vocabulary accepted by Hub.
- Settings in Themis via `settings_client`; no new env vars for tunables; only `TZ` + infra in compose.
- No feature-hiding switches left: every remaining `*.enabled` drives something that acts on its own (reminders,
  alerts, monthly review).
- Hermes: reminders use `replaces`, `resolves: true` on the "done" actions, target `owner`, agenda `job_rule`s.
- Plugins: all four use `PluginClient` + `@hestia/webui-sdk` `hxk-*` kit, Home quick actions with `source` + `undo`.
  Typecheck and esbuild build OK for Scout, Hercules, Hygieia, Wardrobe (2026-10-18).
- `/api/module/context` in the three new modules; CI "Hestia Tests" matrix includes them, green on 182d68d.
- No personal data in the new files.

## Fixed on main
- Plugin order collided (Hygieia and Wardrobe both 40, Scout quick action 40/50): Scout 20s, Hercules 30s,
  Hygieia 40s, Wardrobe 50s for pages and quick actions.
- `/api/module/context`: Hercules added its «Allenamento: » prefix after cutting to the budget (could exceed it);
  Wardrobe default budget 600 → 400 like the others.
- `hygieia.currency` string → enum with the same options as `wardrobe.currency`.
- Hercules and Hygieia notifications now carry `_link` (open the plugin page from the notification) like Scout
  and Wardrobe.
- Leftovers of the removed diary switch (swagger `journal_enabled`, root CHANGELOG «(off)»); compose comment
  «Hercules API port (self care)»; Hercules SPEC status still said «UI bundle in progress».

## Decisions (Marko, 2026-10-18)
1. **Module context**: no change. Oracle's classifier already picks the domain and loads its tools; the modules'
   `/api/module/context` stays available for a future consumer (day planning), nothing wires it into every chat.
2. **Tool names** = `<domain>_<verb>` in English: `hercules_*` → `fitness_*`, `guardaroba_*` → `wardrobe_*`
   (`wardrobe_summary`, `_search`, `_piece`, `_add`, `_update`, `_outfits`, `_create_outfit`, `_suggest`,
   `_log_worn`, `_stats`, `_packing`, `_delete`); `selfcare_*` already fits. Rule in docs/ARCHITECTURE.md.
3. **Common rules, work done by the dedicated modules**:
   - Personal settings `themis.personal.week_start` / `themis.personal.currency` (owner Themis, group «Personali»,
     `settings_client.PERSONAL`). Modules read them with `SettingsClient.follow_personal()`: register sends
     `follows`, Themis answers `shared` and reloads every follower when one changes. Removed `hercules.week_start`,
     `hygieia.week_start`, `hygieia.currency`, `wardrobe.currency`; Wardrobe's weekly goal now honours week start.
   - Reminders: `hestia_common.reminders` — `reminder_settings(module)` (same `<module>.reminder.enabled` off +
     `.max_per_week`) and `reminder_event(...)` (Hermes body with `replaces`, `target: owner`, `_link`). Schedule
     stays an agenda job (Chronos), delivery stays Hermes. Hygieia's `hygieia.reminders.*` → `hygieia.reminder.*`,
     off by default like the others (each routine still chooses its own reminder).
4. Reminder models harmonised by 3. Generic Archive module store: optional refactor, not done.

## Verified with a real run (2026-10-18, v1.2)
Marko: «fai tutti i test che puoi … e aggiusta tutto», for every waiting thread.
- pytest (unit/api/format) green in every Python service; .NET WebUI build (0 warnings) and Angular production
  build OK; the four plugin bundles build.
- Local stack (Hub, Archive + Postgres, Themis, Hermes, Chronos, Hercules, Hygieia, Wardrobe): all register,
  catalog order right, tools listed with the new names, agenda rules registered, `themis.personal.week_start`
  pushed to the three modules, quick actions mark/undo, module context, reminders delivered in the Hermes inbox
  with `_link` and answered from it (the module gets the action).

## Fixed after the real run
- Reminders were never delivered: `reminder_event` put the module domain on the envelope, but Hermes' standing
  owner subscription listens on domain `system` (like Themis, Argus, Hecate). Envelope domain is now `system`,
  the module domain stays in the payload; regression assert in `test_themis_personal.py`.
- Chronos `/health` answered 500 when Hecate was down (agenda and presence looked down): providers are now
  informative only; regression test `test_health_ok_when_hecate_unreachable`.
- Hercules and Wardrobe could nudge twice the same day when the job ran again: «one a day» guard like Hygieia
  (`sent_today`), tests.
- `selfcare_overview` → `selfcare_summary` like `fitness_summary` / `wardrobe_summary`; no personal name in the
  tool description.
