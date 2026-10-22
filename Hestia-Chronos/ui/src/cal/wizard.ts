/**
 * <chronos-cal-wizard> — "Da un modulo…": modules declare what can be created for them (AgendaTemplate, registered
 * with hestia_common.agenda_client.template). Steps: 1 pick · 2 fields + when · 3 review. `seed` = suggested start
 * (null = closed). Events: cal-template ({tpl, body}), close. Ported from the WebUI's template-wizard component.
 */
import { LitElement, css, html, nothing, tokens, kitStyles } from '@hestia/webui-sdk';
import type { AgendaApi, TemplateBody } from './api';
import { type AgendaTemplate, type AgendaType, TYPE_META, fire, ownerLabel } from './models';
import { addMinutes, fmt, fromLocalInput, toLocalInput } from './date';
import { calStyles, ic, segmented } from './ui';
import { formStyles } from './editor';

export interface TemplateCreate { tpl: AgendaTemplate; body: TemplateBody; }
type Freq = 'HOURLY' | 'DAILY' | 'WEEKLY' | 'MONTHLY';
const UNIT1: Record<Freq, string> = { HOURLY: 'ora', DAILY: 'giorno', WEEKLY: 'settimana', MONTHLY: 'mese' };
const UNITN: Record<Freq, string> = { HOURLY: 'ore', DAILY: 'giorni', WEEKLY: 'settimane', MONTHLY: 'mesi' };

export class ChronosCalWizard extends LitElement {
  static properties = { seed: { attribute: false }, api: { attribute: false }, step: { state: true }, loading: { state: true },
                        templates: { state: true }, tpl: { state: true }, values: { state: true }, type: { state: true },
                        start: { state: true }, end: { state: true }, freq: { state: true }, interval: { state: true }, error: { state: true } };
  declare seed: Date | null; declare api: AgendaApi; declare step: number; declare loading: boolean;
  declare templates: AgendaTemplate[]; declare tpl: AgendaTemplate | null; declare values: Record<string, unknown>;
  declare type: AgendaType; declare start: string; declare end: string; declare freq: Freq; declare interval: number; declare error: string;
  private loadedFor: Date | null = null;
  static styles = [tokens, kitStyles, calStyles, formStyles, css`
    .steps { display: flex; gap: 14px; font-size: 12px; color: var(--text-3); margin-bottom: 14px; flex-wrap: wrap; }
    .steps .on { color: var(--accent); font-weight: 600; } .steps .done { color: var(--text-2); }
    h4 { font-size: 11.5px; text-transform: uppercase; letter-spacing: .05em; color: var(--text-3); margin: 10px 0 6px; }
    .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 8px; }
    .card { display: flex; gap: 10px; align-items: flex-start; text-align: left; padding: 12px; border: 1px solid var(--border);
      border-radius: var(--radius-lg); background: var(--surface); }
    .card:hover { border-color: var(--accent); background: var(--accent-soft); }
    .card .ic { color: var(--accent); margin-top: 2px; }
    .ct { display: flex; flex-direction: column; gap: 3px; font-size: 13px; } .ct span { color: var(--text-3); font-size: 12px; }
    .rep { display: flex; align-items: center; gap: 8px; font-size: 13px; } .rep select { width: 140px; }
    .err { color: var(--danger); font-size: 13px; margin: 0; }
    .review { display: grid; grid-template-columns: 120px 1fr; gap: 8px 12px; font-size: 13.5px; margin: 0; }
    .review dt { color: var(--text-3); } .review dd { margin: 0; white-space: pre-wrap; }
    .hint { font-size: 12.5px; color: var(--text-3); margin-top: 14px; }
  `];

  constructor() {
    super(); this.seed = null; this.step = 0; this.loading = false; this.templates = []; this.tpl = null; this.values = {};
    this.type = 'task'; this.start = ''; this.end = ''; this.freq = 'DAILY'; this.interval = 1; this.error = '';
  }

  willUpdate() {
    const s = this.seed;
    if (!s || s === this.loadedFor) return;
    this.loadedFor = s;
    this.step = 0; this.tpl = null; this.error = '';
    this.start = toLocalInput(s); this.end = toLocalInput(addMinutes(s, 60));
    void this.load();
  }

  private async load() {
    this.loading = true;
    try { this.templates = await this.api.templates(); } catch { this.templates = []; } finally { this.loading = false; }
  }

  private fields() {
    const t = this.tpl; if (!t) return [];
    return Object.entries(t.fields ?? {}).map(([name, spec]) => ({ name, spec, required: (t.required ?? []).includes(name),
      label: spec.label || (name.charAt(0).toUpperCase() + name.slice(1)).replace(/_/g, ' ') }));
  }

  private pick(t: AgendaTemplate) {
    this.tpl = t;
    const v: Record<string, unknown> = {};
    for (const [k, f] of Object.entries(t.fields ?? {})) if (f.default !== undefined) v[k] = f.default;
    this.values = v; this.type = t.type;
    if (t.type === 'window' && t.duration_minutes) {
      const s = fromLocalInput(this.start); if (s) this.end = toLocalInput(addMinutes(s, t.duration_minutes));
    }
    this.step = 1;
  }
  private setValue(k: string, v: unknown) { this.values = { ...this.values, [k]: v }; }
  private back() { this.step = Math.max(0, this.step - 1); if (this.step === 0) this.tpl = null; }

  private next() {
    const t = this.tpl!, s = fromLocalInput(this.start), e = fromLocalInput(this.end);
    const missing = (t.required ?? []).filter(k => this.values[k] === undefined || this.values[k] === '');
    if (missing.length) { this.error = `Compila: ${missing.join(', ')}`; return; }
    if (!s) { this.error = 'Indica quando'; return; }
    if (this.type === 'window' && (!e || e <= s)) { this.error = 'La fine della finestra deve essere dopo l\'inizio'; return; }
    this.error = ''; this.step = 2;
  }

  private rrule(): string | null {
    return this.type === 'job' || this.type === 'window' ? `FREQ=${this.freq};INTERVAL=${this.interval}` : null;
  }
  private whenText(): string {
    const s = fromLocalInput(this.start); if (!s) return '';
    const e = fromLocalInput(this.end);
    const base = this.type === 'window' && e ? `${fmt.dateTime(s)} – ${fmt.time(e)}` : fmt.dateTime(s);
    const unit = this.interval === 1 ? UNIT1[this.freq] : `${this.interval} ${UNITN[this.freq]}`;
    return this.type === 'task' ? base : `${base}, poi ogni ${unit}`;
  }

  private create() {
    const t = this.tpl!, s = fromLocalInput(this.start)!, e = this.type === 'window' ? fromLocalInput(this.end) : null;
    fire(this, 'cal-template', { tpl: t, body: { values: this.values, start_at: s.toISOString(), end_at: e ? e.toISOString() : null,
                                                 recurrence: this.rrule(), type: this.type } } as TemplateCreate);
  }

  private input(f: { name: string; spec: AgendaTemplate['fields'][string] }) {
    const v = this.values[f.name];
    if (f.spec.enum?.length) return html`<select @change=${(e: any) => this.setValue(f.name, e.target.value)}>
      ${f.spec.enum.map(o => html`<option value=${o} ?selected=${o === (v ?? '')}>${o || '(predefinito)'}</option>`)}</select>`;
    if (f.spec.type === 'integer' || f.spec.type === 'number')
      return html`<input type="number" .value=${v === undefined ? '' : String(v)} @change=${(e: any) => this.setValue(f.name, +e.target.value)}>`;
    if (f.spec.type === 'boolean')
      return html`<span class="inl"><input type="checkbox" class="chk" .checked=${!!v} @change=${(e: any) => this.setValue(f.name, e.target.checked)}> Sì</span>`;
    if (f.spec.format === 'textarea')
      return html`<textarea rows="3" .value=${String(v ?? '')} @input=${(e: any) => this.setValue(f.name, e.target.value)}></textarea>`;
    return html`<input .value=${String(v ?? '')} @input=${(e: any) => this.setValue(f.name, e.target.value)}>`;
  }

  private body() {
    if (this.step === 0) {
      if (this.loading) return html`<hxk-state kind="loading"></hxk-state>`;
      if (!this.templates.length) return html`<hxk-state kind="empty" text="Nessun modello dai moduli: li dichiarano quando sono avviati (si aggiorna entro un'ora). Usa intanto «Evento libero»."></hxk-state>`;
      const groups = new Map<string, AgendaTemplate[]>();
      for (const t of this.templates) (groups.get(t.owner) ?? groups.set(t.owner, []).get(t.owner)!).push(t);
      return html`${[...groups.entries()].map(([owner, items]) => html`<h4>${ownerLabel(owner)}</h4><div class="cards">
        ${items.map(t => html`<button class="card" @click=${() => this.pick(t)}>${ic(t.icon || 'zap', 18)}
          <span class="ct"><b>${t.label}</b><span>${t.description ?? ''}</span></span></button>`)}</div>`)}
        <p class="hint">Hai eliminato un'attività che un modulo aveva messo da solo (es. il recap della sera)? Rimettila
          com'era da Agenda → «Attività standard».</p>`;
    }
    const t = this.tpl; if (!t) return nothing;
    if (this.step === 1) {
      const typeOpts = (t.types ?? []).map(x => ({ value: x, label: x === 'task' ? 'Una volta' : x === 'job' ? 'Ripetuto' : TYPE_META[x].label }));
      return html`<div class="form">
        ${this.fields().map(f => html`<label class="f"><span>${f.label}${f.required ? html` <b>*</b>` : nothing}</span>${this.input(f)}
          ${f.spec.description ? html`<span class="hint">${f.spec.description}</span>` : nothing}</label>`)}
        ${t.types.length > 1 ? html`<div class="f"><span>Tipo</span>${segmented(typeOpts, this.type, v => (this.type = v))}</div>` : nothing}
        <div class="row2">
          <label class="f"><span>${this.type === 'window' ? 'Inizio finestra' : 'Quando'} <b>*</b></span>
            <input type="datetime-local" .value=${this.start} @change=${(e: any) => (this.start = e.target.value)}></label>
          ${this.type === 'window' ? html`<label class="f"><span>Fine finestra <b>*</b></span>
            <input type="datetime-local" .value=${this.end} @change=${(e: any) => (this.end = e.target.value)}></label>` : nothing}
        </div>
        ${this.type === 'job' || this.type === 'window' ? html`<div class="f"><span>Ripeti</span><div class="rep">ogni
          <input class="num" type="number" min="1" max="999" .value=${String(this.interval)} @change=${(e: any) => (this.interval = +e.target.value || 1)}>
          <select @change=${(e: any) => (this.freq = e.target.value)}>${(Object.keys(UNITN) as Freq[]).map(k =>
            html`<option value=${k} ?selected=${k === this.freq}>${UNITN[k]}</option>`)}</select></div></div>` : nothing}
        ${this.error ? html`<p class="err">${this.error}</p>` : nothing}
      </div>`;
    }
    return html`<dl class="review">
        <dt>Modulo</dt><dd>${ownerLabel(t.owner)} · ${t.label}</dd>
        <dt>Tipo</dt><dd>${TYPE_META[this.type].label}</dd>
        <dt>Quando</dt><dd>${this.whenText()}</dd>
        ${this.fields().filter(f => this.values[f.name] !== undefined && this.values[f.name] !== '')
          .map(f => html`<dt>${f.label}</dt><dd>${String(this.values[f.name])}</dd>`)}
      </dl>
      <p class="hint">La voce sarà "tua" (sempre visibile, mai sovrascritta dal modulo) e il modulo la eseguirà all'orario indicato.</p>`;
  }

  render() {
    const t = this.tpl;
    return html`<chronos-dialog .open=${!!this.seed} heading=${t ? `${ownerLabel(t.owner)} · ${t.label}` : 'Crea da un modulo'} size="lg"
        @close=${() => fire(this, 'close')}>
      ${this.seed ? html`<div class="steps">${['Scegli', 'Dettagli', 'Conferma'].map((s, i) =>
        html`<span class="${this.step === i ? 'on' : this.step > i ? 'done' : ''}">${i + 1} · ${s}</span>`)}</div>${this.body()}` : nothing}
      <div slot="footer" style="display:flex;gap:8px;width:100%;align-items:center">
        ${this.step > 0 ? html`<hxk-button variant="ghost" icon="chevron-left" @click=${() => this.back()}>Indietro</hxk-button>` : nothing}
        <span style="flex:1"></span>
        <hxk-button variant="ghost" @click=${() => fire(this, 'close')}>Annulla</hxk-button>
        ${this.step === 1 ? html`<hxk-button variant="primary" @click=${() => this.next()}>Avanti</hxk-button>` : nothing}
        ${this.step === 2 ? html`<hxk-button variant="primary" icon="check" @click=${() => this.create()}>Crea</hxk-button>` : nothing}
      </div>
    </chronos-dialog>`;
  }
}
