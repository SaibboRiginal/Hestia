/**
 * Kairos («Scadenze») WebUI plugin (plugin contract docs/work/2026-10-17-client-plugins/SPEC.md §4; dossier
 * docs/work/2026-10-24-tutto-brainstorm-cindy W7). Pages and widget declared in Hestia-Kairos/app/main.py.
 */
import { HestiaElement, css, definePlugin, html, nothing } from '@hestia/webui-sdk';
import type { ApiResult, HestiaHost, HttpMethod } from '@hestia/webui-sdk';

const API = '/api/deadlines';
const RECURRENCE: Record<string, string> = { none: 'una volta', monthly: 'ogni mese', bimonthly: 'ogni 2 mesi',
  quarterly: 'ogni 3 mesi', semiannual: 'ogni 6 mesi', yearly: 'ogni anno', biennial: 'ogni 2 anni' };

async function call<T = any>(host: HestiaHost, method: HttpMethod, path: string, body?: unknown, query?: Record<string, any>): Promise<ApiResult<T>> {
  const r = await host.api<T>(method, `${API}${path}`, { body, query });
  if (!r.ok && method !== 'GET') host.toast(r.status === 0 ? 'Non raggiungibile, riprova' : r.error || 'Errore', 'warning');
  return r;
}
const money = (x: number | null | undefined) => x === null || x === undefined ? '' : Number(x).toLocaleString('it-IT', { style: 'currency', currency: 'EUR' });
const dayLabel = (iso: string) => new Date(iso + 'T12:00:00').toLocaleDateString('it-IT', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' });
const when = (n: number) => n < 0 ? `scaduta da ${-n} g` : n === 0 ? 'oggi' : n === 1 ? 'domani' : `tra ${n} giorni`;
const tone = (n: number, lead: number) => n < 0 ? 'danger' : n <= Math.min(lead, 7) ? 'warning' : 'neutral';

const styles = css`
  .between { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
  .click { cursor: pointer; }
  .dl { display: flex; gap: 12px; align-items: center; padding: 10px 4px; border-bottom: 1px solid var(--border); }
  .dl:last-child { border-bottom: 0; }
  .form { display: grid; gap: 10px; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); }
  .advice { background: var(--accent-soft); border-radius: var(--radius-sm); padding: 8px 10px; font-size: 13px; }
`;

class Base extends HestiaElement {
  static properties = { ...HestiaElement.properties, cats: { state: true } };
  declare cats: any[];
  constructor() { super(); this.cats = []; }
  protected async loadCats() { if (!this.cats.length) { const r = await call(this.host, 'GET', '/categories'); this.cats = r.ok ? r.data.categories : []; } }
  protected form(d: Record<string, any>, set: (k: string, v: any) => void) {
    return html`<div class="form">
      <hxk-field label="Cosa" placeholder="Es. Bollo auto" .value=${d.title || ''} @change=${(e: any) => set('title', e.detail)}></hxk-field>
      <hxk-field label="Scade il" type="date" .value=${d.due || ''} @change=${(e: any) => set('due', e.detail)}></hxk-field>
      <hxk-field label="Tipo" type="enum" .options=${[{ value: '', label: 'Lo capisco io' }, ...this.cats.map(c => ({ value: c.key, label: c.label }))]}
        .value=${d.category || ''} @change=${(e: any) => set('category', e.detail)}></hxk-field>
      <hxk-field label="Si ripete" type="enum" .options=${Object.entries(RECURRENCE).map(([value, label]) => ({ value, label }))}
        .value=${d.recurrence || 'none'} @change=${(e: any) => set('recurrence', e.detail)}></hxk-field>
      <hxk-field label="Importo" type="float" unit="€" .value=${d.amount ?? ''} @change=${(e: any) => set('amount', e.detail)}></hxk-field>
      <hxk-field label="Avvisami" type="int" unit="giorni prima" .value=${d.lead_days ?? ''} @change=${(e: any) => set('lead_days', e.detail)}></hxk-field>
    </div>`;
  }
}

export class KairosList extends Base {
  static properties = { ...Base.properties, items: { state: true }, proposed: { state: true }, adding: { state: true }, draft: { state: true }, done: { state: true } };
  declare items: any[] | null | undefined;
  declare proposed: any[];
  declare adding: boolean;
  declare draft: Record<string, any>;
  declare done: boolean;
  static styles = [...HestiaElement.styles, styles];
  constructor() { super(); this.items = undefined; this.proposed = []; this.adding = false; this.draft = {}; this.done = false; }
  connectedCallback() { super.connectedCallback(); this.load(); this.loadCats(); this.onHost('refresh', () => this.load()); }
  async load() {
    const [o, p] = await Promise.all([call(this.host, 'GET', '', undefined, { status: this.done ? 'done' : 'open' }),
                                      call(this.host, 'GET', '', undefined, { status: 'proposed' })]);
    this.items = o.ok ? o.data.items : null;
    this.proposed = p.ok ? p.data.items : [];
  }
  private async save() {
    const r = await call(this.host, 'POST', '', this.draft);
    if (r.ok) { this.adding = false; this.draft = {}; this.host.toast('Scadenza salvata, è anche nel calendario', 'success'); this.load(); }
  }
  private async act(d: any, what: 'done' | 'confirm' | 'dismiss' | 'snooze') {
    const r = await call(this.host, 'POST', `/${d.id}/${what}`, what === 'snooze' ? { days: 3 } : {});
    if (!r.ok) return;
    const msg = { done: d.recurrence !== 'none' ? `Fatto: la prossima è ${dayLabel(r.data.due)}` : 'Fatto', confirm: 'Aggiunta', dismiss: 'Scartata', snooze: 'Te la ricordo tra 3 giorni' }[what];
    this.host.toast(msg, 'success');
    this.load();
  }
  private row(d: any) {
    return html`<div class="dl">
      <div class="grow click" @click=${() => this.host.navigate('scadenza/' + d.id)}>
        <div>${d.title}${d.amount ? html` <span class="muted">· ${money(d.amount)}</span>` : nothing}</div>
        <div class="small muted">${d.category_label} · ${dayLabel(d.due)}${d.recurrence !== 'none' ? ` · ${RECURRENCE[d.recurrence]}` : ''}</div></div>
      ${d.status === 'open' ? html`<hxk-badge tone=${tone(d.in_days, d.lead_days)}>${when(d.in_days)}</hxk-badge>
        <hxk-button size="sm" variant="ghost" @click=${() => this.act(d, 'snooze')}>Dopo</hxk-button>
        <hxk-button size="sm" icon="check" @click=${() => this.act(d, 'done')}>Fatto</hxk-button>` : nothing}
      ${d.status === 'proposed' ? html`<hxk-button size="sm" variant="primary" @click=${() => this.act(d, 'confirm')}>Aggiungi</hxk-button>
        <hxk-button size="sm" variant="ghost" @click=${() => this.act(d, 'dismiss')}>Scarta</hxk-button>` : nothing}
    </div>`;
  }
  render() {
    if (this.items === undefined) return html`<hxk-state kind="loading"></hxk-state>`;
    if (this.items === null) return html`<hxk-state kind="offline" @retry=${() => this.load()}></hxk-state>`;
    const soon = this.items.filter(d => d.in_days <= 30);
    const later = this.items.filter(d => d.in_days > 30);
    const total = soon.reduce((s, d) => s + (d.amount || 0), 0);
    return html`<div class="page">
      <div class="between"><h1>Scadenze</h1>
        <div class="row"><hxk-button variant="ghost" @click=${() => { this.done = !this.done; this.load(); }}>${this.done ? 'Da fare' : 'Fatte'}</hxk-button>
          <hxk-button variant="primary" icon="plus" @click=${() => { this.adding = !this.adding; }}>Aggiungi</hxk-button></div></div>
      ${this.adding ? html`<div class="card col">${this.form(this.draft, (k, v) => { this.draft = { ...this.draft, [k]: v }; })}
        <div class="row"><hxk-button variant="primary" @click=${() => this.save()}>Salva</hxk-button>
          <hxk-button variant="ghost" @click=${() => { this.adding = false; }}>Annulla</hxk-button></div></div>` : nothing}
      ${this.proposed.length && !this.done ? html`<div class="card col"><h3>Trovate nelle email</h3>
        <div class="small muted">Le aggiungo solo se confermi.</div>${this.proposed.map(d => this.row(d))}</div>` : nothing}
      ${this.done ? html`<div class="card">${this.items.length ? this.items.map(d => this.row(d)) : html`<hxk-state kind="empty" text="Nessuna scadenza chiusa."></hxk-state>`}</div>` : html`
        ${soon.length ? html`<div class="card col"><div class="between"><h3>Prossimi 30 giorni</h3>${total ? html`<span class="small muted">${money(total)}</span>` : nothing}</div>
          ${soon.map(d => this.row(d))}</div>` : nothing}
        ${later.length ? html`<div class="card col"><h3>Più avanti</h3>${later.map(d => this.row(d))}</div>` : nothing}
        ${!this.items.length ? html`<hxk-state kind="empty" text="Nessuna scadenza: bollette, assicurazione, bollo, revisione, documenti. Aggiungile qui o dillo in chat."></hxk-state>` : nothing}`}
    </div>`;
  }
}

export class KairosDetail extends Base {
  static properties = { ...Base.properties, d: { state: true }, draft: { state: true }, thinking: { state: true } };
  declare d: any;
  declare draft: Record<string, any>;
  declare thinking: boolean;
  static styles = [...HestiaElement.styles, styles];
  constructor() { super(); this.d = undefined; this.draft = {}; this.thinking = false; }
  connectedCallback() { super.connectedCallback(); this.load(); this.loadCats(); }
  private get did() { return this.ctx?.params?.id || ''; }
  async load() { const r = await call(this.host, 'GET', `/${encodeURIComponent(this.did)}`); this.d = r.ok ? r.data : null; this.draft = r.ok ? { ...r.data } : {}; }
  private async save() { const r = await call(this.host, 'PUT', `/${this.did}`, this.draft); if (r.ok) { this.d = r.data; this.host.toast('Salvata', 'success'); } }
  private async advise() {
    this.thinking = true;
    const r = await call(this.host, 'POST', '/tools/consiglio', { deadline: this.did });
    this.thinking = false;
    if (r.ok && r.data.advice) this.d = { ...this.d, advice: r.data.advice };
  }
  private async deleteDeadline() {
    if (!await this.host.confirm('Eliminare la scadenza?', 'Sparisce anche dal calendario.', { label: 'Elimina', danger: true })) return;
    const r = await call(this.host, 'DELETE', `/${this.did}`);
    if (r.ok) this.host.navigate('scadenze');
  }
  render() {
    const d = this.d;
    if (d === undefined) return html`<hxk-state kind="loading"></hxk-state>`;
    if (d === null) return html`<hxk-state kind="error" text="Scadenza non trovata."></hxk-state>`;
    return html`<div class="page">
      <div class="between"><div><h1>${d.title}</h1><div class="small muted">${d.category_label} · ${dayLabel(d.due)} · ${when(d.in_days)}</div></div>
        ${d.status === 'open' ? html`<hxk-button variant="primary" icon="check" @click=${async () => { const r = await call(this.host, 'POST', `/${d.id}/done`); if (r.ok) { this.d = r.data; this.host.toast('Fatto', 'success'); } }}>Fatto</hxk-button>` : html`<hxk-badge>${d.status === 'done' ? 'fatta' : d.status === 'proposed' ? 'da confermare' : d.status}</hxk-badge>`}</div>
      <div class="card col"><div class="between"><h3>Consiglio</h3><hxk-button size="sm" variant="ghost" icon="sparkle" ?loading=${this.thinking} @click=${() => this.advise()}>Chiedi un consiglio</hxk-button></div>
        ${d.advice ? html`<div class="advice">${d.advice}</div>` : html`<div class="small muted">Nessun consiglio per ora.</div>`}</div>
      <div class="card col">${this.form(this.draft, (k, v) => { this.draft = { ...this.draft, [k]: v }; })}
        <hxk-field label="Note" type="textarea" .value=${this.draft.notes || ''} @change=${(e: any) => { this.draft = { ...this.draft, notes: e.detail }; }}></hxk-field>
        <div class="row"><hxk-button variant="primary" @click=${() => this.save()}>Salva</hxk-button>
          <hxk-button variant="danger" icon="trash" @click=${() => this.deleteDeadline()}>Elimina</hxk-button></div></div>
      ${d.last_done ? html`<div class="small muted">Ultima volta fatta: ${dayLabel(d.last_done)}</div>` : nothing}
    </div>`;
  }
}

export class KairosWidget extends HestiaElement {
  static properties = { ...HestiaElement.properties, items: { state: true } };
  declare items: any[] | null | undefined;
  static styles = [...HestiaElement.styles, styles, css`:host { display: block; height: 100%; }`];
  constructor() { super(); this.items = undefined; }
  connectedCallback() { super.connectedCallback(); this.load(); this.onHost('refresh', () => this.load()); this.onHost('visible', () => this.load()); }
  async load() { const r = await call(this.host, 'GET', '', undefined, { status: 'open', days: 30 }); this.items = r.ok ? r.data.items : null; }
  render() {
    if (this.items === undefined) return html`<hxk-state kind="loading"></hxk-state>`;
    if (this.items === null) return html`<hxk-state kind="offline" @retry=${() => this.load()}></hxk-state>`;
    const n = this.ctx?.size === 's' ? 1 : this.ctx?.size === 'm' ? 3 : 6;
    return html`<div class="col" style="gap:6px">
      <div class="between click" @click=${() => this.host.navigate('scadenze')}><span class="small muted">Scadenze</span><span class="small">Tutte ›</span></div>
      ${this.items.length ? this.items.slice(0, n).map(d => html`<div class="between small click" @click=${() => this.host.navigate('scadenza/' + d.id)}>
        <span class="truncate">${d.title}</span><hxk-badge tone=${tone(d.in_days, d.lead_days)}>${when(d.in_days)}</hxk-badge></div>`)
        : html`<div class="small muted">Niente nei prossimi 30 giorni.</div>`}
    </div>`;
  }
}

definePlugin({ 'kairos-list': KairosList, 'kairos-detail': KairosDetail, 'kairos-widget': KairosWidget });
