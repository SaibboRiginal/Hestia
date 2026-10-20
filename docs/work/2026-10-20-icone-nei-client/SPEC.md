# Icons instead of emoji in the clients

| | |
|---|---|
| **Version** | 1.0 |
| **Source** | user via Project thread (Marko 2026-10-20: «possiamo rimuovere emoji in generale e usare le stesse icone minimaliste tipo quelle del sito web? questo è per i clients … colorato che si capisce l'intenzione al volo … Telegram penso non abbiamo alternative») |
| **Status** | Implementing |

## Goal
What a client draws uses the same minimal stroke icons as the WebUI (`<hx-icon>` / `<hxk-icon>`), coloured by
intent (success, warning, danger, info, accent), never emoji. Telegram keeps emoji: it has no icons.

## Scope
1. **WebUI app** (`Hestia-WebUI/frontend`): every emoji in templates and copy → `<hx-icon>` with a tone colour.
2. **Module plugins** (`Hestia-*/ui/src`, ~120 emoji in 27 files): emoji → `<hxk-icon>` with tone colour; missing icons
   added to both icon sets (WebUI `icon.component.ts` and SDK `kit/basics.ts`, same names and paths).
3. **Data that carries an emoji** and is drawn by the WebUI:
   - Presence states (Chronos `chronos.presence.states`): new field `icon` (icon name) + `tone`; the WebUI draws the icon,
     Telegram keeps `emoji`. Built-in states get both.
   - Hermes notices in the WebUI: icon and colour from `_level` (info/success/warning/error); a leading emoji in the
     text is not shown in the WebUI (Telegram unchanged).
   - Chat cards already carry `icon`; `emoji` is no longer drawn.
4. Docs: `DESIGN-SYSTEM.md` rule «no emoji in the WebUI and plugins: icons with a tone»; module md where a field is added.

## Out of scope
- Telegram texts and buttons (emoji stay).
- Model answers in chat (free text the model writes).

## Acceptance criteria
1. No emoji drawn by WebUI code or plugin code (a check script finds none in `frontend/src` and `Hestia-*/ui/src`).
2. Presence badge, chat strip, notices and plugin pages show coloured icons.
3. Telegram unchanged.
4. Frontend and plugin builds pass; module tests green.

## Design decisions
- One icon vocabulary shared by WebUI and SDK (same names), so modules and the shell look the same.
- Intent = colour token (`--success`, `--warning`, `--danger`, `--accent`, `--text-2`), not a different glyph per mood.
- Data keeps `emoji` for Telegram and gains `icon`: each client draws what it can.
