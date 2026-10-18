# Consistency check of the 2026-10-17 workstreams

| | |
|---|---|
| **Version** | 1.0 |
| **Source** | user via external chat (Marko: «sono tutti completati? sono tutti consistenti tra di loro?») |
| **Status** | Done 2026-10-18 — small fixes on main, larger items below wait for Marko's decision |

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

## Open — needs Marko
1. **Nobody reads `/api/module/context`.** The modules serve it, Oracle doesn't call it, so the assistant doesn't
   see training/self care/wardrobe state unless it calls a tool. Needs an Oracle consumer (discovery by capability
   `context_endpoint`, budget per module, cache).
2. **Three naming styles**: tools `hercules_*` (module), `selfcare_*` (domain, English), `guardaroba_*` (Italian);
   API `/api/hercules`, `/api/selfcare`, `/api/wardrobe`. Pick one rule (proposal: tools and API by domain in
   English) and rename in one pass (tools, swagger, UI `api_prefix`, docs).
3. **Duplicated personal tunables**: `hercules.week_start` + `hygieia.week_start`, `hygieia.currency` +
   `wardrobe.currency`. Proposal: one personal setting each (Themis «Personali»), modules read it.
4. **Two reminder models**: Hercules/Wardrobe one switch off by default; Hygieia master switch on + per-routine
   switch off. Both respect the rules; harmonise only if Marko wants one behaviour.
5. Archive has three copies of the same store router: could become one generic module store (refactor, optional).
