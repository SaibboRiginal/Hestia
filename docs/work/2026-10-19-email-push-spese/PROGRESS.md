# Progress

- [x] Read brainstorm item 3, Scout poll chain, Iris, Hecate mail, Chronos register, module rules
- [x] SPEC v1.0 draft
- [x] Marko approves SPEC (answers §10) — v1.1
- [x] P1 Mail push core (Hecate watcher A + Pub/Sub B code, Iris subscriptions + dispatch + «Email» page, mail_client, Chronos retire, Archive generic stores) — tests green (Iris 40, Hecate 81, Chronos 43); docs pending in P7
- [x] P2 Scout on push (subscription scout:listings, /api/scout/mail, /api/scout/check, job retired, scout.cycle.interval removed, Hecate iris_email + Iris /api/email/ingest removed; Scout tests 25)
- [x] P3 Plutus core: service, store (Archive finance-store), PayPal parser, categories + learned rules, budgets, alerts, recurring, review, reminders, MCP tools, plugin manifest, Docker + compose + CI matrix; 24 tests green
- [x] P4 Statements: preview/commit/undo, PayPal↔bank linking, recurring; chat PDF via Oracle `attachment_handlers` hand-off (Oracle 4 new tests, 414 green; Plutus 25 green)
- [x] P5 Plugin «Spese»: panoramica, movimenti + dettaglio + form, budget, abbonamenti, importa (PDF + email PayPal), statistiche, categorie e regole, widget mese/ultimi; riepilogo mensile, avvisi budget e promemoria estratto (agenda → Hermes). Icone wallet/upload/target/mail aggiunte a WebUI e kit
- [x] P6 Gmail Pub/Sub (B) code — written with P1, inactive until env is set
- [ ] P7 Verify on cloud bench, docs, root CHANGELOG — docs + swagger + CHANGELOG done; left: cloud bench run, PR, CI, merge
