# SPEC — Connections leftovers

| | |
|---|---|
| **Version** | 1.0 |
| **Source** | user via external chat (project thread «Unificare i collegamenti dei moduli», 2026-11-27: «si in generale usare i connettori senza rompere quello che esiste gia», answer to the three items left in .env after `docs/work/2026-11-19-unified-connections`) |
| **Status** | Done |

## Goal
The three things still configured by hand in Hecate's `.env` move to the Connections page (shared contract
`hestia_common.connections`), and whatever is already written there keeps working.

## Scope and decisions
1. **External MCP servers** — new card `hecate.external_mcp` (group home_service, not in the setup), N servers:
   name + address in the Themis setting `hecate.mcp.servers` (`[{name, url}]`, editor `connection:hecate.external_mcp`),
   optional key `HECATE_KEY_MCP_<NAME>` through Hephaestus. «Add and test» (MCP `initialize`, streamable HTTP),
   «Remove <name>», «Test» tries each one. Old `HECATE_MCP_<NAME>_URL/_KEY` lines: still listed and used; on the
   first start with settings loaded they are moved into the card and their lines emptied (Hephaestus may only empty
   them: `secrets.LEGACY_CLEARABLE`). The «External services» list on the AI accesses page links to the card.
2. **Provider switches** — `HECATE_ENABLE_PROVIDER_GOOGLE/MICROSOFT` removed (a feature switch): a provider is listed
   once its app is typed in its card (`enabled_without_credentials`) and configured once signed in. The cloud bench
   no longer sets it.
3. **Garmin email/password** — not documented any more: the card or «Link Garmin» on Telegram. An old pair written by
   hand is still used once to get the tokens when there are none; once tokens exist the pair is emptied.
   `env_credentials` left the Garmin status (connected = tokens).

## Acceptance
- Old `.env` lines keep working until moved; after the move nothing is left to edit by hand.
- Tests: Hecate `test_connections.py` (card + adoption), `test_outbound_mcp.py`, provider detection tests;
  Hephaestus `test_old_hand_written_lines_can_only_be_emptied`.
