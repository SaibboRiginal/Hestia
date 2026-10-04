# Hestia WebUI — Design system & module guide

Rules for humans and AI models adding UI to Hestia. Angular 19, standalone components, signals,
new control flow (`@if`, `@for`, `@switch`). Style = Claude (warm neutrals, serif headings, one accent).

## 1. Golden rules

1. **Never hardcode a color, font or radius.** Use theme tokens: `var(--surface)`, `var(--text-2)`, `var(--accent)`…
2. **Use the kit before writing CSS.** Buttons, inputs, modals, popovers, menus, toasts, badges, empty states
   already exist (`src/app/ui`). New generic widget → add it to the kit (+ this file), not inside a feature.
3. One feature = one folder `src/app/features/<name>/` + one line in `src/app/app.modules.ts`.
4. Data comes from the WebUI backend (`/api/webui/...`), which talks to services **only via Hub**.
5. Italian UI copy, short and concrete. Icons from `<hx-icon>`.
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
| `<hx-icon name size stroke>` | stroke icons; list in `icon.component.ts` (add paths there) |
| `<button hx-btn variant size icon iconRight iconOnly block loading>` | variants `primary · secondary · ghost · subtle · danger`; sizes `sm · md · lg` |
| `.hx-input`, `.hx-select`, `.hx-textarea`, `.hx-check` (+ `.mono`) | global form classes |
| `<hx-field label hint error required>` | label/hint/error wrapper around a control |
| `<hx-toggle [(checked)] label (changed)>` | switch |
| `<hx-segmented [options] [(value)] (changed)>` | segmented control (`{value,label,icon,title}`) |
| `<hx-badge tone dot color>` | tones `neutral · accent · success · danger · warning · info` |
| `<hx-spinner size>` / `<hx-empty icon title>` | loading / empty state |
| `<hx-page-header title subtitle>` + projected actions | page top bar |
| `<hx-modal [open] title size (closed)>` + `[footer]` slot | dialog (`sm·md·lg·xl`), ESC/backdrop close |
| `<hx-popover [open] [anchor]=rect width (closed)>` | floating panel next to an element rect, auto-flip |
| `<hx-menu [items] (select)>` + `[trigger]` slot | dropdown (`{id,label,icon,danger,divider}`) |
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
   `HubClient` (see `AgendaController.cs`). The token middleware already protects `/api/webui/*`.
4. State: a `@Injectable({providedIn:'root'})` store with signals (see `features/calendar/calendar.store.ts`),
   API calls in a small `*.api.ts` service; errors → `ToastService`.
5. Document the module in `Hestia-WebUI/hestia-webui.md` and follow the work protocol (`CLAUDE.md`).

## 5. Patterns

- **Pages**: `:host { display:flex; flex-direction:column; flex:1; min-height:0 }`; scroll inside a `.body`.
- **Phone**: the shell shows a burger at top-left (56 px). Give page headers `padding-left: 56px` below 861 px.
- **Lists**: hover `var(--surface-2)`, selected `var(--accent-soft)` + `color: var(--accent)`.
- **Destructive actions**: `DialogService.confirm(..., danger=true)` and, when possible, a toast with "Annulla".
- **Loading**: `<hx-spinner>` inline; never block the whole page.
- **Keyboard**: page-level shortcuts via `@HostListener('document:keydown')`, ignore when focus is in inputs.

## 6. Calendar module (reference implementation)

`features/calendar/`: `calendar.store.ts` (state, ranges, filters, actions), `agenda.api.ts`
(`/api/webui/agenda/*` → Chronos), views `time-grid` (week/day: windows as bands, overlap columns, pointer
drag/resize with 15-min snap), `month-view` (window bars, chips grouped ×N, HTML5 drag between days),
`list-view`, `mini-calendar`, `event-details` (popover), `event-editor` (modal, RRULE builder).
Sources/layers: `CalendarSource` (`kind: 'ai' | 'external'`) — external calendars plug in there.
