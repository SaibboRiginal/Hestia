# Prove reali sul banco cloud

| Version | Source | Status |
|---|---|---|
| 1.0 | Hestia AI proactive (coordinator: Marko away from his PC for two weeks, «real run» of the pending dossiers on the cloud bench) | done |

## Goal

The dossiers below were all waiting for «Marko: `up-all.bat --build` and a real run». Do that run on the cloud test
bench (`docs/work/2026-10-19-banco-prova-cloud/`) instead: the whole stack, the real doors a client uses, the real
browser, and fix what breaks.

- Hercules (coach) `2026-10-17-coach-module` · Hygieia (self care) `2026-10-17-selfcare-module` ·
  Guardaroba `2026-10-17-modulo-guardaroba` · client plugins `2026-10-17-client-plugins` ·
  core plugins + MCP `2026-10-18-moduli-core-e-mcp-esterno` · Hermes notifications `2026-10-10-hermes-global-notifications`
  and repeats `2026-10-17-hermes-repeat-notifications` · presence `2026-10-10-assistant-presence` ·
  central settings `2026-10-10-central-settings`.

## Scope

- In: module APIs through the WebUI plugin door, chat → Oracle → Hestia-MCP → module tools, agenda jobs, Hermes
  notifications and their buttons, presence, Themis settings from the WebUI, external MCP (tokens, 401/403/429,
  OAuth metadata), every plugin page in Chromium (desktop light, phone 360 px dark), Home quick actions.
- Out: Telegram (`api.telegram.org` is blocked in the cloud session), Google/Microsoft OAuth (needs a person),
  real model quality (no GPU; the fake LLM answers, so semantic search and wording are not judged).

## Design decisions

- **Repeatable, not one-off**: the run is a script, `python tools/cloud_test.py flows [area…]`
  (`tools/cloud_test/flows.py`), so every later change can be re-checked the same way (Marko's «test every change»).
  It writes `.cloud-test/flows.md` + `.cloud-test/flows/*.png` (git-ignored) and creates its own «Banco …» data.
- **Chat without a model**: the fake LLM gains scripted tool calls — a message with `#tool <name> {args}` makes it
  answer with that tool call (native `tool_calls` or a `<tool_call>` block) until the result is in the prompt, then
  it answers with the result. Only directives of the current turn count (the history is ignored).
- Doors used are the clients' ones: `/api/webui/plugins/<module>/call/…` (plugin `host.api`), `/api/webui/notifications`,
  `/api/webui/central-settings`, `/api/webui/presence`, the WebUI `/mcp` door; service-to-service steps go through
  `POST {HUB}/api/route/<svc>/…` like a module.
- Days that cannot pass in a test (a reminder ignored for three days) are emulated by sending the same Hermes thread
  again through the Hub, as the module job would.

## Acceptance criteria

1. Every flow area runs green on the bench; failures found are fixed in code with a regression test, not in the test.
2. Each pending dossier's PROGRESS.md says what the bench verified and what still needs Marko (Telegram, real model,
   his phone/PC).
3. Report in Italian in the project files (`cloud-test/2026-10-19/prove-reali.md`).
