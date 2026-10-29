/**
 * Demeter («Alimentazione») WebUI plugin (plugin contract docs/work/2026-10-17-client-plugins/SPEC.md §4; dossier
 * docs/work/2026-10-24-tutto-brainstorm-cindy W7). Pages and widget declared in Hestia-Demeter/app/main.py.
 */
import { HestiaElement, css, definePlugin, html, nothing } from '@hestia/webui-sdk';
import type { ApiResult, HestiaHost, HttpMethod } from '@hestia/webui-sdk';

const API = '/api/food';
const SLOTS: Record<string, string> = { colazione: 'Colazione', pranzo: 'Pranzo', cena: 'Cena', spuntino: 'Spuntino' };
const TIMES: Record<string, string> = { morning: 'Mattina', midday: 'Pranzo', afternoon: 'Pomeriggio', evening: 'Sera', any: 'Quando vuoi' };
const WEEK = ['Lun', 'Mar', 'Mer', 'Gio', 'Ven', 'Sab', 'Dom'];

async function call<T = any>(host: HestiaHost, method: HttpMethod, path: string, body?: unknown, query?: Record<string, any>): Promise<ApiResult<T>> {
  const r = await host.api<T>(method, `${API}${path}`, { body, query });
  if (!r.ok && method !== 'GET') host.toast(r.status === 0 ? 'Non raggiungibile, riprova' : r.error || 'Errore', 'warning');
  return r;
}
const localDay = (d = new Date()) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const shift = (iso: string, n: number) => { const d = new Date(iso + 'T12:00:00'); d.setDate(d.getDate() + n); return localDay(d); };
const dayTitle = (iso: string) => iso === localDay() ? 'Oggi' : iso === shift(localDay(), -1) ? 'Ieri'
  : new Date(iso + 'T12:00:00').toLocaleDateString('it-IT', { weekday: 'long', day: 'numeric', month: 'long' });

const styles = css`
  .between { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
  .click { cursor: pointer; }
  .bar { height: 8px; border-radius: 99px; background: var(--surface-2); overflow: hidden; }
  .bar > i { display: block; height: 100%; background: var(--accent); border-radius: 99px; }
  .bar.over > i { background: var(--warning); }
  .meal { display: flex; gap: 10px; align-items: center; padding: 8px 2px; border-bottom: 1px solid var(--border); }
  .meal:last-child { border-bottom: 0; }
  .form { display: grid; gap: 10px; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); }
  .days { display: flex; gap: 4px; flex-wrap: wrap; }
  .day { padding: 3px 8px; border-radius: 99px; border: 1px solid var(--border-strong); cursor: pointer; font-size: 12px; }
  .day.on { background: var(--accent); color: var(--accent-contrast); border-color: var(--accent); }
`;

function progress(value: number, target: number | null, unit: string) {
  if (!target) return html`<div class="small muted">${value} ${unit}</div>`;
  const pct = Math.min(100, Math.round(100 * value / target));
  return html`<div class="col" style="gap:4px"><div class="between small"><span>${value} / ${target} ${unit}</span><span class="muted">${Math.round(100 * value / target)}%</span></div>
    <div class="bar ${value > target ? 'over' : ''}"><i style="width:${pct}%"></i></div></div>`;
}

export class DemeterToday extends HestiaElement {
  static properties = { ...HestiaElement.properties, s: { state: true }, day: { state: true }, text: { state: true }, slot: { state: true }, edit: { state: true } };
  declare s: any;
  declare day: string;
  declare text: string;
  declare slot: string;
  declare edit: string;
  static styles = [...HestiaElement.styles, styles];
  constructor() { super(); this.s = undefined; this.day = localDay(); this.text = ''; this.slot = ''; this.edit = ''; }
  connectedCallback() { super.connectedCallback(); this.load(); this.onHost('refresh', () => this.load()); }
  async load() { const r = await call(this.host, 'GET', '/today', undefined, { day: this.day }); this.s = r.ok ? r.data : null; }
  private go(n: number) { this.day = shift(this.day, n); this.load(); }
  private async add() {
    if (!this.text.trim()) return;
    const r = await call(this.host, 'POST', '/meals', { text: this.text, slot: this.slot, date: this.day });
    if (r.ok) {
      this.text = '';
      this.host.toast(r.data.kcal === null ? 'Segnato: le calorie le stima l\'assistente' : 'Segnato', 'success',
        { label: 'Annulla', run: async () => { await call(this.host, 'DELETE', `/meals/${r.data.id}`); this.load(); } });
      this.load();
      if (r.data.kcal === null) setTimeout(() => this.load(), 8000);
    }
  }
  private async saveMeal(m: any, patch: any) { const r = await call(this.host, 'PUT', `/meals/${m.id}`, patch); if (r.ok) { this.edit = ''; this.load(); } }
  private async take(s: any) { const r = await call(this.host, 'POST', `/supplements/${s.id}/take`, { date: this.day }); if (r.ok) this.load(); }
  render() {
    const s = this.s;
    if (s === undefined) return html`<hxk-state kind="loading"></hxk-state>`;
    if (s === null) return html`<hxk-state kind="offline" @retry=${() => this.load()}></hxk-state>`;
    const bySlot = Object.keys(SLOTS).map(k => [k, s.meals.filter((m: any) => m.slot === k)] as [string, any[]]).filter(([, m]) => m.length);
    return html`<div class="page">
      <div class="between"><h1>${dayTitle(this.day)}</h1>
        <div class="row"><hxk-button variant="ghost" icon="chevron-left" @click=${() => this.go(-1)}></hxk-button>
          ${this.day !== localDay() ? html`<hxk-button variant="ghost" @click=${() => { this.day = localDay(); this.load(); }}>Oggi</hxk-button>` : nothing}
          <hxk-button variant="ghost" icon="chevron-right" ?disabled=${this.day >= localDay()} @click=${() => this.go(1)}></hxk-button></div></div>
      <div class="grid" style="--min: 240px">
        <div class="card col"><h3>Calorie</h3>${progress(s.kcal, s.kcal_target, 'kcal')}
          ${s.unknown ? html`<div class="small muted">${s.unknown} past${s.unknown === 1 ? 'o' : 'i'} ancora da stimare</div>` : nothing}</div>
        <div class="card col"><h3>Proteine</h3>${progress(s.protein, s.protein_target, 'g')}</div>
        ${s.supplements.length ? html`<div class="card col"><h3>Integratori</h3>${s.supplements.map((x: any) => html`<div class="between small">
          <span>${x.name}${x.dose ? html` <span class="muted">${x.dose}</span>` : nothing} · <span class="muted">${TIMES[x.time_of_day] || ''}</span></span>
          ${x.taken ? html`<hxk-badge tone="success">preso</hxk-badge>` : html`<hxk-button size="sm" icon="check" @click=${() => this.take(x)}>Preso</hxk-button>`}</div>`)}</div>` : nothing}
      </div>
      <div class="card col"><h3>Cosa hai mangiato</h3>
        <div class="row wrap"><input class="grow" placeholder="Es. pasta al pomodoro e insalata" .value=${this.text}
            @input=${(e: any) => { this.text = e.target.value; }} @keydown=${(e: KeyboardEvent) => { if (e.key === 'Enter') this.add(); }}>
          <select @change=${(e: any) => { this.slot = e.target.value; }}><option value="">Pasto</option>
            ${Object.entries(SLOTS).map(([k, v]) => html`<option value=${k} ?selected=${this.slot === k}>${v}</option>`)}</select>
          <hxk-button variant="primary" icon="plus" @click=${() => this.add()}>Segna</hxk-button></div>
        ${bySlot.length ? bySlot.map(([k, list]) => html`<div class="small muted" style="margin-top:6px">${SLOTS[k]}</div>
          ${list.map(m => this.edit === m.id ? html`<div class="meal"><div class="form grow">
              <hxk-field label="Cosa" .value=${m.text} @change=${(e: any) => { m.text = e.detail; }}></hxk-field>
              <hxk-field label="kcal" type="int" .value=${m.kcal ?? ''} @change=${(e: any) => { m.kcal = e.detail; }}></hxk-field>
              <hxk-field label="Proteine" type="int" unit="g" .value=${m.protein ?? ''} @change=${(e: any) => { m.protein = e.detail; }}></hxk-field></div>
              <hxk-button size="sm" variant="primary" @click=${() => this.saveMeal(m, { text: m.text, kcal: m.kcal, protein: m.protein })}>Salva</hxk-button></div>`
            : html`<div class="meal"><span class="grow">${m.text}</span>
              <span class="small muted">${m.kcal === null ? 'stima in corso' : `${m.estimated ? '≈ ' : ''}${m.kcal} kcal${m.protein !== null ? ` · ${m.protein} g` : ''}`}</span>
              <hxk-button size="sm" variant="ghost" icon="edit" @click=${() => { this.edit = m.id; }}></hxk-button>
              <hxk-button size="sm" variant="ghost" icon="trash" @click=${async () => { await call(this.host, 'DELETE', `/meals/${m.id}`); this.load(); }}></hxk-button></div>`)}`)
          : html`<div class="small muted">Ancora niente. Puoi anche dirlo in chat: «a pranzo ho mangiato…».</div>`}
      </div>
    </div>`;
  }
}

export class DemeterDiet extends HestiaElement {
  static properties = { ...HestiaElement.properties, d: { state: true } };
  declare d: any;
  static styles = [...HestiaElement.styles, styles];
  constructor() { super(); this.d = undefined; }
  connectedCallback() { super.connectedCallback(); this.load(); }
  async load() { const r = await call(this.host, 'GET', '/diet'); this.d = r.ok ? { ...r.data, rules: (r.data.rules || []).join('\n') } : null; }
  private async save() { const r = await call(this.host, 'PUT', '/diet', this.d); if (r.ok) { this.host.toast('Dieta salvata: il piano della settimana si aggiorna', 'success'); this.load(); } }
  render() {
    const d = this.d;
    if (d === undefined) return html`<hxk-state kind="loading"></hxk-state>`;
    if (d === null) return html`<hxk-state kind="offline" @retry=${() => this.load()}></hxk-state>`;
    const set = (k: string) => (e: any) => { this.d = { ...this.d, [k]: e.detail }; };
    return html`<div class="page"><h1>Dieta</h1>
      <div class="card col"><div class="form">
          <hxk-field label="Calorie al giorno" type="int" unit="kcal" .value=${d.kcal ?? ''} @change=${set('kcal')}></hxk-field>
          <hxk-field label="Proteine al giorno" type="int" unit="g" .value=${d.protein ?? ''} @change=${set('protein')}></hxk-field></div>
        <hxk-field label="Regole (una per riga)" type="textarea" placeholder="Es. niente zuccheri la sera" .value=${d.rules} @change=${set('rules')}></hxk-field>
        <hxk-field label="Note" type="textarea" .value=${d.notes || ''} @change=${set('notes')}></hxk-field>
        <div><hxk-button variant="primary" @click=${() => this.save()}>Salva</hxk-button></div>
        <div class="small muted">Le regole valgono anche per i consigli dell'assistente e per il piano della settimana.</div></div>
    </div>`;
  }
}

export class DemeterSupplements extends HestiaElement {
  static properties = { ...HestiaElement.properties, items: { state: true }, draft: { state: true } };
  declare items: any[] | null | undefined;
  declare draft: any;
  static styles = [...HestiaElement.styles, styles];
  constructor() { super(); this.items = undefined; this.draft = null; }
  connectedCallback() { super.connectedCallback(); this.load(); }
  async load() { const r = await call(this.host, 'GET', '/supplements', undefined, { all: true }); this.items = r.ok ? r.data.items : null; }
  private async save() {
    const d = this.draft;
    const r = d.id ? await call(this.host, 'PUT', `/supplements/${d.id}`, d) : await call(this.host, 'POST', '/supplements', d);
    if (r.ok) { this.draft = null; this.host.toast('Salvato: è nel piano della settimana', 'success'); this.load(); }
  }
  private editor() {
    const d = this.draft;
    const set = (k: string, v: any) => { this.draft = { ...this.draft, [k]: v }; };
    const days: number[] = d.days || [];
    return html`<div class="card col">
      <div class="form"><hxk-field label="Nome" .value=${d.name || ''} @change=${(e: any) => set('name', e.detail)}></hxk-field>
        <hxk-field label="Dose" placeholder="Es. 1 compressa" .value=${d.dose || ''} @change=${(e: any) => set('dose', e.detail)}></hxk-field>
        <hxk-field label="Quando" type="enum" .options=${Object.entries(TIMES).map(([value, label]) => ({ value, label }))} .value=${d.time_of_day || 'morning'} @change=${(e: any) => set('time_of_day', e.detail)}></hxk-field></div>
      <div class="col" style="gap:4px"><span class="small muted">Giorni (nessuno = ogni giorno)</span>
        <div class="days">${WEEK.map((w, i) => html`<span class="day ${days.includes(i) ? 'on' : ''}" @click=${() => set('days', days.includes(i) ? days.filter(x => x !== i) : [...days, i])}>${w}</span>`)}</div></div>
      <div class="row wrap"><hxk-field label="Solo nei giorni di allenamento" type="bool" .value=${!!d.training_days_only} @change=${(e: any) => set('training_days_only', e.detail)}></hxk-field>
        <hxk-field label="Con il cibo" type="bool" .value=${!!d.with_food} @change=${(e: any) => set('with_food', e.detail)}></hxk-field></div>
      <div class="row"><hxk-button variant="primary" @click=${() => this.save()}>Salva</hxk-button><hxk-button variant="ghost" @click=${() => { this.draft = null; }}>Annulla</hxk-button></div>
    </div>`;
  }
  render() {
    if (this.items === undefined) return html`<hxk-state kind="loading"></hxk-state>`;
    if (this.items === null) return html`<hxk-state kind="offline" @retry=${() => this.load()}></hxk-state>`;
    return html`<div class="page">
      <div class="between"><h1>Integratori</h1><hxk-button variant="primary" icon="plus" @click=${() => { this.draft = { time_of_day: 'morning', days: [] }; }}>Aggiungi</hxk-button></div>
      ${this.draft ? this.editor() : nothing}
      <div class="card">${this.items.length ? this.items.map(s => html`<div class="meal">
          <div class="grow"><div>${s.name}${s.dose ? html` <span class="muted small">${s.dose}</span>` : nothing}</div>
            <div class="small muted">${TIMES[s.time_of_day]}${s.days?.length ? ' · ' + s.days.map((i: number) => WEEK[i]).join(' ') : ' · ogni giorno'}${s.training_days_only ? ' · giorni di allenamento' : ''}</div></div>
          ${s.status === 'paused' ? html`<hxk-badge>in pausa</hxk-badge>` : nothing}
          <hxk-button size="sm" variant="ghost" @click=${async () => { await call(this.host, 'PUT', `/supplements/${s.id}`, { status: s.status === 'paused' ? 'active' : 'paused' }); this.load(); }}>${s.status === 'paused' ? 'Riprendi' : 'Pausa'}</hxk-button>
          <hxk-button size="sm" variant="ghost" icon="edit" @click=${() => { this.draft = { ...s }; }}></hxk-button>
          <hxk-button size="sm" variant="ghost" icon="trash" @click=${async () => { if (await this.host.confirm('Eliminare?', s.name, { label: 'Elimina', danger: true })) { await call(this.host, 'DELETE', `/supplements/${s.id}`); this.load(); } }}></hxk-button>
        </div>`) : html`<hxk-state kind="empty" text="Nessun integratore. I prodotti per la cura di sé restano nella loro sezione: qui segni cosa prendi e quando."></hxk-state>`}</div>
    </div>`;
  }
}

export class DemeterWidget extends HestiaElement {
  static properties = { ...HestiaElement.properties, s: { state: true } };
  declare s: any;
  static styles = [...HestiaElement.styles, styles, css`:host { display: block; height: 100%; }`];
  constructor() { super(); this.s = undefined; }
  connectedCallback() { super.connectedCallback(); this.load(); this.onHost('refresh', () => this.load()); this.onHost('visible', () => this.load()); }
  async load() { const r = await call(this.host, 'GET', '/today'); this.s = r.ok ? r.data : null; }
  render() {
    const s = this.s;
    if (s === undefined) return html`<hxk-state kind="loading"></hxk-state>`;
    if (s === null) return html`<hxk-state kind="offline" @retry=${() => this.load()}></hxk-state>`;
    const todo = s.supplements.filter((x: any) => !x.taken);
    return html`<div class="col click" style="gap:8px" @click=${() => this.host.navigate('oggi')}>
      <span class="small muted">Alimentazione di oggi</span>
      ${progress(s.kcal, s.kcal_target, 'kcal')}
      ${this.ctx?.size !== 's' ? html`<div class="small muted">${s.meals.length} past${s.meals.length === 1 ? 'o' : 'i'}${todo.length ? ` · da prendere: ${todo.map((x: any) => x.name).join(', ')}` : ''}</div>` : nothing}
    </div>`;
  }
}

definePlugin({ 'demeter-today': DemeterToday, 'demeter-diet': DemeterDiet, 'demeter-supplements': DemeterSupplements, 'demeter-widget': DemeterWidget });
