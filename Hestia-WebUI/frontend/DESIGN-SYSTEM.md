# Hestia WebUI — Design system & module guide

Rules for humans and AI models adding UI to Hestia. Angular 19, standalone components, signals,
new control flow (`@if`, `@for`, `@switch`). Style = Claude (warm neutrals, serif headings, one accent).

## 1. Golden rules

1. **Never hardcode a color, font or radius.** Use theme tokens: `var(--surface)`, `var(--text-2)`, `var(--accent)`…
2. **Use the kit before writing CSS.** Buttons, inputs, modals, popovers, menus, toasts, badges, empty states
   already exist (`src/app/ui`). New generic widget → add it to the kit (+ this file), not inside a feature.
3. One feature = one folder `src/app/features/<name>/` + one line in `src/app/app.modules.ts`.
4. Data comes from the WebUI backend (`/api/webui/...`), which talks to services **only via Hub**.
5. Italian UI copy, short and concrete. Icons from `<hx-icon>`, **never emoji** (also not ★ ✓ ⚠): a stroke icon
   coloured by intent with `tone` (success · warning · danger · info · accent · muted). Telegram keeps emoji (no icons
   there); data meant for both carries `emoji` for Telegram and `icon` + `tone` for the WebUI. Checked by
   `tools/governance/check_icons.py`. Times always 24h (`fmt.time`).
6. Must work at 390 px (phone) and in light + dark themes. Check both.
7. `npx ng build` must pass with **no warnings** before committing.
8. No build-time network: web fonts are a `<link>` in `index.html` and `fonts.inline=false` in
   `angular.json` (the Docker build cannot reach Google Fonts). Never `@import url(https://…)` in SCSS.

## 2. Tokens (defined per theme in `src/app/core/theme/themes.ts`)

| Token | Use |
|---|---|
| `--bg` / `--bg-subtle` | page background / sidebars |
| `--surface`, `--surface-2`, `--surface-3` | cards & popovers / hover & inputs / pressed & selected |
| `--border`, `--border-strong` | dividers / control borders |
| `--text`, `--text-2`, `--text-3` | primary / secondary / muted text |
| `--accent`, `--accent-hover`, `--accent-contrast`, `--accent-soft` | main action, its hover, text on accent, tinted background |
| `--accent-2` | second accent of a graphic profile (birthday, holidays; set by `ThemeService.setPalette`, may be unset: use `var(--accent-2, var(--accent))`). The profile overrides the accents only, never surfaces or text |
| `--danger|success|warning|info` (+ `-soft`) | semantic states |
| `--focus-ring`, `--overlay`, `--shadow-1..3` | focus outline, modal backdrop, elevation |
| `--user-bubble`, `--user-bubble-text` | chat user message |
| `--cal-1..8` | categorical palette (calendar owners, charts) |
| `--font-sans`, `--font-serif`, `--font-mono`, `--font-chat` | UI / headings / code / assistant replies |
| `--radius-xs..xl`, `--radius-full` | corner radii |
| `--dur-fast`, `--dur`, `--ease` | motion |

**New theme** = copy an entry of `THEMES` in `themes.ts`, change values and `id`. It appears in
Impostazioni automatically. `ThemeService.set(id)` / `toggleMode()`; `'auto'` follows the OS.
Tip for tints: `color-mix(in srgb, var(--c) 15%, transparent)`.

## 3. Kit (`import { ... } from '../../ui'` or `imports: [...UI]`)

| Component | Usage |
|---|---|
| `<hx-icon name size stroke tone>` | stroke icons; list in `icon.component.ts`. Add an icon to it **and** to the SDK `kit/basics.ts` (same name and path). Every icon a plugin names in its manifest (pages, widgets, quick actions) must be here, or the sidebar shows «info» — `python tools/cloud_test.py flows plugins` checks it |
| `<button hx-btn variant size icon iconRight iconOnly block loading>` | variants `primary · secondary · ghost · subtle · danger`; sizes `sm · md · lg` |
| `.hx-input`, `.hx-select`, `.hx-textarea`, `.hx-check` (+ `.mono`) | global form classes |
| `<hx-field label hint error required>` | label/hint/error wrapper around a control |
| `<hx-toggle [(checked)] label (changed)>` | switch |
| `<hx-date [(value)]>` · `<hx-time [(value)]>` · `<hx-datetime [(value)]>` | Italian date `gg/mm/aaaa` (+ picker) and **24h** time; values `YYYY-MM-DD`, `HH:mm`, `YYYY-MM-DDTHH:mm`. Never use native `datetime-local` / `time` (AM/PM on en-US OS) |
| `<hx-segmented [options] [(value)] (changed)>` | segmented control (`{value,label,icon,title}`) |
| `<hx-badge tone dot color>` | tones `neutral · accent · success · danger · warning · info` |
| `<hx-spinner size>` / `<hx-empty icon title>` | loading / empty state |
| `<hx-page-header title subtitle>` + projected actions | page top bar |
| `<hx-modal [open] title size (closed)>` + `[footer]` slot | dialog (`sm·md·lg·xl`), ESC/backdrop close |
| `<hx-popover [open] [anchor]=rect width (closed)>` | floating panel next to an element rect, auto-flip |
| `<hx-menu [items] (select)>` + `[trigger]` slot | dropdown (`{id,label,icon,danger,divider}`) |
| `<hx-diff [diff] [only] [truncated]>` | unified `git diff` viewer: per-file collapsible (big files start closed), *Unificato / Affiancato* (remembered), `parseDiff()` exported |
| `<hx-markdown [text]>` | GitHub-flavoured markdown (tables, task lists) with theme styles, sanitized |
| `<hx-resize [(width)] edge [min] [max] [def] key [inline]>` + `savedWidth(key, def)` | drag handle for a side panel: drag, ←/→, double-click = default, clamped to 90vw, width per browser; `inline` for panels that scroll (sits in the flex row) |
| `ToastService.show/success/error(text, tone, action?)` | snackbar (action = undo) |
| `DialogService.confirm(title,msg,label,danger)` / `.choose(title,msg,options)` | awaitable dialogs |

System notices: `<div class="hx-notices [rich]"><div class="hx-notice" data-level="info|success|warning|error"><hx-icon/>
<span class="nt">title</span><span class="nd">detail</span></div></div>` — never style a system message like chat text.
Visibility/style prefs: `NoticePrefsService` (`services/notice-prefs.service.ts`).

Layout helpers: `.hx-row`, `.hx-col`, `.hx-grow`, `.hx-card`, `.hx-muted`, `.hx-small`, `.hx-truncate`,
`.hx-prose` (rendered assistant HTML), `.hx-fade-in`.

## 4. Add a module (example: "Notes")

```ts
// 1) src/app/features/notes/notes-page.component.ts
@Component({
  selector: 'app-notes-page',
  imports: [...UI],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <hx-page-header title="Note" subtitle="…"><button hx-btn variant="primary" icon="plus">Nuova</button></hx-page-header>
    <div class="body">…</div>`,
  styles: [`:host { display:flex; flex-direction:column; flex:1; min-height:0; } .body { flex:1; overflow:auto; padding:18px 24px; }`],
})
export class NotesPageComponent {}

// 2) src/app/app.modules.ts → APP_MODULES
{ path: 'notes', label: 'Note', icon: 'file', load: () => import('./features/notes/notes-page.component').then(m => m.NotesPageComponent) },
```

3. Backend: add `Hestia-WebUI/app/Controllers/NotesController.cs` that proxies to the owning service via
   `HubClient` (see `AgendaController.cs`, the ICS feed). The token middleware already protects `/api/webui/*`.
4. State: a `@Injectable({providedIn:'root'})` store with signals (see `services/notifications.service.ts`),
   API calls in a small `*.api.ts` service; errors → `ToastService`.
5. Document the module in `Hestia-WebUI/hestia-webui.md` and follow the work protocol (`CLAUDE.md`).

## 5. Patterns

- **Pages**: `:host { display:flex; flex-direction:column; flex:1; min-height:0 }`; scroll inside a `.body`.
- **Phone**: the shell shows a burger at top-left (56 px). Give page headers `padding-left: 56px` below 861 px.
- **Lists**: hover `var(--surface-2)`, selected `var(--accent-soft)` + `color: var(--accent)`.
- **Destructive actions**: `DialogService.confirm(..., danger=true)` and, when possible, a toast with "Annulla".
- **Loading**: `<hx-spinner>` inline; never block the whole page.
- **Keyboard**: page-level shortcuts via `@HostListener('document:keydown')`, ignore when focus is in inputs.
  Global: **Ctrl/⌘+J** = "Crea con Hestia" (shell).
- **"Crea con Hestia" entry point**: any page that creates or changes things offers a ghost button with the
  `sparkle` icon (accent color) labelled *Chiedi a Hestia* / *Crea con Hestia…* that calls
  `AssistantService.open({page, intent, label, hints, suggestions, prompt})`. `label` is the chip the user sees
  (short, human); `hints` are compact key/values for Oracle (ids, keys, dates — no prose, every token is paid).
  Reload page data on `AssistantService.changed$` (agenda / Forge / action notices).
- **Side panels are resizable** (the owner likes it): every side column/drawer gets `<hx-resize>` with a `key`
  (shell sidebar, Crea con Hestia, Sviluppo list + context panel, Calendario filters, Impostazioni → Sistema modules).
- **Random ids**: `uid()` from `core/uid.ts` (`crypto.randomUUID` is missing on plain-http LAN addresses).

## 6. Calendar module (reference implementation)

Since 2026-10-19 the Agenda is Chronos's plugin page (`/p/chronos/agenda`, `/calendar` redirects), written with
the plugin SDK (§7): `Hestia-Chronos/ui/src/agenda.ts` (page: layout, actions, dialogs) and
`ui/src/cal/`: `store.ts` (state, ranges, filters), `api.ts` (Chronos `/api/agenda*` through `host.api`), `views/timegrid.ts` (week/day: windows as bands,
overlap columns, pointer drag/resize with 15-min snap), `views/month.ts`, `views/list.ts`, `mini.ts`, `details.ts`
(popover), `editor.ts` (modal, RRULE builder), `wizard.ts` (module templates). Only the ICS feed stays in the
WebUI (`AgendaController`). Sources/layers: `CalendarSource` (`kind: 'ai' | 'external'`) — external calendars plug in there.

## 6b. Assistant drawer

`features/assistant/assistant-drawer.component.ts` (`<hx-assistant>`, lazy via `@defer` in the shell) +
`services/assistant.service.ts`. Own `ChatService` instance (`providers`, channel `assistant`): the chat code and
packets are shared with the Chat page, the conversation and the Oracle session are not.
Resizable from its left edge (`<hx-resize key="assistant">`, 340px–90vw, default 440px); full screen on phones.

## 7. Sviluppo module

Since 2026-10-19 Sviluppo is Hephaestus' plugin page (`Hestia-Hephaestus/ui/src/sviluppo.ts` + `ui/src/forge/`:
store, api, transcript, task panel, repo browser + graph), built with the plugin kit (`hxk-*`) and the same tokens.
The WebUI route `/forge` only redirects to `/p/hephaestus/sviluppo`.

## 8. Central settings (`features/settings/`)

Any page can show a Hestia setting (Themis) with `<hx-setting [item]>` (full row: label, help, state badges,
history/undo) or just `<hx-setting-control [item] [compact] (commit)>` (the input), wired to
`CentralSettingsStore.set(item, value)`. Never build a custom form for a module setting: declare it in the module
(`hestia_common.settings_client.setting`, optional `row`/`column` for a table) and it appears in Impostazioni → Sistema.
A setting that lives only in this client uses `<hx-setting-shell label help [wide]>` around its control, so every
row of Impostazioni looks the same and the page search finds it (add it to `personal-settings.component.ts`).

## 9. Client plugins (`features/plugins/`, contract in `docs/work/2026-10-17-client-plugins/SPEC.md` §4)

Module UI is **not** written in this Angular app. A module ships Web Components (Lit) built with
`Hestia-Shared/webui-sdk` (`node build.mjs plugin src/index.ts ui/dist/webui/index.js`) and declares them with
`hestia_common.plugin_client`; the WebUI loads them from the Hub catalog at runtime.

- Element names `<module>-…`; extend `HestiaElement`; no emoji: `<hxk-icon name tone>` (same names as `hx-icon`); use the `hxk-*` kit (icon, button, badge, card, stat, state,
  list, chart, field, image-picker, quicklog). It reads the same CSS tokens, so plugins follow the theme. `hx-*` stays
  the Angular kit.
- Call only your module: `this.host.api('GET', '/api/ui/...')`. Navigate with `host.navigate(page, params)`;
  feedback with `host.toast`, `host.confirm`; keep offline data in `host.store(name)`; react to `host.on('refresh'|'online'|…)`.
- Widgets get a padded body (12 px) and `ctx.size` (`s|m|l|xl` = 1×1, 2×1, 2×2, 4×2 cells of 170 px); content must
  fit or scroll inside. On phone every widget is one column and one row tall (min 150 px, grows with content).
  The frame already draws the widget title and a chevron to its page: the widget body never repeats them. In a
  flex column filling the cell, keep the key line (`.big`, title) from shrinking (`flex-shrink: 0`), or `truncate` hides it whole.
- Quick actions are declared, not drawn: the Home strip, the Ctrl/⌘+K palette and `<hxk-quicklog>` render them.
- In Angular, show a plugin element with `<hx-plugin-outlet [module] [element] [ctx]>` (loading/offline/error states built in).
- Sidebar (`layout/shell.component.ts`): fixed top (logo, Crea con Hestia) and bottom (Impostazioni, Esci, state),
  **one scroll area** in between with sections *Fissati · Generale · Dashboard · Moduli · Sistema* (core modules =
  manifest `kind: "core"`). Section headers collapse (`webui.sidebar.collapsed`); the pin on hover moves an entry to
  *Fissati* (`webui.sidebar.pinned`, ids `app.<path>` · `dash.<id>` · `<module>.<page>`), drag to reorder there. The
  list is computed, so a pinned entry leaves its section (never shown twice); a pinned parent brings its sub-pages.
  A page with `badge: {source, field}` shows that number (read through the plugin call proxy with the catalog poll).

