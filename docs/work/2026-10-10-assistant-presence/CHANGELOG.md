# CHANGELOG (spec) — assistant presence

- v1.0 — 2026-10-10 — spec created after brainstorming (states active/waiting/deep_sleep/dnd owned by Chronos,
  persisted in Archive, pings from all clients, deep sleep from agenda window or inactivity, consumers Athena,
  Oracle, Forge, Metis; everything configurable via central settings, implementation waits for that work) — source: user via external chat (Claude Code cloud session).
- v2.0 — 2026-10-10 — redesign: signals → data-defined states (one base + combinable overlays such as busy,
  eating, tired) → named effects asked by consumers; new states addable by modules or by the user without code
  changes (SOLID); Hermes notification level in scope — source: user via external chat (same thread).
