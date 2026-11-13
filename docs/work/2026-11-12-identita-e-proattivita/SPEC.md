# SPEC — Identità, imprinting e proattività dell'assistente

| | |
|---|---|
| **Version** | 1.1 |
| **Source** | user via external chat (thread «Rendere Hestia viva come Verity», Marko 2026-11-09 and 2026-11-12: «mi piace vai») |
| **Status** | Implemented, merged (PR #98); real run by Marko pending. Timing of «parla con te» changed by `docs/work/2026-11-13-prima-osserva-poi-propone` |

Versioning: minor = refinement, major = scope/design change. Every bump goes in `CHANGELOG.md` (this folder).
Follows `docs/work/2026-11-06-hestia-viva` (persona, awareness, reactions).

## 1. Goal
After trying the UI Marko said: the Verity-style personality is still not visible and must be there in every mode;
the assistant must know who he is and that it is **his** assistant; its name must be changeable and it can be a she
or a he (imprinting, once, at the first setup); and, separately, it must have Athena's proactivity to ask questions
or chat like a real person.

## 2. What was found in the code (why the personality did not show)
- `conversation_style_contract`, added after the persona on every path, said «saluto di una parola», «domanda solo
  se ambigua», «no interiezioni, no stato»: it switched off exactly what the persona asked for. The quick answer
  added «Solo la richiesta attuale. No argomenti nuovi.»
- «Hestia» was written in about twenty prompts; there was no owner name and no gender anywhere.
- Athena thinks about the owner's life every day, but by his choice of October the observations only reach him in
  the evening recap: she never wrote first.

## 3. Scope

### A — Identity (Themis personal settings, `hestia_common.identity`)
- New personal settings, group «Tu e l'assistente»: `themis.personal.owner_name`, `themis.personal.owner_call`,
  `themis.personal.assistant_name` (default `Hestia`), `themis.personal.assistant_gender` (`lei` default · `lui`).
- `hestia_common.identity`: `read(settings.get)` → `{assistant, gender, owner_name, owner}`; `render(text, ident)`
  fills `{assistant}`, `{owner}`, `{owner_rule}`, `{g:lei-form|lui-form}`; other braces untouched.
- Oracle: follows the personal settings; `prompt_config.prompt()` renders every prompt; the persona opens «Sei
  {assistant}, l'assistente personale di {owner}: {sua|suo} e di nessun altro»; unknown name → «chiediglielo alla
  prima occasione». `ChainAgent` reads the persona at every call (live, no restart). Tokens also in the quick
  answer, the agent-loop preambles, the Claude contract and the notification prompts.
- Hermes: the «frase» style prompt uses the same tokens.
- Not renamed: the product, modules, repository, internal extractor prompts («compilatore di Hestia»).

### B — Imprinting, once (WebUI guided setup)
- Second step «Tu e io»: your name (needed to go on), how to call you, the assistant's name, a she or a he.
  Saved as the four settings above; the recap row at the end shows them. Later: Sistema → Impostazioni → Personali.
- `IdentityService` (frontend): the chat placeholder, the voice button and the setup greeting show the chosen name.

### C — Style contract rewritten
- Forbids bot closings and status lines; on small talk she answers warmly and may ask one real question or pick up
  something she knows; on a task she goes to the point; no unasked option lists; short.
- Quick answer: «Rispondi a quello che dice ora», 1–2 sentences.

### D — «Parla con te»: she writes first (Athena → Oracle → Hermes)
- **When** (Athena `core/talk.py`): agenda window `athena.talk` (default 9–21, the owner moves/pauses it), at most
  `athena.talk.max_per_day` (default 2, 0 = never), `athena.talk.min_gap_hours` apart (default 4), never while he
  is chatting, never at a fixed minute. Checked before the thinking gate.
- **Why**: mood of today, signals `alta`/`attenzione`, a long silence; none → Oracle may ask one thing it does not
  know yet about him (work, people, passions…), from what memory lacks.
- **What** (Oracle `POST /api/chat/opener`): persona + memory digest + awareness lines → 1–2 plain sentences, or
  `NIENTE` (no message).
- **How** (Hermes): event with `kind: athena.talk`, `_chat: true`, no title: Telegram sends plain chat text, the
  WebUI adds it to the open chat (and Notifiche); never retracted; presence and quiet hours hold as for any
  notification. Oracle's awareness adds «Oggi gli hai scritto tu per prima: …» so his answer has its context in
  any chat. Kept in `signals-store` (`kind=talk`) so she does not repeat herself.
- Manual: `POST /api/athena/think?track=parla` («Scrivimi ora»); `GET /api/athena/talk`.
- Unchanged: life observations reach him only in the evening recap.

## 4. Out of scope (other threads)
- Prompt composer, per-client format, quick answer with memories, classifier, module voice block, prompt test
  bench: thread «Migliorare i prompt per ogni situazione» (it calls `identity`/`prompt()` of this dossier).
- Empty «Ragionamento» in chat; settings shortcuts.

## 5. New feature checklist (`docs/REGOLE-DI-MARKO.md`)
1. Real job: an assistant that is yours, knows you, and talks first when it has a reason.
2. Owners: Themis (personal settings), Oracle (persona, opener text), Athena (when/why), Hermes (delivery),
   clients (display). No new module.
3. Configuration: four personal settings; `athena.talk.max_per_day`, `athena.talk.min_gap_hours` (tunables, 0 =
   never is a quantity, not a switch); hours = agenda window.
4. Push: Hermes push; automatic (loop) and manual («Scrivimi ora» endpoint).
5. Confirms: nothing writes data without the owner; what he answers is a normal chat turn (memory as usual).
6. Clients: WebUI (setup step, chat, Notifiche) and Telegram (chat text).
7. Stop/correct: 0 = never, pause the window, change name/gender/name any time.
8. Docs: hestia-oracle/athena/hermes/telegram/webui/themis/shared .md, swagger, ARCHITECTURE (rule 14), flow map,
   REGOLE-DI-MARKO (R8), root CHANGELOG.

## 6. Acceptance criteria
- Changing the four settings changes the persona of the next turn without a restart (name, gendered words, owner).
- The style contract no longer contains «saluto di una parola»; it allows one real question on small talk.
- Setup step «Tu e io» saves the four settings; the chat shows the chosen name.
- Athena sends at most N messages a day inside the window, none while he chats, none when Oracle says `NIENTE`;
  model or Hermes down → retry later, nothing lost.
- The message is chat text on Telegram (not cut at 80 chars) and appears in the WebUI chat; Hermes never retracts
  it; the next turn's context has the awareness line.
- Tests: identity render/read, persona tokens, live role prompt, style, opener (prompt, NIENTE, endpoint),
  awareness talk line, Athena talk (due, limit, pause, reasons, delivery, failures, avoid), Hermes `kind`/identity,
  Telegram `_chat`.

## 7. Not done (told to Marko in the thread, his call)
- No page yet shows what she wrote and why (`GET /api/athena/talk` exists); no «Scrivimi ora» button in the UI.
- Telegram's own static texts and the voice wake word still say «Hestia».
- The opener is not saved in the chat history (context = awareness line of the same day).
