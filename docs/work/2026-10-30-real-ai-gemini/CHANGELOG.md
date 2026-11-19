# CHANGELOG — Test with the real AI (Gemini)

- v1.0 — 2026-10-30 — first version, written with the fixes found on the bench — Marko asked to test the real AI with Gemini — user via external chat
- v1.1 — 2026-10-30 — round 2: behaviour of the whole assistant (memory discipline, truth about actions, MCP doors), fixes 11–21 — Marko asked to test that the AI answers sensibly, saves only what matters and that the prompts work — user via external chat
- v1.2 — 2026-10-30 — round 3 with small models: tools of the turn's domains only, no memory copy of a module write — Marko may run a local 9B model — user via external chat
- v1.3 — 2026-10-30 — safeguards in code (turn guards 24–28) — Marko: the AI must not be free to make trivial mistakes — user via external chat
- v1.4 — 2026-10-30 — fixes 29–31 after verification round 4 (empty-values read passes, refused ≠ failed, no empty answer) — bench findings — user via external chat
