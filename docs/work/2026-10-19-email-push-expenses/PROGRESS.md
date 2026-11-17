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
- [x] P7 Docs (module docs, ARCHITECTURE, AI-GUIDE, readme, flow map, swagger, .env.example), root CHANGELOG, PR #8 (main merged: brain offline)
- [x] P7 Cloud bench 2026-10-19: 23 containers up, 19 on Hub, 42 WebUI pages 0 JS errors, phone ok. Found and fixed: Hub rejected Plutus (tag `finance` not allowed, 422) → regression test in Hub. Real chain checked: PayPal mail in Archive `finance` → ring → Spese transaction (−23,50, marked evaluated); Iris without Gmail login answers 503 and stores nothing (Hecate retries) as designed; Hype-like PDF sent to Oracle `/api/chat/document/json` → hand-off to Plutus → reply «Li registro?» in chat history → `finance_import_statement` commit: 3 added, PayPal row linked, month spent 55,90 counted once. Screens: Spese panoramica/importa/movimenti/budget/abbonamenti/statistiche/categorie, Iris Email
- [x] P7 CI green on PR #8 (21 checks), merged by Claude as Marko asked. Left for Marko: real run on his PC (`up-all.bat --build`), Google re-login if Hecate asks, optional Gmail Pub/Sub setup (hestia-hecate.md)
