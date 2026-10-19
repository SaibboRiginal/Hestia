/**
 * <chronos-cal-editor> — create / edit an agenda item (title, type, time, recurrence, description, action).
 * `seed` opens it (null = closed). Events: cal-save (EditorResult), cal-ask (EditorAsk), close.
 * Ported from the WebUI's event-editor component.
 */
import { LitElement, css, html, nothing, tokens, kitStyles } from '@hestia/webui-sdk';
import { type AgendaItem, type AgendaType, TYPE_META, fire } from './models';
import { WEEKDAYS, WEEKDAY_LABELS, addMinutes, fromLocalInput, toLocalInput } from './date';
import { type Freq, type RepeatModel, buildRRule, describeRRule, emptyRepeat, parseRRule } from './rrule';
import { calStyles, segmented } from './ui';

export interface EditorSeed {
  start: Date; end?: Date | null; type?: AgendaType; item?: AgendaItem; duplicate?: boolean;
  /** Natural-language quick add: fields Oracle understood (the user reviews them here). */
  prefill?: { title?: string; description?: string; recurrence?: string | null };
}
export interface EditorAsk { title: string; start: Date | null; end: Date | null; type: AgendaType; }
export interface EditorResult { key?: string; body: Record<string, unknown>; }
type Errors = { title?: string; start?: string; end?: string; body?: string };

const TYPES: AgendaType[] = ['event', 'task', 'job', 'window'];
const FREQS: { value: Freq; label: string }[] = [
  { value: 'none', label: 'Non si ripete' }, { value: 'MINUTELY', label: 'Ogni N minuti' }, { value: 'HOURLY', label: 'Ogni N ore' },
  { value: 'DAILY', label: 'Giornaliera' }, { value: 'WEEKLY', label: 'Settimanale' }, { value: 'MONTHLY', label: 'Mensile' },
  { value: 'YEARLY', label: 'Annuale' }, { value: 'custom', label: 'Regola personalizzata (RRULE)' },
];

export const formStyles = css`
  .form { display: flex; flex-direction: column; gap: 14px; padding-bottom: 6px; }
  .f { display: flex; flex-direction: column; gap: 4px; }
  .f > span { font-size: 12px; color: var(--text-2); font-weight: 500; }
  .f > span b { color: var(--danger); }
  .f .hint { font-size: 12px; color: var(--text-3); } .f .er { font-size: 12px; color: var(--danger); }
  input:not([type=checkbox]), select, textarea { font: inherit; color: var(--text); background: var(--surface-2);
    border: 1px solid var(--border-strong); border-radius: var(--radius-sm); padding: 7px 10px; outline: none; width: 100%; min-width: 0; box-sizing: border-box; }
  input:focus, select:focus, textarea:focus { border-color: var(--accent); box-shadow: 0 0 0 3px var(--focus-ring); }
  .mono { font-family: var(--font-mono); font-size: 12.5px; }
  .row2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .inl { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; color: var(--text-2); }
  .num { width: 74px !important; }
  @media (max-width: 640px) { .row2 { grid-template-columns: 1fr; } }
`;

export class ChronosCalEditor extends LitElement {
  static properties = { seed: { attribute: false }, f: { state: true }, rep: { state: true }, errors: { state: true } };
  declare seed: EditorSeed | null;
  declare f: { title: string; description: string; start: string; end: string; type: AgendaType;
               svc: string; method: string; path: string; body: string };
  declare rep: RepeatModel; declare errors: Errors;
  private loadedFor: EditorSeed | null = null;
  static styles = [tokens, kitStyles, calStyles, formStyles, css`
    .title { font-size: 16px; padding: 10px 12px !important; }
    .rep { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
    .rep select { width: auto; min-width: 220px; }
    .rep.end { margin-top: 8px; }
    .days { display: flex; gap: 5px; margin-top: 8px; flex-wrap: wrap; }
    .day { width: 42px; height: 30px; border-radius: 99px; border: 1px solid var(--border-strong); font-size: 12.5px; color: var(--text-2); }
    .day.on { background: var(--accent); border-color: var(--accent); color: var(--accent-contrast); }
    .row3 { display: grid; grid-template-columns: 1fr 110px 2fr; gap: 10px; margin-bottom: 10px; }
    .adv { border: 1px solid var(--border); border-radius: var(--radius-md); padding: 8px 12px; }
    .adv summary { cursor: pointer; font-size: 13px; color: var(--text-2); font-weight: 500; padding: 2px 0 6px; }
    .note { font-size: 12.5px; color: var(--text-3); background: var(--surface-2); padding: 8px 10px; border-radius: var(--radius-md); margin: 0; }
    .ask { margin-right: auto; }
    @media (max-width: 640px) { .row3 { grid-template-columns: 1fr; } }
  `];

  constructor() {
    super(); this.seed = null; this.errors = {}; this.rep = emptyRepeat();
    this.f = { title: '', description: '', start: '', end: '', type: 'event', svc: '', method: 'POST', path: '', body: '' };
  }

  willUpdate() {
    const s = this.seed;
    if (!s || s === this.loadedFor) return;
    this.loadedFor = s;
    const it = s.item, dup = !!s.duplicate;
    const start = it && !dup ? new Date(it.start_at) : s.start;
    const end = it && !dup ? (it.end_at ? new Date(it.end_at) : null)
      : (s.end ?? (it?.end_at ? new Date(s.start.getTime() + (new Date(it.end_at).getTime() - new Date(it.start_at).getTime())) : addMinutes(s.start, 60)));
    this.f = {
      title: it ? (dup ? `${it.title} (copia)` : it.title) : (s.prefill?.title ?? ''),
      description: it?.description ?? s.prefill?.description ?? '',
      start: toLocalInput(start), end: end ? toLocalInput(end) : '', type: it?.type ?? s.type ?? 'event',
      svc: it?.action?.service ?? '', method: it?.action?.method ?? 'POST', path: it?.action?.path ?? '',
      body: it?.action?.body ? JSON.stringify(it.action.body, null, 2) : '',
    };
    this.rep = parseRRule(it?.recurrence ?? s.prefill?.recurrence);
    this.errors = {};
  }

  private get editing() { return !!this.seed?.item && !this.seed?.duplicate; }
  private get needsEnd() { return this.f.type === 'window' || this.f.type === 'event'; }
  private set(k: keyof ChronosCalEditor['f'], v: string) { this.f = { ...this.f, [k]: v }; }

  private onStart(v: string) {   // keep the duration when the start moves
    const s = fromLocalInput(v), old = fromLocalInput(this.f.start), e = fromLocalInput(this.f.end);
    this.f = { ...this.f, start: v, end: s && old && e ? toLocalInput(new Date(e.getTime() + (s.getTime() - old.getTime()))) : this.f.end };
  }

  private patchRep(p: Partial<RepeatModel>) {
    const next = { ...this.rep, ...p } as RepeatModel;
    if (p.freq === 'WEEKLY' && !next.byday.length) {
      const d = fromLocalInput(this.f.start) ?? new Date();
      next.byday = [WEEKDAYS[(d.getDay() + 6) % 7]];
    }
    if (p.freq === 'custom' && !next.raw)
      next.raw = buildRRule({ ...this.rep, freq: (this.rep.freq === 'custom' ? 'DAILY' : this.rep.freq) as Freq }) ?? '';
    this.rep = next;
  }

  private toggleDay(d: string) {
    const r = this.rep, byday = r.byday.includes(d) ? r.byday.filter(x => x !== d) : [...r.byday, d];
    this.rep = { ...r, byday: byday.length ? byday : r.byday };
  }

  private ask() {
    fire(this, 'cal-ask', { title: this.f.title.trim(), start: fromLocalInput(this.f.start),
                            end: this.f.end ? fromLocalInput(this.f.end) : null, type: this.f.type } as EditorAsk);
  }

  private save(e?: Event) {
    e?.preventDefault();
    const f = this.f, errs: Errors = {};
    const start = fromLocalInput(f.start), end = this.needsEnd ? fromLocalInput(f.end) : null;
    if (!f.title.trim()) errs.title = 'Serve un titolo';
    if (!start) errs.start = 'Data/ora non valida';
    if (f.type === 'window' && !end) errs.end = 'Una finestra ha bisogno della fine';
    if (start && end && end <= start) errs.end = 'La fine deve essere dopo l\'inizio';
    let body: unknown = undefined;
    if (f.body.trim()) { try { body = JSON.parse(f.body); } catch { errs.body = 'JSON non valido'; } }
    this.errors = errs;
    if (Object.keys(errs).length) return;
    const action = (f.type === 'task' || f.type === 'job') && f.svc.trim() && f.path.trim()
      ? { service: f.svc.trim(), path: f.path.trim(), method: f.method, body: body ?? null } : undefined;
    const recurrence = f.type === 'task' ? null : buildRRule(this.rep);
    const payload: Record<string, unknown> = { title: f.title.trim(), description: f.description.trim() || null,
      start_at: start!.toISOString(), end_at: end ? end.toISOString() : null, recurrence: recurrence ?? '' };
    if (action) payload['action'] = action;
    const it = this.seed?.item;
    fire(this, 'cal-save', (this.editing && it ? { key: it.key, body: payload }
      : { body: { ...payload, type: f.type, recurrence: recurrence ?? null, owner: 'user', created_by: 'user' } }) as EditorResult);
  }

  private field(label: string, body: unknown, o: { req?: boolean; hint?: string; err?: string } = {}) {
    return html`<label class="f"><span>${label}${o.req ? html` <b>*</b>` : nothing}</span>${body}
      ${o.err ? html`<span class="er">${o.err}</span>` : o.hint ? html`<span class="hint">${o.hint}</span>` : nothing}</label>`;
  }

  render() {
    const s = this.seed, f = this.f, r = this.rep, er = this.errors;
    const series = this.editing && r.freq !== 'none';
    const typeOpts = TYPES.map(t => ({ value: t, label: TYPE_META[t].label, title: TYPE_META[t].hint }));
    return html`<chronos-dialog .open=${!!s} heading=${this.editing ? 'Modifica voce' : 'Nuova voce in agenda'} size="lg" @close=${() => fire(this, 'close')}>
      ${s ? html`<form class="form" @submit=${(e: Event) => this.save(e)}>
        ${this.field('Titolo', html`<input class="title" .value=${f.title} placeholder="Es. Controlla le email della banca"
          @input=${(e: any) => this.set('title', e.target.value)}>`, { req: true, err: er.title })}
        ${this.field('Tipo', segmented(typeOpts, f.type, v => { if (!this.editing) this.set('type', v); }),
          { hint: this.editing ? 'Il tipo non si cambia: duplica la voce per crearne una di altro tipo.' : TYPE_META[f.type].hint })}
        <div class="row2">
          ${this.field(series ? 'Inizio della serie' : 'Inizio', html`<input type="datetime-local" .value=${f.start}
            @change=${(e: any) => this.onStart(e.target.value)}>`,
            { req: true, err: er.start, hint: series ? "Prima occorrenza della regola: spostala per cambiare l'orario di tutte" : '' })}
          ${this.needsEnd ? this.field('Fine', html`<input type="datetime-local" .value=${f.end}
            @change=${(e: any) => this.set('end', e.target.value)}>`, { req: f.type === 'window', err: er.end }) : nothing}
        </div>
        ${f.type === 'task' ? nothing : this.field('Ripetizione', html`
          <div class="rep">
            <select @change=${(e: any) => this.patchRep({ freq: e.target.value })}>
              ${FREQS.map(o => html`<option value=${o.value} ?selected=${o.value === r.freq}>${o.label}</option>`)}</select>
            ${r.freq !== 'none' && r.freq !== 'custom' ? html`<span class="inl">ogni <input class="num" type="number" min="1" .value=${String(r.interval)}
              @change=${(e: any) => this.patchRep({ interval: +e.target.value || 1 })}></span>` : nothing}
          </div>
          ${r.freq === 'WEEKLY' ? html`<div class="days">${WEEKDAYS.map(d => html`<button type="button" class="day ${r.byday.includes(d) ? 'on' : ''}"
            @click=${() => this.toggleDay(d)}>${WEEKDAY_LABELS[d]}</button>`)}</div>` : nothing}
          ${r.freq === 'custom' ? html`<input class="mono" .value=${r.raw} placeholder="FREQ=WEEKLY;BYDAY=MO,WE;BYHOUR=3"
            @change=${(e: any) => this.patchRep({ raw: e.target.value })}>` : nothing}
          ${r.freq !== 'none' && r.freq !== 'custom' ? html`<div class="rep end">
            <span class="inl">Fine: <input type="date" style="width:auto" .value=${r.until || ''} @change=${(e: any) => this.patchRep({ until: e.target.value, count: null })}></span>
            <span class="inl">oppure dopo <input class="num" type="number" min="1" .value=${r.count ? String(r.count) : ''}
              @change=${(e: any) => this.patchRep({ count: +e.target.value || null, until: '' })}> volte</span></div>` : nothing}`,
          { hint: describeRRule(buildRRule(r)) })}
        ${this.field('Descrizione', html`<textarea rows="3" .value=${f.description} @input=${(e: any) => this.set('description', e.target.value)}></textarea>`)}
        ${f.type === 'task' || f.type === 'job' ? html`<details class="adv" ?open=${!!f.svc}>
          <summary>Azione da eseguire (via Hub)</summary>
          <div class="row3">
            ${this.field('Servizio', html`<input .value=${f.svc} placeholder="scout" @input=${(e: any) => this.set('svc', e.target.value)}>`)}
            ${this.field('Metodo', html`<select @change=${(e: any) => this.set('method', e.target.value)}>
              ${['POST', 'GET', 'PUT', 'PATCH', 'DELETE'].map(m => html`<option ?selected=${m === f.method}>${m}</option>`)}</select>`)}
            ${this.field('Percorso', html`<input class="mono" .value=${f.path} placeholder="/api/scout/cycle" @input=${(e: any) => this.set('path', e.target.value)}>`)}
          </div>
          ${this.field('Body JSON', html`<textarea class="mono" rows="3" .value=${f.body} placeholder='{"trigger": "agenda"}'
            @input=${(e: any) => this.set('body', e.target.value)}></textarea>`, { err: er.body })}
        </details>` : nothing}
        ${this.editing && s.item?.created_by !== 'user' ? html`<p class="note">Questa voce è di <b>${s.item?.owner}</b>: dopo la tua modifica il modulo non la sovrascriverà più.</p>` : nothing}
        <button type="submit" hidden></button>
      </form>` : nothing}
      <div slot="footer" style="display:flex;gap:8px;width:100%;flex-wrap:wrap">
        ${this.editing ? nothing : html`<hxk-button class="ask" variant="ghost" icon="sparkle" title="Descrivi a parole cosa vuoi: Hestia crea la voce"
          @click=${() => this.ask()}>Chiedi a Hestia</hxk-button>`}
        <span style="flex:1"></span>
        <hxk-button variant="ghost" @click=${() => fire(this, 'close')}>Annulla</hxk-button>
        <hxk-button variant="primary" @click=${() => this.save()}>${this.editing ? 'Salva' : 'Crea'}</hxk-button>
      </div>
    </chronos-dialog>`;
  }
}
