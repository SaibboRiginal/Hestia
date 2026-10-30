# PROGRESS — Hestia inside Claude (mod + marketplace)

- [x] SPEC v2.0 → approved with Marko's three answers (v2.1)
- [x] P1 Oracle `assistant_profile` (tool external + `GET /api/assistant/profile`), prompt `client_contract_claude`,
      Themis `oracle.chat.profile_max_tokens`; tests `Hestia-Oracle/tests/test_assistant_profile.py` (Oracle suite 557 green)
- [x] P2 mod `claude-plugins/hestia`: band (mark, off · strumenti · Hestia, Ricorda · Memoria · Stato · Sviluppo,
      status line), `/hestia` command, `tool.check` refusal when off, `prompt.compose` persona section, panes,
      icon (`.claude-plugin/icon.png` from `assets/hestia.svg`), README with install + privacy; `claude plugin validate`
      ok, `tsc` ok, `claude plugin test` 4/4 on terminal, desktop, vscode, mobile
- [x] Marketplace `.claude-plugin/marketplace.json` (hestia, hestia-dev)
- [x] P3 shared memory: Ricorda (Claude distils → `memory_note`), notes from the Memoria pane, `/hestia
      importa-memoria` (preview, saves only after ok), notes counted on the band; Memoria page origin filter existed
- [x] P4 `claude-plugins/hestia-dev` (5 skills, guards on `.env*`/`data/`/token-like text, precheck reminder; test 1/1);
      claude.ai skill `claude-plugins/claude-ai/hestia`; *Accessi AI* card «Hestia dentro Claude Code»; docs
- [ ] Marko real run: install from GitHub after merge, set the address, `/hestia on`, consent on Accessi AI,
      «chi sei?», change tone in Impostazioni → next turn, «ricordati che…» → Memoria

Not verifiable in the cloud: a real Claude Code session against a running Hestia (OAuth consent in a browser).
