# CHANGELOG (spec) — assistant presence

- v1.0 — 2026-10-10 — spec created after brainstorming (states active/waiting/deep_sleep/dnd owned by Chronos,
  persisted in Archive, pings from all clients, deep sleep from agenda window or inactivity, consumers Athena,
  Oracle, Forge, Metis; everything configurable via central settings, implementation waits for that work) — source: user via external chat (Claude Code cloud session).
- v2.0 — 2026-10-10 — redesign: signals → data-defined states (one base + combinable overlays such as busy,
  eating, tired) → named effects asked by consumers; new states addable by modules or by the user without code
  changes (SOLID); Hermes notification level in scope — source: user via external chat (same thread).
- v2.1 — 2026-10-10 — core states (awake, idle, dnd: not deletable) vs optional ones; default conditions and
  effects proposed by Claude (nap 45 min, deep sleep 01–07 or 3 h, tired < 25 % Claude quota, dnd 2 h); digest in
  v1; `waiting` renamed `idle` — source: user via external chat (same thread).
- v2.2 — 2026-10-10 — aligned with central settings now on main: tunables declared with `settings_client.setting`
  (no env), state definitions stored as Themis setting `chronos.presence.states`; Hermes `notify.level` mapped on
  global notifications' `level` — source: coordinator relay (settings P1–P5 landed).
