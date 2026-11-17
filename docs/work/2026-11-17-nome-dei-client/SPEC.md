# SPEC — The clients are called with the name the owner chose

| | |
|---|---|
| **Version** | 1.0 |
| **Source** | user via external chat (thread «Hestia viva», Marko 2026-11-17: «sarebbe bello che il nome diventasse qualcosa di globale anche per i client che si adattino per chiamarsi come vuole l'utente e tutte le "variabili" che abbiamo messo che possono cambiare») |
| **Status** | Implemented |

Follows `docs/work/2026-11-16-nome-ovunque` (texts that speak of her as a person) and
`docs/work/2026-11-14-backend-inglese` v2.0 (English source, Italian catalog).

## 1. Today (main be81e0d)

- The site called itself «Hestia»: tab title, installed app (static manifest), login, sidebar, setup brand,
  command palette, route titles «… · Hestia».
- The Telegram bot kept the name given in BotFather and described itself as «Your personal assistant» in Italian only.
- Push notifications without a title, monitor messages («Hestia Monitor»), the Google sign-in page and several
  pages and helps still said «Hestia» (some came back with the English rewrite of PR #113).
- Greetings did not use the owner's name.

## 2. Goal and scope

1. Every client calls itself with the chosen name: WebUI (tab, installed app, login, sidebar, setup, palette,
   route titles), Telegram (bot name `setMyName`, description and short description in «Lingua», menu button),
   web push, Argus monitor messages, Hecate Google page, Hermes inbox fallback, Themis proposer.
2. The other personal variables follow too: she/he (Italian agreement `{g:…|…}` in the catalog), the language
   (bot description and commands are set again when «Lingua» changes), the owner's name (greetings: chat page
   «Buongiorno, Marko», Telegram «Ciao, Marko»).
3. «Hestia» stays only for the software itself: releases and updates, installer and git folder, the
   transfer/backup file format, technical module names (`Hestia-MCP`), the Google app name in Google's own
   permission page, hidden text for the model.

## 3. Design

- WebUI: `assistantName()` from the catalog (already loaded before the bundle) for route titles and the brand;
  `i18n.js` sets `document.title`; `GET /api/webui/manifest.webmanifest` (public, no-store) writes the manifest
  from the catalog (the static `manifest.webmanifest` is gone). `IdentityService.assistant` starts from the catalog.
- Telegram: `set_bot_identity()` renames the bot only when the name differs (Telegram limits renames) and sets
  the descriptions without a language code (one owner, «Lingua»); `on_personal_change` runs the whole profile
  again when name, she/he or language change.
- Owner's name stays out of the public catalog: the WebUI reads it from the settings (authenticated).

## 4. Acceptance criteria

- Name «Leo»: tab «Chat · Leo», installed app «Leo», login «Leo», Telegram bot «Leo» with «Sono Leo, il tuo
  assistente personale…», monitor «Monitor di Leo», push without title «Leo».
- He: «scarica da solo», «per tutto Leo». Owner «Marko»: «Buongiorno, Marko», Telegram «Ciao, Marko».

## 5. New-feature checklist

- No new setting or env var. One public WebUI endpoint (swagger), no personal data in it besides the assistant's name.
- Logs `event=…`, fallbacks `[🔄]`. Texts English source with the Italian catalog entry.
