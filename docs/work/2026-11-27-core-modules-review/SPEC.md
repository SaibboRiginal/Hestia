# SPEC — Core modules review (bugs, broken flows, lost data, rule breaks)

| | |
|---|---|
| **Version** | 1.1 |
| **Source** | user via external chat («Scout had many bugs, can we review Hestia's core modules again?») |
| **Status** | Done (§4 answered by the owner 2026-11-27: 2, 5, 6 done; 1, 3, 4 kept as they are) |

Versioning: minor = refinement, major = scope/design change. Every bump goes in `CHANGELOG.md` (this folder).

## 1. Scope

The platform modules every other module leans on: Oracle, Hermes, Themis, Archive, Chronos (agenda), Hub,
Iris (mail dispatcher), MCP, Athena (memory), Telegram, WebUI and `hestia_common`. Read in the code, flow by flow,
looking for the same kinds of faults the Scout review found (data lost when a step fails, rows cut by a limit,
filters ignored, state overwritten, rule breaks). Only clear bugs are fixed here; design choices are in §4.

## 2. Bugs fixed

| # | Module | Fault (verified in code) | Fix |
|---|---|---|---|
| 1 | Hermes | A batched entity (house listing) left its Archive row `queued` forever: if Hermes restarted during the settling window, or gave up after the retries, that listing was **never notified again** (`queued` blocks dedupe and nothing ever changed it). | Rows become `delivered` / `failed`; at startup the `queued` ones go back in their batch (audience and filters stored in the row). |
| 2 | Chronos + Archive | The agenda read `calendar_items` with `limit=1000` ordered by start: finished one-offs (history, never purged) pushed **new tasks past the limit, so they never fired**, `get(key)` answered 404 and a module re-registering its rule overwrote the user's edits. | Live views ask Archive only for unfinished items (`exclude_statuses`), one item is read by key (`external_ids`), limit 5000 with a log when reached. |
| 3 | Chronos | The hourly re-assert of every module rule rewrote each rule from a copy read before the loop: a job fired meanwhile got its old `last_fired` back (**fired twice**) and its run lost. | Re-read under the lock; write only when the rule really changed (times compared as instants). |
| 4 | Themis | Approving or rejecting a proposal searched only the newest 200: an older one answered «unknown proposal». | Lookup by `proposal_id`. |
| 5 | Themis | The confirmation card named the module («… (oracle)», «Athena proposes») and showed labels/choices in English. | `{assistant}` / `{assistant} (chat)` / «X (external AI)», labels and choices translated. |
| 6 | Themis | A yes/no setting accepted «no» only in English. | No words of every language (`common.no_word`). |
| 7 | Hermes | The «to decide» mark, the release of held notifications, the voice copy and the retract pass wrote the state they had read without compare-and-set: an answer arriving meanwhile could be **reopened** (answerable twice). | `only_if_states=[state]` on each of them. |
| 8 | Hermes + Oracle | Confirm questions stored the Italian value `si` (R9: stored values English); Hermes labels not translated. | `yes` / `no`, labels via `tr`. |
| 9 | Hermes | The fallback list of a listing batch put URL and title in HTML unescaped and wrote «mq». | Escaped, «m²». |
| 10 | MCP + hestia_common | `/mcp` (gateway and every module's own) and handler-only REST routes ran **sync handlers on the event loop**: one slow tool (seconds of Hub calls) froze every other call and the health check of that service. | Worker thread for sync handlers, `await` for async ones; external door's token check too. |
| 11 | Athena | The nightly consolidation added a new memory «[REINFORCED xN] …» at every run a pattern was seen (no quote, no undo): the memory filled with copies. | The weight of the memory that already says it goes up (learning log `reinforce`, undoable); nothing new is created. |
| 12 | Athena | A conflict retired the old memory even when the new fact had been dropped (no exact quote) and for any id the model wrote: **memory lost with nothing in its place**. | Only ids the model was shown, only when the new fact was saved in the same run; Archive errors respected. |
| 13 | Athena | Presence label «Athena thinks» named a module (R5). | «{assistant} thinks». |
| 14 | Oracle | Claude Code status said «available» with only `ANTHROPIC_API_KEY`, which Oracle never hands to Claude Code. | Only the subscription login counts. |
| 15 | hestia_common | `reminder_settings` / `voice_setting` declared help texts with `tr` at import (R9: registration labels plain English). | Plain English, translated at the edge by Themis. |
| 16 | Hub | Two dead entry points (`src/main_old.py`, `src/main_new.py`) next to the real `main.py`. | Removed. |

Regression tests: `Hestia-Hermes/tests/test_hermes_batch_rows.py`, `Hestia-Chronos/tests/test_agenda_rows.py`,
`Hestia-Athena/tests/test_consolidator.py` (class `TestConflictsAndPatternsSafe`); existing tests updated for `yes`.

## 3. Checked, no fault found

Hub routing envelope and deadline header, LLM bus (priority, deadline, pre-emption), `settings_client`
(apply/live/restart, followers), Themis undo/presets/history, Iris dispatcher (durable store before ring, partial
result keeps Hecate's cursor), Archive outbound compare-and-set, MCP accesses (revoke/rotate, rate limit),
Telegram offline chat queue (claim/release, back to queued on failure).

## 4. Proposals — the owner's answers (2026-11-27, one card each)

| # | Proposal | Answer | What was done |
|---|---|---|---|
| 1 | Hermes delivery retry: own timer loop → agenda job `hermes.delivery.retry`? | **Keep the internal timer** | Nothing: the retry loop stays in Hermes (owner's choice, no polling job in the agenda). |
| 2 | Message queued while offline, `failed` after 5 drains, nobody told | **Tell me** | Telegram and WebUI drains read the state Archive returns on `done`; `failed` → one Hermes notice for the owner «Message not answered» with the text (key `chat_queue.failed.<client>.<id>`). Test `Hestia-Telegram/tests/test_chat_queue.py::test_given_up_message_is_told_to_the_owner`. |
| 3 | Athena decay retires old memories by itself | **Keep automatic** | Nothing (logged and undoable, as today). |
| 4 | Purge finished one-off agenda items | **Keep them all** | Nothing (harmless for firing since fix §2.2). |
| 5 | Listing deduped forever, price drop never told | **Yes, when it falls** | Hermes lets a listing through again only when its price is below the last price told to that subscription (lowest live row of the dedupe key); the entity carries `previous_price`, the message says it is cheaper now. A batch still `queued` is not doubled. Tests `TestPriceDrop` in `Hestia-Hermes/tests/test_hermes_batch_rows.py`. |
| 6 | Hub failover after a timeout could run a POST twice | **Only when the connection fails** | `router.may_fail_over`: reads fail over on any network error, writes only when the first instance was never reached (refused, unknown host, connect timeout). Unicast/fan-out and stream paths. Test `Hestia-Hub/tests/test_hub_failover.py`. |

## 5. Acceptance criteria

- Every fix above in code with its module doc, swagger (Archive calendar filters), this dossier and the root
  CHANGELOG; `tools/governance/precheck.py` 0 failed; CI green; PR merged.
