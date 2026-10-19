# Progress — Oracle a blocchi

- [x] Read brainstorm (section 0 + Oracle sections), Oracle settings/providers/gateway, Forge engines
- [x] SPEC v1.0 draft; v1.1 with Marko's answers
- [x] Marko approved SPEC v1.1 (card, 2026-10-19)
- [x] P1 Named providers + chains + quota skip (Oracle core) + tests
- [x] P2 Use cases declared by modules (Scout, Athena, Argus, Chronos, Wardrobe, Forge) → chains, migration of `oracle.models.*`, Modelli simplified / rest advanced; Forge engine `oracle` on `forge.codice`, profiles removed
- [x] P3 Usage rows (module = use case prefix), Archive `llm-usage`, `/api/llm/usage`
- [x] P4 WebUI Cervello tabs Uso + Modelli (chain editor); Sistema links the object settings to it
- [x] P5 External agent mode: `oracle.brain.*`, stdio MCP bridge, Claude Code + Codex adapters, session cache, fallback interna, `ORACLE_INSTALL_CODEX`
- [x] P6 Docs (oracle, hephaestus, archive, scout, athena, argus, chronos, wardrobe, metis, shared md, swagger, .env.example, compose, ARCHITECTURE, AI-GUIDE, readme, TESTING), SPEC v1.2, root CHANGELOG
- [x] Cloud bench run (`python tools/cloud_test.py all`): all up and smoke ok except Hephaestus crash-looping on `from core.capabilities` (bare import, hidden by the test sys.path) → relative import + regression test that imports the engine like the container
- [ ] Bench re-run after the Hephaestus fix
- [ ] PR opened, CI green, merged
- [ ] Marko real run: add keys `ORACLE_KEY_*`, check Cervello → Modelli and Uso, try brain mode Esterna with Claude Code

Tests: Oracle 465, Archive 23, Hephaestus 43, Scout 21, Athena 102, Argus 18, Chronos 41, Metis 25, Wardrobe 19 pass;
Oracle and Hephaestus UI typecheck + bundle build; Angular `ng build` ok.
