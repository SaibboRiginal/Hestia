# Changelog

- v1.0 — 2026-11-14 — first version: backend English, people texts of tools in `locales/` — Marko asked
  «backend tutto inglese, utente lingua che usa» — ext-chat
- v1.1 — 2026-11-14 — phase 2 split in 2a Telegram / 2b settings, tools, module notices / 2c WebUI; English
  fallback for languages without a catalog — keeps each PR reviewable — ext-chat
- v1.2 — 2026-11-14 — 2b narrowed to settings and tools; module notices move to 2c, WebUI to 2d; tool texts fall
  back to English before Italian like fixed texts — one consistent chain for every language — ext-chat
- v1.3 — 2026-11-15 — 2d delivered as one catalog for shell and plugins, served before the bundles (script
  `/api/webui/i18n.js`) instead of a per-page language from the identity service — module-level constants are
  translated too and plugins need no host call — ext-chat
- v1.4 — 2026-11-16 — only Italian and English; German/French/Spanish dropped; one written standard and a gate —
  Marko: «mi serve solo italiano ed inglese… lasciare una guida… un solido standard per i moduli» — ext-chat
- v2.0 — 2026-11-16 — English source everywhere, Italian only in `locales/it/messages.json`; registration labels as
  plain English keys; Iris and Atlas follow «Lingua»; `locale()`, money and date words by language — Marko: «togli
  tutto l'italiano!! e devono usare tutti la lingua!!» — ext-chat
