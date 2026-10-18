/**
 * <hermes-deliveries> — «Consegne»: what Hermes sent to which client (held / quiet / retracted / superseded),
 * the answers, the active subscriptions and the clients reached. Read-only; the inbox is the Notifiche page.
 * SPEC docs/work/2026-10-18-moduli-core-e-mcp-esterno §A2.
 */
import { HestiaElement, html, css, nothing } from '@hestia/webui-sdk';
import { API, CLIENT_STATE, LEVEL_TONE, hermesStyles, todayStart, when } from './util';

const FILTERS = [
  { id: '', label: 'Tutte' }, { id: 'held', label: 'Trattenute' }, { id: 'quiet', label: 'Silenziose' },
  { id: 'retracted', label: 'Ritirate' }, { id: 'failed', label: 'Fallite' }, { id: 'answered', label: 'Con risposta' },
  { id: 'pending', label: 'In attesa' }, { id: 'superseded', label: 'Sostituite' },
];

export class HermesDeliveries extends HestiaElement {
  static properties = { ...HestiaElement.properties, items: { state: true }, summary: { state: true }, next: { state: true },
                        error: { state: true }, flag: { state: true }, client: { state: true }, clients: { state: true },
                        subs: { state: true }, more: { state: true }, open: { state: true } };
  declare items: any[] | null; declare summary: any; declare next: string | null; declare error: string;
  declare flag: string; declare client: string; declare clients: string[]; declare subs: any[] | null;
  declare more: boolean; declare open: string;
  static styles = [...HestiaElement.styles, hermesStyles, css`
    .head { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
    .sub { color: var(--text-3); font-size: 13px; }
    .chips { display: flex; gap: 6px; flex-wrap: wrap; }
    .chip { font: inherit; font-size: 13px; padding: 4px 10px; border-radius: 99px; border: 1px solid var(--border-strong);
      background: var(--surface); color: var(--text-2); cursor: pointer; }
    .chip[aria-pressed=true] { background: var(--accent-soft); color: var(--accent); border-color: var(--accent); }
    .chip:focus-visible { outline: none; box-shadow: 0 0 0 3px var(--focus-ring); }
    .n { padding: 10px 0; border-top: 1px solid var(--border); display: flex; flex-direction: column; gap: 4px; }
    .n:first-child { border-top: 0; }
    .top { display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
    .t { font-weight: 550; overflow-wrap: anywhere; }
    .pv { color: var(--text-2); font-size: 13px; overflow-wrap: anywhere; }
    .cl { display: flex; gap: 6px; flex-wrap: wrap; }
    .sec { display: flex; flex-direction: column; gap: 8px; }
    .subrow { padding: 8px 0; border-top: 1px solid var(--border); font-size: 13px; overflow-wrap: anywhere; }
    .subrow:first-child { border-top: 0; }
    code { font-size: 12px; background: var(--surface-2); padding: 0 4px; border-radius: 4px; }
    select { max-width: 100%; }
  `];

  constructor() {
    super();
    this.items = null; this.summary = null; this.next = null; this.error = ''; this.flag = ''; this.client = '';
    this.clients = []; this.subs = null; this.more = false; this.open = '';
  }

  connectedCallback() {
    super.connectedCallback();
    this.load(); this.loadSide();
    this.onHost('refresh', () => { this.load(); this.loadSide(); });
    this.addEventListener('retry', () => { this.load(); this.loadSide(); });
  }

  private async load(append = false) {
    const query: Record<string, any> = { limit: 40 };
    if (this.flag) query.flag = this.flag;
    if (this.client) query.client = this.client;
    if (append && this.next) query.before = this.next;
    this.more = append;
    const r = await this.host.api('GET', `${API}/deliveries`, { query });
    this.more = false;
    if (!r.ok) {
      if (append) { this.host.toast(r.error || 'Non caricato', 'danger'); return; }
      this.error = r.status === 0 || r.error === 'offline' || r.error === 'unreachable' ? 'Hermes non raggiungibile'
        : r.error || 'Hermes non raggiungibile';
      return;
    }
    this.error = '';
    this.items = append ? [...(this.items || []), ...r.data.items] : r.data.items;
    this.next = r.data.next_before;
    if (!append) this.loadSummary();
  }

  private async loadSummary() {
    const r = await this.host.api('GET', `${API}/deliveries`, { query: { since: todayStart(), limit: 200 } });
    this.summary = r.ok ? r.data.summary : null;
  }

  private async loadSide() {
    const [c, s] = await Promise.all([this.host.api('GET', `${API}/clients`), this.host.api('GET', `${API}/subscriptions`)]);
    this.clients = c.ok ? c.data.clients || [] : [];
    this.subs = s.ok ? s.data.subscriptions || [] : [];
  }

  private setFlag(id: string) { this.flag = id; this.items = null; this.load(); }
  private setClient(e: Event) { this.client = (e.target as HTMLSelectElement).value; this.items = null; this.load(); }

  private renderStats() {
    const s = this.summary; if (!s) return nothing;
    return html`<hxk-stat .items=${[
      { label: 'Oggi', value: s.total },
      { label: 'Trattenute', value: s.held, hint: 'presenza: solo elenco' },
      { label: 'Fallite', value: s.failed, tone: s.failed ? 'danger' : 'neutral', delta: s.failed ? 'da riprovare' : '' },
      { label: 'In attesa', value: s.pending, hint: 'aspettano una risposta' },
    ]}></hxk-stat>`;
  }

  private flags(n: any) {
    const f = n.flags || {};
    return html`${f.held ? html`<hxk-badge tone="warning" title=${`Trattenuta: livello notifiche «${f.held}»${f.held_released ? ' · rilasciata nel riepilogo' : ''}`}>trattenuta${f.held_released ? ' · rilasciata' : ''}</hxk-badge>` : nothing}
      ${f.quiet ? html`<hxk-badge tone="neutral" title="Copia in elenco senza avviso (la domanda era in chat)">silenziosa</hxk-badge>` : nothing}
      ${f.retracted ? html`<hxk-badge tone="neutral" title="Tolta dalla chat dopo che era stata vista o gestita">ritirata</hxk-badge>` : nothing}
      ${f.superseded ? html`<hxk-badge tone="neutral" title="Sostituita da una nuova occorrenza dello stesso promemoria">sostituita</hxk-badge>` : nothing}
      ${f.pending ? html`<hxk-badge tone="accent">in attesa</hxk-badge>` : nothing}
      ${n.repeat?.count > 1 ? html`<hxk-badge tone="info">${n.repeat.count}ª volta</hxk-badge>` : nothing}`;
  }

  private renderItem(n: any) {
    const clients = Object.entries(n.clients || {}) as Array<[string, any]>;
    const isOpen = this.open === n.id;
    return html`<div class="n">
      <div class="top"><span class="small muted tnum">${when(n.created_at)}</span>
        <hxk-badge tone=${LEVEL_TONE[n.level] || 'neutral'}>${n.source || 'sistema'}</hxk-badge>
        <span class="t grow">${n.title || n.preview || n.event_type}</span></div>
      ${n.title && n.preview ? html`<div class="pv">${n.preview}</div>` : nothing}
      <div class="cl">
        ${clients.length ? clients.map(([name, c]) => {
          const st = CLIENT_STATE[c.state] || { text: c.state || '–', tone: 'neutral' };
          return html`<hxk-badge tone=${st.tone} title=${[when(c.at), c.attempts > 1 ? `${c.attempts} tentativi` : '', c.detail || ''].filter(Boolean).join(' · ')}>${name}: ${st.text}${c.retracted ? ' · ritirata' : ''}</hxk-badge>`;
        }) : html`<span class="small muted">nessun client raggiunto</span>`}
        ${n.audience === 'origin' && n.origin_client ? html`<span class="pill">solo ${n.origin_client}</span>` : nothing}
        ${this.flags(n)}
      </div>
      ${n.answer ? html`<div class="small">Risposta: <b>${n.answer.label || n.answer.action_id || '–'}</b>
          ${n.answer.by ? html` da ${n.answer.by}` : nothing} · ${when(n.answer.at)}
          ${n.answer.outcome_text ? html` · <span class="muted">${n.answer.outcome_text}</span>` : nothing}</div>`
        : n.actions?.length ? html`<div class="small muted">Azioni: ${n.actions.join(' · ')}</div>` : nothing}
      ${isOpen ? html`<div class="small muted">Tipo <code>${n.event_type}</code> · stato <code>${n.state}</code>
          ${n.seen?.at ? html` · vista ${when(n.seen.at)}${n.seen.by ? ` su ${n.seen.by}` : ''}` : nothing} · id <code>${n.id}</code></div>` : nothing}
      <div><hxk-button size="sm" variant="ghost" @click=${() => (this.open = isOpen ? '' : n.id)}>${isOpen ? 'Meno' : 'Dettagli'}</hxk-button></div>
    </div>`;
  }

  private renderSubs() {
    if (this.subs === null) return nothing;
    return html`<hxk-card heading="Iscrizioni attive" subtitle="Quali eventi diventano notifiche e per chi">
      ${this.subs.length ? this.subs.map(s => html`<div class="subrow">
          <b>${s.domain || '*'}</b> · <code>${s.event_type || '*'}</code>
          → ${(s.channels || []).map((c: any) => c.type === 'client' ? `solo ${c.client}` : 'tutti i client').join(', ') || 'tutti i client'}
          ${Object.keys(s.filters || {}).length ? html`<div class="small muted">Filtri: ${Object.entries(s.filters).map(([k, v]) => `${k} = ${typeof v === 'object' ? JSON.stringify(v) : v}`).join(' · ')}</div>` : nothing}
        </div>`) : html`<hxk-state kind="empty" text="Nessuna iscrizione attiva"></hxk-state>`}
    </hxk-card>`;
  }

  render() {
    if (this.error) return html`<div class="page"><h1>Consegne</h1><hxk-state kind="offline" text=${this.error}></hxk-state></div>`;
    return html`<div class="page">
      <div class="head"><h1>Consegne</h1><span class="sub">Cosa Hermes ha mandato, a chi e com'è andata</span></div>
      ${this.renderStats()}
      <div class="row wrap">
        <div class="chips grow">${FILTERS.map(f => html`<button class="chip" aria-pressed=${this.flag === f.id} @click=${() => this.setFlag(f.id)}>${f.label}</button>`)}</div>
        ${this.clients.length ? html`<select aria-label="Client" @change=${(e: Event) => this.setClient(e)}>
          <option value="">Tutti i client</option>${this.clients.map(c => html`<option value=${c} ?selected=${this.client === c}>${c}</option>`)}</select>` : nothing}
      </div>
      ${this.items === null ? html`<hxk-state kind="loading"></hxk-state>`
        : this.items.length ? html`<div class="card">${this.items.map(n => this.renderItem(n))}
            ${this.next ? html`<div style="padding-top:8px"><hxk-button size="sm" ?loading=${this.more} @click=${() => this.load(true)}>Carica altre</hxk-button></div>` : nothing}</div>`
        : html`<hxk-state kind="empty" text="Nessuna notifica con questo filtro"></hxk-state>`}
      <div class="sec">
        ${this.renderSubs()}
        <p class="small muted">Client raggiunti ora: ${this.clients.length ? this.clients.join(', ') : 'nessuno'}. Le notifiche da leggere e a cui rispondere sono in Notifiche.</p>
      </div>
    </div>`;
  }
}
