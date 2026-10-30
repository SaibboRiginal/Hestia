# Progress

- [x] Audit of the current Telegram client (strings, emoji, menu, command output, settings) — SPEC section 1
- [x] SPEC v1.0 (draft), v1.1 hybrid markers, v2.0 navigation redesign, v3.0 all functions + reply as context
- [x] Marko approves SPEC + choices of section 9 (2026-10-24, all as proposed; v3.1 menu as configuration)
- [x] T1 `ui.py` grammar + local strings (`ui.py`, `store.py`, `inputs.py`, `render.py`)
- [x] T2 navigation as configuration: `catalog.py`, `menu/` (defaults, model, editor), `nav.py`, `actions.py`,
      `local_actions.py`, bot profile, robustness; `tools/governance/check_telegram.py` in CI
- [x] T3 results without the model: generic renderer, `hestia_common.display`, display in Hercules, Chronos,
      Hygieia, Plutus, Wardrobe, Scout; Hestia-MCP strips it for non-Telegram clients; signal/format path removed
- [x] T4 chat: notices in the answer, feedback + Ascolta row, slim settings (4 + voice + custom prompt)
- [x] T5 notifications, assistant questions, chat queue texts, confirmations persisted in the store
- [x] T5b all functions: 192 actions in 11 areas (hidden only `interno`), files in/out, reply/quote as context
      (Oracle `quoted`)
- [x] T7 Mini App: `webapp.py` buttons + menu button, Telegram `/api/webapp/verify`, WebUI `/api/webui/auth/telegram`,
      frontend login from `tgWebAppData` (frontend build ok; .NET build not verifiable in the cloud session)
- [x] T6 docs: SPEC v3.2 section 10, `hestia-telegram.md`, ARCHITECTURE, swagger, flow map, module docs, root CHANGELOG
- [x] Parity list (closed 2026-10-30 in `docs/work/2026-10-30-cose-aperte`: export/import/restore, backup, presence and
      repair history already had tools; memory clean-ups and Athena commitments added) — WebUI actions still without a tool (to add in their own modules, next wave):
      export/import `.hestia` (Archive transfer), backup now / restore (Archive), presence state change (Chronos),
      Athena proposals / thoughts list, Argus remediation history. Hermes inbox is the «Notifiche» door already.
- [ ] Marko real run: bot conversation on the real stack (`up-all.bat --build`), Mini App with the tunnel address

## Notes
- Audit numbers from main @ af732d7: ~210 emoji in Telegram strings, 80 module tools visible + 22 local commands.
