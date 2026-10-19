# Progress

- [x] Read brainstorm item 3, Scout poll chain, Iris, Hecate mail, Chronos register, module rules
- [x] SPEC v1.0 draft
- [x] Marko approves SPEC (answers §10) — v1.1
- [x] P1 Mail push core (Hecate watcher A + Pub/Sub B code, Iris subscriptions + dispatch + «Email» page, mail_client, Chronos retire, Archive generic stores) — tests green (Iris 40, Hecate 81, Chronos 43); docs pending in P7
- [x] P2 Scout on push (subscription scout:listings, /api/scout/mail, /api/scout/check, job retired, scout.cycle.interval removed, Hecate iris_email + Iris /api/email/ingest removed; Scout tests 25)
- [x] P3 Plutus core: service, store (Archive finance-store), PayPal parser, categories + learned rules, budgets, alerts, recurring, review, reminders, MCP tools, plugin manifest, Docker + compose + CI matrix; 24 tests green
- [ ] P4 Statements (Hype PDF, linking, recurring, chat attachments) — statement preview/commit/undo + PayPal↔bank linking done and tested in P3; left: Oracle chat attachments → Archive blob id passed to finance_import_statement
- [ ] P5 Plugin + reflection
- [x] P6 Gmail Pub/Sub (B) code — written with P1, inactive until env is set
- [ ] P7 Verify on cloud bench, docs, root CHANGELOG
