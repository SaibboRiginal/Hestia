---
name: hestia-new-module
description: Use when adding a new Hestia service/module (Hestia-<Name>): layout, port, Hub registration, docs, plugin order.
---

- Start from `templates/python-service-template` (`create-service.bat` does it on Windows). Layout:
  `Hestia-<Name>/app/`, `tests/`, `hestia-<name>.md`, `Dockerfile`, compose entry in `docker-compose.global.yml`.
- Pick the next free port (see `docs/ARCHITECTURE.md` port table); register with Hub via `hestia_common` startup.
- R1: one job per module. A domain module owns its data through Archive (never its own DB), its UI as a WebUI
  plugin (`Hestia-<Name>/ui/`, plugin order in decades), its tools as MCP tools (`hestia-new-tool`).
- Add it to `readme.md` (one line), `docs/ARCHITECTURE.md`, `architecture-and-flow-map.md`, swagger.
