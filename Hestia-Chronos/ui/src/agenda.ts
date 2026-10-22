/**
 * <chronos-agenda> — "Agenda di Hestia": the assistant's own calendar (month / week / day / list), sidebar with mini
 * calendar, layers and filters, popover details, editor, drag & drop, quick add in words, "Da un modulo…", module
 * logs around an occurrence, ICS file. Keys: T oggi · M/W/D/L viste · N nuovo · ←/→. Ported from the WebUI's
 * built-in calendar page (SPEC docs/work/2026-10-18-moduli-core-e-mcp-esterno P6); state in cal/store.ts.
 */
import { HestiaElement, css, html, nothing } from '@hestia/webui-sdk';
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
  { value: 'day', label: 'Giorno', title: 'Giorno (D)' }, { value: 'week', label: 'Settimana', title: 'Settimana (W)' },
  { value: 'month', label: 'Mese', title: 'Mese (M)' }, { value: 'list', label: 'Elenco', title: 'Elenco (L)' },
];
const NEW_MENU: MenuItem[] = [
  { id: 'free', label: 'Evento libero', icon: 'edit' }, { id: 'module', label: 'Da un modulo…', icon: 'zap' },
  { id: 'ai', label: 'Crea con Hestia…', icon: 'sparkle' }, { id: 'd', label: '', divider: true },
  { id: 'ics', label: 'Agenda sul telefono (ICS)…', icon: 'external' },
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
    const unit = { day: ['Giorno precedente', 'Giorno successivo'], week: ['Settimana precedente', 'Settimana successiva'],
                   month: ['Mese precedente', 'Mese successivo'], list: ['30 giorni prima', '30 giorni dopo'] }[this.store.view];
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
    this.host.assistant({ label: `Agenda · ${fmt.dayLong(d)}${at ? ', ' + fmt.time(at) : ''}`, prompt,
      hints: this.hints({ giorno: dayKey(d), ora: at ? fmt.time(at) : undefined, vista: this.store.view,
                          agenda: 'agenda di Hestia (strumenti agenda_assistente_*)' }) });
  }
  private askAbout(ev: CalEvent) {
    const it = ev.item;
    this.host.assistant({ label: `“${ev.occ.title}” · ${fmt.dayLong(ev.start)} ${fmt.time(ev.start)}`,
      hints: this.hints({ voce: ev.occ.key, titolo: ev.occ.title, modulo: ev.occ.owner, tipo: ev.occ.type, occorrenza: ev.occ.occurrence,
        regola: it?.recurrence, stato: ev.occ.status,
        ultimo_esito: it?.last_result ? (it.last_result.ok ? 'ok' : 'fallito: ' + (it.last_result.detail || '')) : undefined }),
      suggestions: ev.occ.recurring
        ? ['Spiegami cosa fa questa regola', 'Sposta solo questa occorrenza di un\'ora', 'Cambia la frequenza…', 'Perché è fallita?']
        : ['Spiegami cosa fa', 'Spostala a domani alla stessa ora', 'Perché è fallita?'] });
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
      this.host.toast(`Non ho capito la data (${e?.message || 'errore'}): completa tu`, 'warning');
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
      if (seq === this.logsSeq && this.logs) this.logs = { ...next, loading: false, result: null, error: e?.message || 'Log non disponibili' };
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
    } catch (e: any) { this.host.toast(e?.message || 'Download non riuscito', 'danger'); }
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
      case 'restore': await s.update(ev.occ.key, { status: 'confirmed' }, 'Regola ripristinata'); break;
      case 'reset-move': await s.resetMove(ev); break;
      case 'ask': this.askAbout(ev); break;
      case 'logs': this.openLogs(ev); break;
      case 'cancel': {
        const ok = await this.host.confirm(ev.occ.recurring ? 'Annullare tutta la regola?' : 'Annullare la voce?',
          ev.occ.recurring ? 'Nessuna occorrenza futura verrà eseguita. Per saltarne solo una usa «Salta questa».' : '',
          { label: 'Annulla regola', danger: true });
        if (ok) await s.cancel(ev);
        break;
      }
    }
  }
  private async onSave(r: EditorResult) {
    this.editor = null;
    if (r.key) await this.store.update(r.key, r.body, 'Modifiche salvate');
    else await this.store.create(r.body);
  }
  private onAskFromEditor(a: EditorAsk) { this.editor = null; this.askCreate(a.start ?? undefined, a.title ? `${a.title} ` : ''); }
  private async onTemplate(r: TemplateCreate) { this.wizard = null; await this.store.createFromTemplate(r.tpl.owner, r.tpl.id, r.body); }

  // ── render ─────────────────────────────────────────────────────────────
  private renderSide() {
    const s = this.store;
    return html`<aside class="side ${this.sideOpen ? 'open' : ''}" style="--side-w:${s.sideW}px">
        <div class="new-wrap">
          <button class="new" title="Nuovo evento libero (N)" @click=${() => this.newAt(this.defaultStart())}>${ic('plus', 16)} Nuovo</button>
          <chronos-menu .items=${NEW_MENU} @select=${(e: CustomEvent) => { e.stopPropagation(); this.onNew(e.detail); }}>
            <button class="new-more" aria-label="Altri modi di creare">${ic('chevron-down', 16)}</button></chronos-menu>
        </div>
        <div class="quick" title="Scrivi a parole, es. &quot;domani alle 15 dentista&quot; o &quot;ogni lunedì alle 9 controlla le case&quot;: si apre l'editor già compilato">
          ${this.quickBusy ? html`<hxk-icon name="refresh" size="14"></hxk-icon>` : ic('sparkle', 15)}
          <input placeholder="Aggiungi rapido: domani alle 15…" .value=${this.quick} ?disabled=${this.quickBusy}
            @input=${(e: any) => (this.quick = e.target.value)} @keydown=${(e: KeyboardEvent) => { if (e.key === 'Enter') void this.quickAdd(); }}>
        </div>
        <chronos-cal-mini .selected=${s.anchor} .marked=${new Set(s.events().map(e => dayKey(e.start)))}
          @cal-pick=${(e: CustomEvent) => { e.stopPropagation(); s.focusDay(e.detail); }}></chronos-cal-mini>
        <section><h4>Calendari</h4>
          ${s.sources.map(src => html`<label class="flt"><input type="checkbox" class="chk" .checked=${src.enabled} @change=${() => s.toggleSource(src.id)}>
            <span class="sw ai"></span><span class="nm">${src.label}</span></label>`)}
          <p class="hint">I tuoi calendari Google/Outlook arriveranno qui come livelli separati.</p></section>
        <section><h4>Moduli</h4>
          ${s.owners().length ? s.owners().map(o => html`<label class="flt" title=${'Doppio clic: mostra solo ' + ownerLabel(o.owner)}
              @dblclick=${() => s.onlyOwner(o.owner)}>
            <input type="checkbox" class="chk" style="accent-color:${o.color}" .checked=${!s.hiddenOwners.has(o.owner)} @change=${() => s.toggleOwner(o.owner)}>
            <span class="sw" style="background:${o.color}"></span><span class="nm">${ownerLabel(o.owner)}</span><span class="cnt">${o.count}</span></label>`)
            : html`<p class="hint">Nessun modulo ha ancora pianificato nulla.</p>`}</section>
        <section><h4>Tipi</h4>
          ${TYPES.map(t => html`<label class="flt"><input type="checkbox" class="chk" .checked=${!s.hiddenTypes.has(t)} @change=${() => s.toggleType(t)}>
            ${ic(TYPE_META[t].icon, 14)}<span class="nm">${TYPE_META[t].label}</span></label>`)}</section>
        <section class="opts">
          ${toggle('Mostra occorrenze saltate', s.showSkipped, v => s.setShowSkipped(v))}
          ${toggle('Mostra completate/annullate', s.showDone, v => s.setShowDone(v))}
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
        <h4>Vista del calendario</h4>
        <div class="lab">Finestre (es. Athena quando sei inattivo)
          ${segmented([{ value: 'lane', label: 'Corsia' }, { value: 'band', label: 'Banda' }, { value: 'hidden', label: 'Nascoste' }],
            vp.windowsMode, v => s.setVp({ windowsMode: v }))}</div>
        <div class="lab">Ricorrenze frequenti <small>Regole con almeno ${vp.frequentPerDay} esecuzioni al giorno</small>
          ${segmented([{ value: 'compact', label: 'Compatte' }, { value: 'full', label: 'Complete' }, { value: 'hidden', label: 'Nascoste' }],
            vp.frequentMode, v => s.setVp({ frequentMode: v }))}</div>
        <label class="num">Frequente da ${n('frequentPerDay', 2, 96)} volte al giorno</label>
        ${toggle('Vista focalizzata (meno affollata)', vp.focused, v => s.setVp({ focused: v }))}
        ${vp.focused ? html`<div class="rules">
          <p>Le voci create da te e il giorno selezionato si vedono sempre.</p>
          <label class="num">Ricorrenze frequenti: prossimi ${n('frequentDays', 1, 60)} giorni</label>
          <label class="num">Ricorrenze rare: prossime ${n('rareCount', 1, 50)} volte o ${n('rareDays', 1, 60)} giorni (il primo che arriva)</label>
          <label class="num">Passato: solo errori degli ultimi ${n('pastDays', 0, 90)} giorni, uno per regola</label></div>` : nothing}
        <label class="num">Scorri all'apertura alle ${n('scrollHour', 0, 23)}:00</label>
        <label class="num">Orario di lavoro (lun–ven) ${n('workStart', 0, 24)}–${n('workEnd', 0, 24)}: fuori è ombreggiato</label>
        <div style="display:flex"><span class="grow"></span><hxk-button size="sm" variant="ghost" @click=${() => s.resetVp()}>Ripristina predefinite</hxk-button></div>
      </div></chronos-pop>`;
  }

  private renderLogs() {
    const l = this.logs;
    const time = (ts: string) => { const d = new Date(ts); return `${fmt.time(d)}:${String(d.getSeconds()).padStart(2, '0')}`; };
    return html`<chronos-dialog .open=${!!l} heading=${'Log · ' + (l?.title || '')} size="lg" @close=${() => (this.logs = null)}>
      ${l ? html`<div class="logs-bar">
          <select @change=${(e: any) => void this.loadLogs({ service: e.target.value })}>
            ${l.services.map(x => html`<option value=${x} ?selected=${x === l.service}>${x}</option>`)}</select>
          <span>±</span>
          <select @change=${(e: any) => void this.loadLogs({ minutes: +e.target.value })}>
            ${[2, 5, 15, 60].map(m => html`<option value=${m} ?selected=${m === l.minutes}>${m} min</option>`)}</select>
          <span class="muted">attorno a ${l.when}</span>${l.loading ? html`<span class="muted">…</span>` : nothing}</div>
        ${l.error ? html`<p class="bad">${l.error}</p>` : l.result ? (l.result.logs.length
          ? html`<div class="logs">${l.result.logs.map(r => html`<div class="lr" data-l=${r.level}><span class="lts">${time(r.ts)}</span>
              <span class="llv">${r.level}</span><span class="lm">${r.message}</span></div>`)}</div>`
          : html`<p class="muted">Nessuna riga in questo intervallo.${l.result.oldest ? ` Il modulo tiene in memoria solo le ultime righe (dalle ${fmt.relative(new Date(l.result.oldest))}).` : ''}</p>`)
          : nothing}` : nothing}
    </chronos-dialog>`;
  }

  private renderIcs() {
    return html`<chronos-dialog .open=${this.icsOpen} heading="Agenda sul telefono" @close=${() => (this.icsOpen = false)}>
      <p class="ics-p">Feed iCalendar di sola lettura dell'agenda di Hestia (eventi, task e finestre; i job periodici restano qui).</p>
      <p class="ics-p small">Per l'abbonamento dal telefono imposta <code>WEBUI_ICS_KEY</code> (almeno 16 caratteri) nel servizio WebUI e
        aggiungi come calendario "da URL" (Google Calendar, Apple Calendario) <code>${location.origin}/api/webui/agenda/feed.ics?key=&lt;la tua chiave&gt;</code>.
        Chi ha il link vede l'agenda: non condividerlo. Intanto puoi scaricare il file.</p>
      <div slot="footer"><hxk-button variant="primary" icon="external" @click=${() => void this.downloadIcs()}>Scarica .ics</hxk-button></div>
    </chronos-dialog>`;
  }

  render() {
    const s = this.store;
    if (!s) return nothing;
    return html`<div class="cal">
      ${this.renderSide()}
      <section class="main">
        <header class="bar">
          <button class="ib side-btn" aria-label="Filtri" @click=${() => (this.sideOpen = !this.sideOpen)}>${ic('sidebar', 18)}</button>
          <hxk-button size="sm" @click=${() => s.today()}>Oggi</hxk-button>
          <button class="ib" aria-label=${this.stepLabel(-1)} title=${this.stepLabel(-1) + ' (←)'} @click=${() => s.step(-1)}>${ic('chevron-left', 16)}</button>
          <button class="ib" aria-label=${this.stepLabel(1)} title=${this.stepLabel(1) + ' (→)'} @click=${() => s.step(1)}>${ic('chevron-right', 16)}</button>
          <h2>${s.title()}</h2>
          ${s.loading ? html`<span class="muted">…</span>` : nothing}
          <span class="grow"></span>
          <div class="search">${ic('search', 15)}<input placeholder="Cerca…" .value=${s.search} @input=${(e: any) => s.setSearch(e.target.value)}></div>
          <button class="ib" aria-label="Aggiorna" title="Aggiorna" @click=${() => void s.load()}>${ic('refresh', 16)}</button>
          <button class="ib" aria-label="Vista" title="Vista: finestre, ricorrenze, cosa mostrare"
            @click=${(e: Event) => (this.vistaRect = this.vistaRect ? null : (e.currentTarget as HTMLElement).getBoundingClientRect())}>${ic('settings', 16)}</button>
          ${segmented(VIEWS, s.view, v => s.setView(v))}
        </header>
        ${s.error ? html`<div class="err">${ic('alert', 16)} ${s.error}<hxk-button size="sm" variant="ghost" @click=${() => void s.load()}>Riprova</hxk-button></div>` : nothing}
        ${s.vp.focused && s.hiddenByPolicy() > 0 ? html`<div class="hint-bar">${ic('filter', 14)}
          <span>${s.hiddenByPolicy()} prossime voci dei moduli nascoste dalla <b>vista focalizzata</b> (oltre l'orizzonte impostato).</span>
          <button class="lnk" @click=${() => s.setVp({ focused: false })}>Mostra tutto</button>
          <button class="lnk" @click=${(e: Event) => (this.vistaRect = (e.currentTarget as HTMLElement).getBoundingClientRect())}>Regole…</button></div>` : nothing}
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
    <chronos-dialog .open=${!!this.moveAsk} heading="Spostare la voce ricorrente" @close=${() => (this.moveAsk = null)}>
      <p class="ics-p">“${this.moveAsk?.ev.occ.title ?? ''}”: solo questa occorrenza o tutta la serie?</p>
      <div slot="footer" style="display:flex;gap:8px">
        <hxk-button @click=${() => void this.doMove('one')}>Solo questa</hxk-button>
        <hxk-button variant="primary" @click=${() => void this.doMove('all')}>Tutta la serie</hxk-button></div>
    </chronos-dialog>
    ${this.renderLogs()}${this.renderIcs()}`;
  }
}
