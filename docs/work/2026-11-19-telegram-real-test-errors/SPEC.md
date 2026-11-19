# SPEC — Telegram real-test errors

| | |
|---|---|
| **Version** | 1.1 |
| **Source** | user via external chat (screenshot of the Telegram client, 2026-11-19) |
| **Status** | Done |

Versioning: minor = refinement, major = scope/design change. Every bump goes in `CHANGELOG.md` (this folder).

## 1. Today (verified in code)
- Forge sent every notice twice (Hermes dispatch + send) with the task id in `<code>`, «Answer "approve development <id>"» to type, and one new proposal per Argus burst for the same trouble.
- Hermes' «While I was away» digest showed `(hephaestus)`, `(hermes)`, `(service)` and cut each line at a fixed length, mid-word, with HTML tags counted.
- Telegram split every bullet of a card into its own message, so tags opened in one bubble arrived as raw text.
- Hecate pushed the internal reason «Google not authorized yet: no refresh token found» (English, twice: Calendar and Gmail).
- Argus monitor texts named modules (`<b>chronos</b>`, `<code>chronos</code>`) and pasted raw log lines.
- Plutus' chat reply ended with «(import_id …)»; Oracle said «Handed to plutus».

## 2. Goal
What the owner reads on any client is plain, in his language: no ids, module names, raw errors, HTML code or commands to type; one notice per event; decisions are buttons.

## 3. Scope and design
- Forge `_notify`: one Hermes ingest with `_title`, `_message`, `_actions` (approve / reject / rollback endpoints), `_link` to the Development page, `dedupe_key`. `find_open_twin`: non-user sources get the open task for the same `origin.service` + `origin.kind`.
- Repairs page: Approve / Undo buttons instead of typed notes.
- Hermes `digest_line`: plain title or first real line, cut on a word with «…», no source; `<code>`/`<pre>` spans dropped, so notices stored before the fix show no ids either (v1.1).
- Telegram `_split_html_link_bullets`: split only lists with links.
- Hecate: plain notice with title and sign-in button, `dedupe_key hecate.<action>`, reason only in the log.
- Argus: area labels (`module_label`), `_title`, no raw lines; prompts forbid module/code names.
- Plutus: no id in the text; «yes» commits the latest preview. Oracle names the area.

## 4. New feature checklist (`docs/MARKO-RULES.md`)
1. Real job for the owner: understand notices and act with one tap.
2. Owner module (R1): each module its own texts; Hermes delivers.
3. Configuration: none.
4. Push or poll: push (Hermes).
5. Who confirms: the owner, via buttons.
6. WebUI and Telegram: buttons on both (Hermes actions); Repairs page buttons.
7. Stop, correct, undo: Discard / Undo buttons.
8. Docs that change: hestia-hephaestus, hestia-hermes, hestia-telegram, hestia-hecate, hestia-argus, hestia-plutus.
9. Texts: English in `tr`, Italian in the catalog.

## 5. Acceptance criteria
- No notice shows an id, a module name, HTML code or a command to type.
- The same trouble gives one open proposal.
- A plain list card is one Telegram message.
- Regression tests: Telegram list card, Argus recovery text, Plutus commit without id, Argus fallback area.
