# SPEC — WebUI rethought: navigation, look, pages, search, mascot link

| | |
|---|---|
| **Version** | 1.2 |
| **Source** | user via WebUI project chat (Marko, 2026-11-27): «non so dove sia cosa, ci sono 20000 voci, la sidebar e logo sono stile claude, non ha uno stile moderno, vivace e facile da usare» |
| **Status** | Approved («dai iniziamo da qui», 2026-11-27 22:24) — piece 1 in progress |

Proposal shown to Marko (v2, mock + screenshots): https://claude.ai/artifact/GCph7e1FmExFi2G35bp99t.
Screenshots of the state before: `/mnt/project-files/webui-ripensata/oggi/` (project files, not in the repo).

## 1. Today (verified on the cloud bench, 2026-11-27)

- Sidebar (`layout/shell.component.ts`): 77 entries with every section open; sections General, Pinned, Conversations,
  Dashboards, Modules (every sub-page is an entry), System (30 entries). The owner's own pages (Email, Your week,
  Notifications, Memory, Thoughts) sit in «System» next to Map, Performance, Machines, Download.
- Duplicated or vague labels: three «Statistics», two «Routine», «Houses» (Scout) and «Home» (Lares), «Documents» and
  «Documents created».
- Four ways to talk to the assistant on Home (Chat, Talk and «Write here» in the Home header, the bubble).
- Settings → System lists the internal module names (Aphrodite, Argus…); themes are called «Claude light/dark»; the
  default look is the Claude one (terracotta on cream, serif titles, diamond logo).
- Module pages each draw their own header; empty states are one grey line; some pages show text for developers
  (Thoughts: score formula, «threshold 0.55», «Settings → System → Athena»).
- Ctrl+K finds actions, pages and settings, never the owner's data.
- The mascot does not react to what the owner does on the pages; clicking it only cheers.

## 2. Goal

A WebUI where the owner always knows where things are, with its own look, pages that all work the same way, one box
that finds anything (and asks the assistant on the fly), and a mascot that brings back the conversation and reacts to
what he does.

## 3. Scope and design — four pieces, merged one at a time

### Piece 1 — navigation and look

1. **Place of a page** (contract, `hestia_common.plugin_client.page(place=…)`): `space` (default for domain modules),
   `agenda`, `assistant`, `notifications`, `system` (default for core modules). The WebUI builds every list from it;
   a new module finds its place by itself.
2. **Icon rail** (always visible): logo, Today, Chat, Agenda, Spaces, the assistant (named with the chosen name),
   the pages the owner pins, then Search, Notifications (with count), Settings, the assistant's state dot.
3. **Context panel** next to the rail, resizable and closable (kept per browser): it lists what fits where you are —
   the spaces (one entry each, never sub-pages), the conversations (Chat: new, pinned, recent, all), the Agenda pages,
   the assistant's pages, the notification pages, Settings + the system pages. Closed = rail only.
4. **Sub-pages are tabs** at the top of the page (shell, one component for every module), not sidebar entries.
   Old addresses keep working.
5. **Phone**: the rail becomes a bottom bar Today · Chat · Agenda · Spaces · More; the panel opens as a sheet.
6. **Look**: new theme pair «Aurora» (teal/blue, light and dark) is the default, with the «Glass» style by default;
   Claude themes renamed («Terracotta»); new logo = the hearth ring (circle + fire in the middle) in the theme colours,
   also favicon/app icon. The logo never depends on the mascot.
7. **Home cleanup**: no second «System status» tab and no Talk / «Write here» buttons in the header (one door: the
   bubble, later the mascot); Discover reachable from the Today panel and from Search.
8. **No module names** in Settings → System (people's names from `module_label`) and in Search («Make Athena
   think» → «Think now»).
9. Labels: Scout's page «House hunting», Lares «Home»; Calliope «Documents»; Oracle documents «Shared files» (they are the files the owner gives the assistant, in its place).

### Piece 2 — one page pattern

Shared kit components (WebUI `ui/` + SDK `kit/`): page header (title, one line of context, one primary action and «Ask»;
page settings stay on the shell's gear (v1.2)), summary-first layout, empty state (icon, sentence, start button, «or say it in chat»
with an example). Applied to every module page; developer text removed (Thoughts formula/threshold etc.); governance
check for module names in people texts.

### Piece 3 — «Search everything» and «Ask on the fly»

- One box (Ctrl+K or `/` from any page): actions, pages, settings, conversations (message text), memories, people,
  deadlines, workouts, expenses, clothes, documents, email; quick maths and dates.
- Contract: a module declares a search provider (`hestia_common` plugin contribution `search`, GET under its
  api_prefix `?q=` → items `{title, hint, icon, link}`); the WebUI backend asks all providers through Hub in parallel
  with a short timeout and streams results; a slow module never blocks the others.
- Tab (or a leading «?») = ask: short answer under the box via Oracle `/api/llm/chat` (fast profile), tools allowed,
  one «Quick questions» conversation; «Continue in chat» opens it.

### Piece 4 — mascot link (site side; characters stay in the mascot thread)

- Clicking the mascot opens a mini chat with the current or last conversation next to it («Open» = full page); holding
  it starts Talk. The mascot replaces the bottom-right bubble (one door).
- Page events contract: the SDK host gets `host.event(kind, data)`; pages emit `mood_logged`, `workout_done`,
  `deadline_done`, `budget_over`… Rules (no LLM) map an event to a reaction; the mascot side consumes
  `react(kind, text?, action?)` so the characters play a pose without the site knowing the sprites (agreed with the
  mascot thread, 2026-11-27).

## 4. New feature checklist (`docs/MARKO-RULES.md`)
1. Real job for the owner: find things, see what matters, ask fast.
2. Owner module (R1): WebUI (client) + each module declares its page place / search provider / events.
3. Configuration: no new Themis setting; panel open/width and pins are per-browser/WebUI layout prefs (existing
   `webui.sidebar.*`), not feature switches.
4. Push or poll: navigation is static; search asks on demand; events are pushed by pages.
5. Who confirms: nothing automatic; Ask on the fly runs tools the chat already allows.
6. WebUI: stroke icons with tones, no emoji. Telegram: unchanged (search and quick ask exist there as chat).
7. Stop, correct, undo: panel/pins changed by the owner; old URLs redirect.
8. Docs: DESIGN-SYSTEM.md, `Hestia-WebUI/hestia-webui.md`, SDK docs (`page(place)`, search, events), swagger when
   endpoints change, ARCHITECTURE rule on page places.
9. Texts: English + `tr`, Italian (and other) catalogs in `hestia_common/locales/*/messages.json`.

## 5. Acceptance criteria

- Piece 1: rail + panel on desktop, bottom bar on phone; no sub-page in any list; Email, Week, Notifications,
  Memory, Thoughts no longer under System; Aurora default with the ring logo; no «Claude» theme name; no module name
  in Settings → System; `ng build` with no warnings; screenshots on the bench (desktop light/dark, phone).
- Piece 2: every module page uses the shared header and empty state; no developer text left.
- Piece 3: typing «panca» finds the exercise, the workouts, the chat message and the memory; Tab gives a short answer.
- Piece 4: click on the mascot opens the last conversation; logging mood «down» makes the mascot react with a bubble.
