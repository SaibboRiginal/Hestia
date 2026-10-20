# memory_note: conversations with external AIs end up in Hestia's memory

| | |
|---|---|
| **Version** | 1.0 |
| **Source** | user via Project thread (brainstorm 2026-10-19 item 10: «MCP diretto + tool `memory_note` perché quelle conversazioni finiscano nella memoria di Hestia»; Marko 2026-10-20: «voglio che venga fatto tutto») |
| **Status** | Draft, waiting for Marko's approval |

## Goal
When Marko talks to an external AI (Claude, ChatGPT) connected to Hestia's MCP, that conversation never reaches
Archive's sessions nor Oracle's memory. A `memory_note` tool lets the external AI hand Hestia the durable facts that
came out of the conversation ("Marko is lactose intolerant", "the gym moved to Tuesdays"), so Hestia knows them
from then on in every client.

## Scope
1. **Tool `memory_note`** (declared by Oracle, the memory owner; executed through Hestia-MCP like every tool).
   - Clients: `external` plus `ui`/`telegram` (hidden in the Telegram menu), so the same tool works everywhere.
   - Input: `facts` (list of short sentences, required, max 10, each max 300 chars), `topic` (optional, a few words
     on what the conversation was about). The description tells the external AI to send only durable facts about
     Marko (preferences, constraints, decisions, personal details), already distilled, never a transcript.
   - It is a write tool: only accesses with write scope can call it (existing rule of the external door), and every
     call already lands as a quiet note in the notifications inbox (existing audit).
2. **Oracle endpoint** `POST /api/memory/note` → `{saved:[...], skipped:[...]}`.
   - Each fact goes through the same path as `memory.save`: domains from the embedding classifier (fallback
     `general`), class `durable_user_preference`, so Oracle uses it in the next turns exactly like what it learns
     in its own chats.
   - Origin kept in `extra_data`: `{source:"external", access:<X-Hestia-Access name>, topic, noted_at}`
     (`source:"chat"` for Oracle's own saves from now on).
   - Duplicates skipped: a fact equal (case/space-insensitive) to an active memory, or above a similarity
     threshold when embeddings are available, is returned in `skipped` with the existing one.
   - No LLM call: the external AI already distilled the facts, so a note is saved even when the local model is down.
3. **Tool `memory_recall`** (read-only, `external` too): the external AI can ask what Hestia already knows on a
   topic before answering, so the two memories do not diverge. Same keyword search as `memory.search`, max 20 rows,
   only `durable_user_preference`. Per-access tool allow-lists (Accessi AI) can switch it off for a given AI.
4. **Memoria page** in the Oracle plugin (Sistema section, next to Cervello and Documenti): list of active memories
   with text, domains, origin (in chat / which external AI) and date; search box; filter by origin; delete
   (deactivate, `PATCH /api/memory/{id}` `is_active=false` in Archive). This is where Marko checks what an external
   AI wrote. Icons, no emoji.
5. Docs: `hestia-oracle.md`, `Hestia-MCP/hestia-mcp.md` (external tools list), swagger, `docs/ARCHITECTURE.md`
   (external write tools), `architecture-and-flow-map.md`, root CHANGELOG, TESTING.md if a bench step is added.

## Out of scope
- Storing the external conversation itself as an Archive session (only distilled facts enter memory).
- Hestia asking the external AI anything (that is Oracle's external mode, already done).

## Acceptance criteria
- An external AI with a write access calls `memory_note` with two facts → both appear in the Memoria page with
  origin = that access name, and Oracle uses them in the next WebUI/Telegram chat in the matching domain.
- Same fact sent twice → second call returns it in `skipped`, no new row.
- Read-only access: `memory_note` is not listed and is refused; `memory_recall` works.
- Deleting a memory in the page removes it from Oracle's context.
- Unit/api tests: endpoint validation (empty, too many, too long), dedup, origin fields, tool visibility for
  `external`; plugin bundle builds.

## Design decisions (defaults, Marko can change them)
| # | Question | Default |
|---|---|---|
| D1 | Save at once or ask Marko to confirm each note via Hermes? | Save at once: it is Marko himself talking to the external AI; the quiet inbox note + Memoria page let him undo. |
| D2 | Also give external AIs `memory_recall` (read)? | Yes, switchable per access. |
| D3 | Who splits the conversation into facts? | The external AI (no Hestia LLM cost, works when the local model is down). |
| D4 | Tool names | `memory_note`, `memory_recall` (`<domain>_<verb>` rule). The old `memory.save` / `memory.search` stay for Oracle's own chats. |
