---
name: hestia-setting-and-agenda
description: Use when Hestia code needs a tunable value, a schedule, a timer or periodic work — Themis settings and Chronos agenda instead of env vars and loops.
---

- Tunable → `hestia_common.settings_client.setting(key, label, type, default, …)` in the owning module, key
  `<module>.<area>.<name>`. Never a new env var (env = secrets + infrastructure). No on/off switch that only hides
  a feature (R3). The assistant only proposes changes; the owner confirms via Hermes.
- Periodic or timed work → `hestia_common.agenda_client` rule (job or window) registered by the module. Never
  `while True`/`sleep`/timers. Owner edits win; paused or cancelled stays so.
- Personal settings → `themis.personal.*`.
