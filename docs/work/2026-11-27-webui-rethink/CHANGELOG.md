# CHANGELOG — WebUI rethought

- v1.0 — 2026-11-27 — first SPEC: four pieces (navigation and look, page pattern, search + quick ask, mascot link) — Marko approved proposal v2 («dai iniziamo da qui») — [ext-chat]
- v1.1 — 2026-11-28 — Oracle's documents page is «Shared files» (place assistant), not «Knowledge» — the page lists the files the owner gives the assistant; «Knowledge» read as memory — [ext-chat]
- v1.2 — 2026-11-28 — piece 2: «Ask» is a button of the page header and page settings stay on the shell's gear (no «…» menu in the header) — one way to reach each thing, the gear already exists on every page — [ext-chat]
- v1.3 — 2026-11-28 — piece 3: the WebUI asks the search providers itself, in parallel through its plugin proxy (no new backend fan-out); quick ask uses Oracle's chat in Quick mode, not `/api/llm/chat` — the proxy already guards each module and gives per-group arrival; the chat path saves the «Quick questions» conversation and keeps the tools, which the stateless `/api/llm/chat` does not — [ext-chat]
