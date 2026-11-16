/**
 * <chronos-agenda> — "Agenda di Hestia": the assistant's own calendar (month / week / day / list), sidebar with mini
 * calendar, layers and filters, popover details, editor, drag & drop, quick add in words, "Da un modulo…", module
 * logs around an occurrence, ICS file. Keys: T oggi · M/W/D/L viste · N nuovo · ←/→. Ported from the WebUI's
 * built-in calendar page (SPEC docs/work/2026-10-18-moduli-core-e-mcp-esterno P6); state in cal/store.ts.
 */
import { HestiaElement, css, html, nothing, tr } from '@hestia/webui-sdk';
import { CalStore } from './cal/store';
import type { LogsResult } from './cal/api';
import { type AgendaType, type CalEvent, type CalView, type MoveRequest, type SelectRequest, TYPE_META, ownerLabel } from './cal/models';
import { addDays, addMinutes, dayKey, fmt, startOfWeek } from './cal/date';
import { loadPrefs } from './cal/prefs';
import { type MenuItem, calStyles, ic, segmented, toggle } from './cal/ui';
import type { DetailAction } from './cal/details';
import type { EditorAsk, EditorResult, EditorSeed } from './cal/editor';
import type { TemplateCreate } from './cal/wizard';

const TYPES: AgendaType[] = ['event', 'task', 'job', 'window'];
const VIEWS: { value: CalView; label: string; title: string }[] = [
  { value: 'day', label: tr('Day'), title: tr('Day (D)') }, { value: 'week', label: tr('Week'), title: tr('Week (W)') },
  { value: 'month', label: tr('Month'), title: tr('Month (M)') }, { value: 'list', label: tr('List'), title: tr('List (L)') },
];
const NEW_MENU: MenuItem[] = [
  { id: 'free', label: tr('Free event'), icon: 'edit' }, { id: 'module', label: tr('From a module…'), icon: 'zap' },
  { id: 'ai', label: tr('Create with {assistant}…'), icon: 'sparkle' }, { id: 'd', label: '', divider: true },
  { id: 'ics', label: tr('Agenda on the phone (ICS)…'), icon: 'external' },
];
type NumKey = 'frequentPerDay' | 'frequentDays' | 'rareCount' | 'rareDays' | 'pastDays' | 'scrollHour' | 'workStart' | 'workEnd';
interface LogsState { title: string; when: string; at: string; service: string; services: string[]; minutes: number;
                      loading: boolean; result: LogsResult | null; error: string; }

export class ChronosAgenda extends HestiaElement {
  static properties = {
    ...HestiaElement.properties, tick: { state: true }, sideOpen: { state: true }, sel: { state: true }, selRect: { state: true },
    editor: { state: true }, wizard: { state: true }, vistaRect: { state: true }, quick: { state: true }, quickBusy: { state: true },
    logs: { state: true }, icsOpen: { state: true }, moveAsk: { state: true },
  };
  declare tick: number; declare sideOpen: boolean; declare sel: CalEvent | null; declare selRect: DOMRect | null;
  declare editor: EditorSeed | null; declare wizard: Date | null; declare vistaRect: DOMRect | null;
  declare quick: string; declare quickBusy: boolean; declare logs: LogsState | null; declare icsOpen: boolean;
  declare moveAsk: MoveRequest | null;
  private store!: CalStore;
  private logsSeq = 0;

  static styles = [...HestiaElement.styles, calStyles, css`
    :host { display: flex; flex: 1; min-height: 0; height: 100%; }
    .cal { display: flex; flex: 1; min-height: 0; width: 100%; }
    .side { width: var(--side-w, 256px); flex-shrink: 0; border-right: 1px solid var(--border); padding: 14px 12px; overflow-y: auto;
      display: flex; flex-direction: column; gap: 16px; background: var(--bg); box-sizing: border-box; }
    .new-wrap { display: flex; align-self: flex-start; }
    .new { display: inline-flex; align-items: center; gap: 6px; height: 40px; padding: 0 18px; background: var(--accent); color: var(--accent-contrast);
      border-radius: var(--radius-lg) 0 0 var(--radius-lg); font-weight: 500; box-shadow: var(--shadow-1); }
    .new-more { height: 40px; width: 34px; display: grid; place-items: center; background: var(--accent); color: var(--accent-contrast);
      border-radius: 0 var(--radius-lg) var(--radius-lg) 0; border-left: 1px solid color-mix(in srgb, var(--accent-contrast) 25%, transparent); }
    .quick { display: flex; align-items: center; position: relative; margin: -4px 0 0; }
    .quick .ic, .quick hxk-icon { position: absolute; left: 9px; color: var(--accent); pointer-events: none; }
    .quick input { width: 100%; height: 32px; padding: 0 10px 0 30px; font: inherit; font-size: 12.5px; color: var(--text); background: var(--surface-2);
      border: 1px solid var(--border-strong); border-radius: var(--radius-sm); outline: none; box-sizing: border-box; }
    .quick input:focus { border-color: var(--accent); box-shadow: 0 0 0 3px var(--focus-ring); }
    section h4 { font-size: 11.5px; text-transform: uppercase; letter-spacing: .05em; color: var(--text-3); font-weight: 600; margin: 0 0 6px 4px; }
    .flt { display: flex; align-items: center; gap: 8px; padding: 4px 6px; border-radius: var(--radius-sm); font-size: 13.5px; cursor: pointer; user-select: none; }
    .flt:hover { background: var(--surface-2); }
    .flt .nm { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .sw { width: 10px; height: 10px; border-radius: 3px; flex-shrink: 0; }
    .sw.ai { background: linear-gradient(135deg, var(--cal-1), var(--cal-2)); }
    .cnt { font-size: 11.5px; color: var(--text-3); }
    .hint { font-size: 12px; color: var(--text-3); padding: 2px 6px; margin: 0; }
    .opts { display: flex; flex-direction: column; gap: 10px; padding: 0 4px; }
    .main { flex: 1; min-width: 0; display: flex; flex-direction: column; }
    .bar { display: flex; align-items: center; gap: 8px; padding: 12px 16px; border-bottom: 1px solid var(--border); flex-wrap: wrap; }
    .bar h2 { font-family: var(--font-serif); font-weight: 500; font-size: 20px; white-space: nowrap; margin: 0; }
    .ib { padding: 6px; border-radius: var(--radius-sm); color: var(--text-2); line-height: 0; }
    .ib:hover { background: var(--surface-2); color: var(--text); }
    .grow { flex: 1; }
    .search { position: relative; width: 200px; }
    .search .ic, .search hxk-icon { position: absolute; left: 9px; top: 50%; transform: translateY(-50%); color: var(--text-3); }
    .search input { width: 100%; height: 32px; padding: 0 10px 0 30px; font: inherit; font-size: 13px; color: var(--text); background: var(--surface-2);
      border: 1px solid var(--border-strong); border-radius: var(--radius-sm); outline: none; box-sizing: border-box; }
    .side-btn { display: none; }
    .err { margin: 10px 16px 0; padding: 8px 12px; border-radius: var(--radius-md); background: var(--danger-soft); color: var(--danger);
      display: flex; align-items: center; gap: 8px; font-size: 13.5px; }
    .hint-bar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin: 8px 16px 0; padding: 6px 12px; font-size: 12.5px;
      color: var(--text-2); background: var(--bg-subtle, var(--surface-2)); border: 1px solid var(--border); border-radius: var(--radius-md); }
    .view { flex: 1; min-height: 0; display: flex; flex-direction: column; }
    .view > * { flex: 1; min-height: 0; }
    .scrim { display: none; }
    .vista { padding: 14px 16px; display: flex; flex-direction: column; gap: 12px; }
    .vista h4 { font-size: 14px; font-weight: 600; margin: 0; }
    .vista .lab { font-size: 12px; color: var(--text-2); font-weight: 500; display: flex; flex-direction: column; gap: 4px; }
    .vista .lab small { color: var(--text-3); font-weight: 400; }
    .num { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; font-size: 13px; color: var(--text-2); }
    .num input, .logs-bar select { width: 58px; height: 28px; padding: 2px 6px; text-align: center; font: inherit; color: var(--text);
      background: var(--surface-2); border: 1px solid var(--border-strong); border-radius: var(--radius-sm); }
    .rules { display: flex; flex-direction: column; gap: 8px; padding: 8px 10px; border-radius: var(--radius-md); background: var(--surface-2); }
    .rules p { font-size: 12px; color: var(--text-3); margin: 0; }
    .logs-bar { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; font-size: 13px; color: var(--text-2); flex-wrap: wrap; }
    .logs-bar select { width: auto; text-align: left; }
    .logs { font-family: var(--font-mono); font-size: 11.5px; max-height: 60vh; overflow: auto; border: 1px solid var(--border); border-radius: var(--radius-md); }
    .lr { display: grid; grid-template-columns: 62px 64px 1fr; gap: 8px; padding: 3px 8px; border-bottom: 1px solid var(--border); }
    .lr:last-child { border-bottom: 0; }
    .lr[data-l=WARNING] { background: color-mix(in srgb, var(--warning) 10%, transparent); }
    .lr[data-l=ERROR], .lr[data-l=CRITICAL] { background: var(--danger-soft); }
    .lts, .llv { color: var(--text-3); } .lm { white-space: pre-wrap; word-break: break-word; color: var(--text); }
    .muted { font-size: 13px; color: var(--text-3); } .bad { font-size: 13px; color: var(--danger); }
    .ics-p { font-size: 13.5px; color: var(--text-2); margin: 0 0 10px; line-height: 1.5; } .ics-p.small { font-size: 12.5px; color: var(--text-3); }
    @media (max-width: 1100px) {
      .side { position: fixed; z-index: 700; inset: 0 auto 0 0; transform: translateX(-100%); transition: transform .2s; box-shadow: var(--shadow-3); }
      .side.open { transform: none; }
      .side.open + .scrim { display: block; position: fixed; inset: 0; background: var(--overlay); z-index: 690; }
      .side-btn { display: inline-flex; } .search { width: 140px; }
    }
    @media (max-width: 720px) { .bar { padding: 10px; } .bar h2 { font-size: 16px; } .search { display: none; } }
  `];

  constructor() {
    super(); this.tick = 0; this.sideOpen = false; this.sel = null; this.selRect = null; this.editor = null; this.wizard = null;
    this.vistaRect = null; this.quick = ''; this.quickBusy = false; this.logs = null; this.icsOpen = false; this.moveAsk = null;
  }

  connectedCallback() {
    super.connectedCallback();
    this.store = new CalStore(this.host, () => this.tick++);
    const phone = window.matchMedia('(max-width: 720px)').matches;
    void loadPrefs(this.host).then(p => { this.store.applyPrefs(p, phone); return this.store.load(); });
    this.onHost('refresh', () => void this.store.load());
    document.addEventListener('keydown', this.onKey);
  }
  disconnectedCallback() { super.disconnectedCallback(); document.removeEventListener('keydown', this.onKey); }

  // ── keyboard ───────────────────────────────────────────────────────────
  private onKey = (e: KeyboardEvent) => {
    const t = e.composedPath()[0] as HTMLElement | undefined;
    if (e.ctrlKey || e.metaKey || e.altKey || (t && ['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName))) return;
    if (this.editor || this.wizard || this.logs || this.icsOpen || this.moveAsk || this.sel || this.vistaRect || !this.isConnected) return;
    const s = this.store;
    const map: Record<string, () => void> = {
      t: () => s.today(), m: () => s.setView('month'), w: () => s.setView('week'), d: () => s.setView('day'), l: () => s.setView('list'),
      n: () => this.newAt(this.defaultStart()), ArrowLeft: () => s.step(-1), ArrowRight: () => s.step(1),
    };
    const fn = map[e.key];
    if (fn) { e.preventDefault(); fn(); }
  };

  // ── helpers ────────────────────────────────────────────────────────────
  private defaultStart(): Date {
    const d = new Date(this.store.anchor), now = new Date();
    d.setHours(now.getHours() + 1, 0, 0, 0);
    return d;
  }
  private newAt(d: Date) { this.sel = null; this.editor = { start: d, end: addMinutes(d, 60), type: 'event' }; }
  private gridDays(): Date[] {
    const a = this.store.anchor;
    if (this.store.view === 'day') return [a];
    const s = startOfWeek(a);
    return Array.from({ length: 7 }, (_, i) => addDays(s, i));
  }
  private stepLabel(dir: 1 | -1) {
    const unit = { day: [tr('Previous day'), tr('Next day')], week: [tr('Previous week'), tr('Next week')],
                   month: [tr('Previous month'), tr('Next month')], list: [tr('30 days before'), tr('30 days later')] }[this.store.view];
    return unit[dir < 0 ? 0 : 1];
  }
  private num(key: NumKey, v: unknown) {
    const n = Math.round(Number(v));
    if (Number.isFinite(n) && n >= 0) this.store.setVp({ [key]: n });
  }
  private hints(o: Record<string, string | number | null | undefined>): Record<string, string | number> {
    return Object.fromEntries(Object.entries(o).filter(([, v]) => v !== undefined && v !== null && v !== '')) as Record<string, string | number>;
  }

  // ── "Crea con Hestia" ──────────────────────────────────────────────────
  private askCreate(at?: Date, prompt = '') {
    const d = at ?? this.store.anchor;
    this.sel = null;
    this.host.assistant({ label: tr("Agenda · {0}{1}", fmt.dayLong(d), at ? ', ' + fmt.time(at) : ''), prompt,
      hints: this.hints({ day: dayKey(d), time: at ? fmt.time(at) : undefined, view: this.store.view,
                          agenda: tr("{assistant}'s agenda (agenda_assistente_* tools)") }) });
  }
  private askAbout(ev: CalEvent) {
    const it = ev.item;
    this.host.assistant({ label: `“${ev.occ.title}” · ${fmt.dayLong(ev.start)} ${fmt.time(ev.start)}`,
      hints: this.hints({ entry: ev.occ.key, title: ev.occ.title, module: ev.occ.owner, type: ev.occ.type, occurrence: ev.occ.occurrence,
        rule: it?.recurrence, state: ev.occ.status,
        last_result: it?.last_result ? (it.last_result.ok ? 'ok' : 'failed: ' + (it.last_result.detail || '')) : undefined }),
      suggestions: ev.occ.recurring
        ? [tr('Explain to me what this rule does'), tr('Move only this occurrence by one hour'), tr('Change the frequency…'), tr('Why did it fail?')]
        : [tr('Explain to me what it does'), tr('Move it to tomorrow at the same time'), tr('Why did it fail?')] });
  }

  // ── quick add in words ─────────────────────────────────────────────────
  private async quickAdd() {
    const text = this.quick.trim();
    if (!text || this.quickBusy) return;
    this.quickBusy = true;
    try {
      const d = await this.store.api.parse(text);
      this.sel = null;
      this.editor = { start: new Date(d.start_at), end: d.end_at ? new Date(d.end_at) : null, type: d.type,
                      prefill: { title: d.title, description: d.description ?? undefined, recurrence: d.recurrence } };
    } catch (e: any) {
      this.host.toast(tr("I didn't understand the date ({0}): complete it yourself", e?.message || tr('error')), 'warning');
      const s = this.defaultStart();
      this.editor = { start: s, end: addMinutes(s, 60), type: 'event', prefill: { title: text } };
    } finally { this.quick = ''; this.quickBusy = false; }
  }

  // ── module logs around an occurrence ───────────────────────────────────
  private openLogs(ev: CalEvent) {
    const svc = (ev.item?.action?.service || ev.occ.owner || 'chronos').toLowerCase();
    const services = [...new Set([svc, 'chronos', 'hub'].filter(s => s && s !== 'user'))];
    const at = ev.occ.run?.at || ev.start.toISOString();
    this.logs = { title: ev.occ.title, when: fmt.dateTime(new Date(at)), at, service: services[0], services, minutes: 5,
                  loading: false, result: null, error: '' };
    void this.loadLogs({});
  }
  private async loadLogs(change: { service?: string; minutes?: number }) {
    if (!this.logs) return;
    const next = { ...this.logs, ...change, loading: true, error: '' }, seq = ++this.logsSeq;
    this.logs = next;
    try {
      const r = await this.store.api.logs(next.service, next.at, next.minutes);
      if (seq === this.logsSeq && this.logs) this.logs = { ...next, loading: false, result: r };
    } catch (e: any) {
      if (seq === this.logsSeq && this.logs) this.logs = { ...next, loading: false, result: null, error: e?.message || tr('Logs not available') };
    }
  }

  // ── ICS ────────────────────────────────────────────────────────────────
  private async downloadIcs() {
    try {
      const text = await this.store.api.ics();
      const a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob([text], { type: 'text/calendar' }));
      a.download = 'hestia-agenda.ics';
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    } catch (e: any) { this.host.toast(e?.message || tr('Download failed'), 'danger'); }
  }

  // ── events from views / popover / dialogs ──────────────────────────────
  private onNew(id: string) {
    if (id === 'module') { this.sel = null; this.wizard = this.defaultStart(); }
    else if (id === 'ai') this.askCreate();
    else if (id === 'ics') this.icsOpen = true;
    else this.newAt(this.defaultStart());
  }
  private select(r: SelectRequest) { this.selRect = r.rect; this.sel = r.ev; }
  private openDay(d: Date) { this.store.anchor = d; this.store.setView('day'); }
  private async onMove(m: MoveRequest) {
    if (m.ev.occ.recurring) { this.moveAsk = m; return; }
    await this.store.move(m.ev, m.start, m.end, 'one');
  }
  private async doMove(scope: 'one' | 'all') {
    const m = this.moveAsk; this.moveAsk = null;
    if (m) await this.store.move(m.ev, m.start, m.end, scope);
  }

  private async onAction(a: DetailAction) {
    const ev = this.sel; if (!ev) return;
    const s = this.store;
    this.sel = null;
    switch (a) {
      case 'edit': if (ev.item) this.editor = { start: ev.start, end: ev.end, item: ev.item }; break;
      case 'duplicate': if (ev.item) this.editor = { start: ev.start, end: ev.end, item: ev.item, duplicate: true }; break;
      case 'skip': await s.skip(ev); break;
      case 'unskip': await s.unskip(ev); break;
      case 'run': await s.run(ev); break;
      case 'pause': await s.pause(ev, true); break;
      case 'resume': await s.pause(ev, false); break;
      case 'restore': await s.update(ev.occ.key, { status: 'confirmed' }, tr('Rule restored')); break;
      case 'reset-move': await s.resetMove(ev); break;
      case 'ask': this.askAbout(ev); break;
      case 'logs': this.openLogs(ev); break;
      case 'cancel': {
        const ok = await this.host.confirm(ev.occ.recurring ? tr('Cancel the whole rule?') : tr('Cancel the item?'),
          ev.occ.recurring ? tr('No future occurrence will run. To skip just one use «Skip this».') : '',
          { label: tr('Cancel rule'), danger: true });
        if (ok) await s.cancel(ev);
        break;
      }
    }
  }
  private async onSave(r: EditorResult) {
    this.editor = null;
    if (r.key) await this.store.update(r.key, r.body, tr('Changes saved'));
    else await this.store.create(r.body);
  }
  private onAskFromEditor(a: EditorAsk) { this.editor = null; this.askCreate(a.start ?? undefined, a.title ? `${a.title} ` : ''); }
  private async onTemplate(r: TemplateCreate) { this.wizard = null; await this.store.createFromTemplate(r.tpl.owner, r.tpl.id, r.body); }

  // ── render ─────────────────────────────────────────────────────────────
  private renderSide() {
    const s = this.store;
    return html`<aside class="side ${this.sideOpen ? 'open' : ''}" style="--side-w:${s.sideW}px">
        <div class="new-wrap">
          <button class="new" title=${tr("New free event (N)")} @click=${() => this.newAt(this.defaultStart())}>${ic('plus', 16)} ${tr("New")}</button>
          <chronos-menu .items=${NEW_MENU} @select=${(e: CustomEvent) => { e.stopPropagation(); this.onNew(e.detail); }}>
            <button class="new-more" aria-label=${tr("Other ways to create")}>${ic('chevron-down', 16)}</button></chronos-menu>
        </div>
        <div class="quick" title=${tr("Write in words, e.g. \"tomorrow at 3pm dentist\" or \"every Monday at 9 check the houses\": the editor opens already filled in")}>
          ${this.quickBusy ? html`<hxk-icon name="refresh" size="14"></hxk-icon>` : ic('sparkle', 15)}
          <input placeholder=${tr("Quick add: tomorrow at 3pm…")} .value=${this.quick} ?disabled=${this.quickBusy}
            @input=${(e: any) => (this.quick = e.target.value)} @keydown=${(e: KeyboardEvent) => { if (e.key === 'Enter') void this.quickAdd(); }}>
        </div>
        <chronos-cal-mini .selected=${s.anchor} .marked=${new Set(s.events().map(e => dayKey(e.start)))}
          @cal-pick=${(e: CustomEvent) => { e.stopPropagation(); s.focusDay(e.detail); }}></chronos-cal-mini>
        <section><h4>${tr("Calendars")}</h4>
          ${s.sources.map(src => html`<label class="flt"><input type="checkbox" class="chk" .checked=${src.enabled} @change=${() => s.toggleSource(src.id)}>
            <span class="sw ai"></span><span class="nm">${src.label}</span></label>`)}
          <p class="hint">${tr("Your Google/Outlook calendars will arrive here as separate layers.")}</p></section>
        <section><h4>${tr("Modules")}</h4>
          ${s.owners().length ? s.owners().map(o => html`<label class="flt" title=${tr('Double click: show only ') + ownerLabel(o.owner)}
              @dblclick=${() => s.onlyOwner(o.owner)}>
            <input type="checkbox" class="chk" style="accent-color:${o.color}" .checked=${!s.hiddenOwners.has(o.owner)} @change=${() => s.toggleOwner(o.owner)}>
            <span class="sw" style="background:${o.color}"></span><span class="nm">${ownerLabel(o.owner)}</span><span class="cnt">${o.count}</span></label>`)
            : html`<p class="hint">${tr("No module has planned anything yet.")}</p>`}</section>
        <section><h4>${tr("Types")}</h4>
          ${TYPES.map(t => html`<label class="flt"><input type="checkbox" class="chk" .checked=${!s.hiddenTypes.has(t)} @change=${() => s.toggleType(t)}>
            ${ic(TYPE_META[t].icon, 14)}<span class="nm">${TYPE_META[t].label}</span></label>`)}</section>
        <section class="opts">
          ${toggle(tr('Show skipped occurrences'), s.showSkipped, v => s.setShowSkipped(v))}
          ${toggle(tr('Show completed/cancelled'), s.showDone, v => s.setShowDone(v))}
        </section>
      </aside><div class="scrim" @click=${() => (this.sideOpen = false)}></div>`;
  }

  private renderView() {
    const s = this.store, ev = s.events();
    const handlers = {
      select: (e: CustomEvent) => { e.stopPropagation(); this.select(e.detail); },
      create: (e: CustomEvent) => { e.stopPropagation(); this.newAt(e.detail); },
      move: (e: CustomEvent) => { e.stopPropagation(); void this.onMove(e.detail); },
      day: (e: CustomEvent) => { e.stopPropagation(); this.openDay(e.detail); },
    };
    if (s.view === 'month') return html`<chronos-cal-month .anchor=${s.anchor} .events=${ev} .weather=${s.weather} @cal-select=${handlers.select}
      @cal-create=${handlers.create} @cal-move=${handlers.move} @cal-day=${handlers.day}></chronos-cal-month>`;
    if (s.view === 'list') return html`<chronos-cal-list .events=${ev} .weather=${s.weather} .from=${s.range().start} @cal-select=${handlers.select}></chronos-cal-list>`;
    return html`<chronos-cal-grid .days=${this.gridDays()} .events=${ev} .weather=${s.weather} .windowsMode=${s.vp.windowsMode} .frequentMode=${s.vp.frequentMode}
      .focusDay=${s.anchor} .scrollHour=${s.vp.scrollHour} .workHours=${[s.vp.workStart, s.vp.workEnd]}
      @cal-select=${handlers.select} @cal-create=${handlers.create} @cal-move=${handlers.move} @cal-day=${handlers.day}></chronos-cal-grid>`;
  }

  private renderVista() {
    const s = this.store, vp = s.vp;
    const n = (key: NumKey, min: number, max: number) => html`<input type="number" min=${min} max=${max} .value=${String(vp[key])}
      @change=${(e: any) => this.num(key, e.target.value)}>`;
    return html`<chronos-pop .open=${!!this.vistaRect} .anchor=${this.vistaRect} .width=${340} placement="below" @close=${() => (this.vistaRect = null)}>
      <div class="vista">
        <h4>${tr("Calendar view")}</h4>
        <div class="lab">${tr("Windows (e.g. Athena when you are idle)")}
          ${segmented([{ value: 'lane', label: tr('Lane') }, { value: 'band', label: tr('Band') }, { value: 'hidden', label: tr('f.pl::Hidden') }],
            vp.windowsMode, v => s.setVp({ windowsMode: v }))}</div>
        <div class="lab">${tr("Frequent recurrences")} <small>${tr("Rules with at least")} ${vp.frequentPerDay} ${tr("runs per day")}</small>
          ${segmented([{ value: 'compact', label: tr('f.pl::Compact') }, { value: 'full', label: tr('Complete') }, { value: 'hidden', label: tr('f.pl::Hidden') }],
            vp.frequentMode, v => s.setVp({ frequentMode: v }))}</div>
        <label class="num">${tr("Frequent since")} ${n('frequentPerDay', 2, 96)} ${tr("times a day")}</label>
        ${toggle(tr('Focused view (less crowded)'), vp.focused, v => s.setVp({ focused: v }))}
        ${vp.focused ? html`<div class="rules">
          <p>${tr("The items you created and the selected day are always shown.")}</p>
          <label class="num">${tr("Frequent recurrences: next")} ${n('frequentDays', 1, 60)} ${tr("days")}</label>
          <label class="num">${tr("Rare recurrences: next")} ${n('rareCount', 1, 50)} ${tr("times or")} ${n('rareDays', 1, 60)} ${tr("days (whichever comes first)")}</label>
          <label class="num">${tr("Past: only errors of the last")} ${n('pastDays', 0, 90)} ${tr("days, one per rule")}</label></div>` : nothing}
        <label class="num">${tr("Scroll on opening to")} ${n('scrollHour', 0, 23)}:00</label>
        <label class="num">${tr("Working hours (Mon–Fri)")} ${n('workStart', 0, 24)}–${n('workEnd', 0, 24)}${tr(": outside it is shaded")}</label>
        <div style="display:flex"><span class="grow"></span><hxk-button size="sm" variant="ghost" @click=${() => s.resetVp()}>${tr("Restore defaults")}</hxk-button></div>
      </div></chronos-pop>`;
  }

  private renderLogs() {
    const l = this.logs;
    const time = (ts: string) => { const d = new Date(ts); return `${fmt.time(d)}:${String(d.getSeconds()).padStart(2, '0')}`; };
    return html`<chronos-dialog .open=${!!l} heading=${tr('Log · ') + (l?.title || '')} size="lg" @close=${() => (this.logs = null)}>
      ${l ? html`<div class="logs-bar">
          <select @change=${(e: any) => void this.loadLogs({ service: e.target.value })}>
            ${l.services.map(x => html`<option value=${x} ?selected=${x === l.service}>${x}</option>`)}</select>
          <span>±</span>
          <select @change=${(e: any) => void this.loadLogs({ minutes: +e.target.value })}>
            ${[2, 5, 15, 60].map(m => html`<option value=${m} ?selected=${m === l.minutes}>${m} ${tr("min")}</option>`)}</select>
          <span class="muted">${tr("around")} ${l.when}</span>${l.loading ? html`<span class="muted">…</span>` : nothing}</div>
        ${l.error ? html`<p class="bad">${l.error}</p>` : l.result ? (l.result.logs.length
          ? html`<div class="logs">${l.result.logs.map(r => html`<div class="lr" data-l=${r.level}><span class="lts">${time(r.ts)}</span>
              <span class="llv">${r.level}</span><span class="lm">${r.message}</span></div>`)}</div>`
          : html`<p class="muted">${tr("No line in this interval.")}${l.result.oldest ? tr(" The module keeps in memory only the last lines (from {0}).", fmt.relative(new Date(l.result.oldest))) : ''}</p>`)
          : nothing}` : nothing}
    </chronos-dialog>`;
  }

  private renderIcs() {
    return html`<chronos-dialog .open=${this.icsOpen} heading=${tr("Agenda on the phone")} @close=${() => (this.icsOpen = false)}>
      <p class="ics-p">${tr("Read-only iCalendar feed of {assistant}'s agenda (events, tasks and windows; the periodic jobs stay here).")}</p>
      <p class="ics-p small">${tr("For the subscription from the phone set")} <code>WEBUI_ICS_KEY</code> ${tr("(at least 16 characters) in the WebUI service and add it as a calendar \"from URL\" (Google Calendar, Apple Calendar)")} <code>${location.origin}/api/webui/agenda/feed.ics?key=&lt;${tr("your key")}&gt;</code>${tr(". Whoever has the link sees the agenda: don't share it. Meanwhile you can download the file.")}</p>
      <div slot="footer"><hxk-button variant="primary" icon="external" @click=${() => void this.downloadIcs()}>${tr("Download .ics")}</hxk-button></div>
    </chronos-dialog>`;
  }

  render() {
    const s = this.store;
    if (!s) return nothing;
    return html`<div class="cal">
      ${this.renderSide()}
      <section class="main">
        <header class="bar">
          <button class="ib side-btn" aria-label=${tr("Filters")} @click=${() => (this.sideOpen = !this.sideOpen)}>${ic('sidebar', 18)}</button>
          <hxk-button size="sm" @click=${() => s.today()}>${tr("Today")}</hxk-button>
          <button class="ib" aria-label=${this.stepLabel(-1)} title=${this.stepLabel(-1) + ' (←)'} @click=${() => s.step(-1)}>${ic('chevron-left', 16)}</button>
          <button class="ib" aria-label=${this.stepLabel(1)} title=${this.stepLabel(1) + ' (→)'} @click=${() => s.step(1)}>${ic('chevron-right', 16)}</button>
          <h2>${s.title()}</h2>
          ${s.loading ? html`<span class="muted">…</span>` : nothing}
          <span class="grow"></span>
          <div class="search">${ic('search', 15)}<input placeholder=${tr("Search…")} .value=${s.search} @input=${(e: any) => s.setSearch(e.target.value)}></div>
          <button class="ib" aria-label=${tr("Refresh")} title=${tr("Refresh")} @click=${() => void s.load()}>${ic('refresh', 16)}</button>
          <button class="ib" aria-label=${tr("Seen")} title=${tr("View: windows, recurrences, what to show")}
            @click=${(e: Event) => (this.vistaRect = this.vistaRect ? null : (e.currentTarget as HTMLElement).getBoundingClientRect())}>${ic('settings', 16)}</button>
          ${segmented(VIEWS, s.view, v => s.setView(v))}
        </header>
        ${s.error ? html`<div class="err">${ic('alert', 16)} ${s.error}<hxk-button size="sm" variant="ghost" @click=${() => void s.load()}>${tr("Try again")}</hxk-button></div>` : nothing}
        ${s.vp.focused && s.hiddenByPolicy() > 0 ? html`<div class="hint-bar">${ic('filter', 14)}
          <span>${s.hiddenByPolicy()} ${tr("next module entries hidden from the")} <b>${tr("focused view")}</b> ${tr('(beyond the set horizon).')}</span>
          <button class="lnk" @click=${() => s.setVp({ focused: false })}>${tr("Show everything")}</button>
          <button class="lnk" @click=${(e: Event) => (this.vistaRect = (e.currentTarget as HTMLElement).getBoundingClientRect())}>${tr("Rules…")}</button></div>` : nothing}
        <div class="view">${this.renderView()}</div>
      </section>
    </div>
    <chronos-pop .open=${!!this.sel} .anchor=${this.selRect} .width=${360} @close=${() => (this.sel = null)}>
      ${this.sel ? html`<chronos-cal-details .ev=${this.sel} .host=${this.host}
        @cal-act=${(e: CustomEvent) => { e.stopPropagation(); void this.onAction(e.detail); }}
        @cal-pick-occ=${(e: CustomEvent) => { e.stopPropagation(); this.sel = e.detail; }}></chronos-cal-details>` : nothing}
    </chronos-pop>
    ${this.renderVista()}
    <chronos-cal-editor .seed=${this.editor} @close=${(e: Event) => { e.stopPropagation(); this.editor = null; }}
      @cal-save=${(e: CustomEvent) => { e.stopPropagation(); void this.onSave(e.detail); }}
      @cal-ask=${(e: CustomEvent) => { e.stopPropagation(); this.onAskFromEditor(e.detail); }}></chronos-cal-editor>
    <chronos-cal-wizard .seed=${this.wizard} .api=${s.api} @close=${(e: Event) => { e.stopPropagation(); this.wizard = null; }}
      @cal-template=${(e: CustomEvent) => { e.stopPropagation(); void this.onTemplate(e.detail); }}></chronos-cal-wizard>
    <chronos-dialog .open=${!!this.moveAsk} heading=${tr("Move the recurring item")} @close=${() => (this.moveAsk = null)}>
      <p class="ics-p">“${this.moveAsk?.ev.occ.title ?? ''}${tr("”: only this occurrence or the whole series?")}</p>
      <div slot="footer" style="display:flex;gap:8px">
        <hxk-button @click=${() => void this.doMove('one')}>${tr("Only this one")}</hxk-button>
        <hxk-button variant="primary" @click=${() => void this.doMove('all')}>${tr("The whole series")}</hxk-button></div>
    </chronos-dialog>
    ${this.renderLogs()}${this.renderIcs()}`;
  }
}
