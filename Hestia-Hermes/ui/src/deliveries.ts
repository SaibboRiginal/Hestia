/**
 * <hermes-deliveries> — «Deliveries»: what Hermes sent to which client (held / quiet / retracted / superseded),
 * the answers, the active subscriptions and the clients reached. Read-only; the inbox is the Notifications page.
 * SPEC docs/work/2026-10-18-moduli-core-e-mcp-esterno §A2.
 */
import { HestiaElement, html, css, nothing, tr } from '@hestia/webui-sdk';
import { API, CLIENT_STATE, LEVEL_TONE, hermesStyles, todayStart, when } from './util';

const FILTERS = [
  { id: '', label: tr('All') }, { id: 'held', label: tr('Held back') }, { id: 'quiet', label: tr('Silent') },
  { id: 'retracted', label: tr('Withdrawn') }, { id: 'failed', label: tr('f.pl::Failed') }, { id: 'answered', label: tr('With answer') },
  { id: 'pending', label: tr('Waiting') }, { id: 'superseded', label: tr('f.pl::Replaced') },
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
      if (append) { this.host.toast(r.error || tr('Not uploaded'), 'danger'); return; }
      this.error = r.status === 0 || r.error === 'offline' || r.error === 'unreachable' ? tr('Hermes not reachable')
        : r.error || tr('Hermes not reachable');
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
      { label: tr('Today'), value: s.total },
      { label: tr('Held back'), value: s.held, hint: tr('presence: list only') },
      { label: tr('f.pl::Failed'), value: s.failed, tone: s.failed ? 'danger' : 'neutral', delta: s.failed ? tr('to retry') : '' },
      { label: tr('Waiting'), value: s.pending, hint: tr('waiting for an answer') },
    ]}></hxk-stat>`;
  }

  private flags(n: any) {
    const f = n.flags || {};
    return html`${f.held ? html`<hxk-badge tone="warning" title=${tr("Held back: notification level «{0}»{1}", f.held, f.held_released ? tr(' · released in the summary') : '')}>${tr("held back")}${f.held_released ? tr(' · released') : ''}</hxk-badge>` : nothing}
      ${f.quiet ? html`<hxk-badge tone="neutral" title=${tr("Copy in the list without a notice (the question was in chat)")}>${tr("silent")}</hxk-badge>` : nothing}
      ${f.retracted ? html`<hxk-badge tone="neutral" title=${tr("Removed from the chat after it was seen or handled")}>${tr("withdrawn")}</hxk-badge>` : nothing}
      ${f.superseded ? html`<hxk-badge tone="neutral" title=${tr("Replaced by a new occurrence of the same reminder")}>${tr("f::replaced")}</hxk-badge>` : nothing}
      ${f.pending ? html`<hxk-badge tone="accent">${tr("waiting")}</hxk-badge>` : nothing}
      ${n.repeat?.count > 1 ? html`<hxk-badge tone="info">${tr("time {0}", n.repeat.count)}</hxk-badge>` : nothing}`;
  }

  private renderItem(n: any) {
    const clients = Object.entries(n.clients || {}) as Array<[string, any]>;
    const isOpen = this.open === n.id;
    return html`<div class="n">
      <div class="top"><span class="small muted tnum">${when(n.created_at)}</span>
        <hxk-badge tone=${LEVEL_TONE[n.level] || 'neutral'}>${n.source || tr('system')}</hxk-badge>
        <span class="t grow">${n.title || n.preview || n.event_type}</span></div>
      ${n.title && n.preview ? html`<div class="pv">${n.preview}</div>` : nothing}
      <div class="cl">
        ${clients.length ? clients.map(([name, c]) => {
          const st = CLIENT_STATE[c.state] || { text: c.state || '–', tone: 'neutral' };
          return html`<hxk-badge tone=${st.tone} title=${[when(c.at), c.attempts > 1 ? tr('{0} attempts', c.attempts) : '', c.detail || ''].filter(Boolean).join(' · ')}>${name}: ${st.text}${c.retracted ? tr(' · withdrawn') : ''}</hxk-badge>`;
        }) : html`<span class="small muted">${tr("no client reached")}</span>`}
        ${n.audience === 'origin' && n.origin_client ? html`<span class="pill">${tr("only")} ${n.origin_client}</span>` : nothing}
        ${this.flags(n)}
      </div>
      ${n.answer ? html`<div class="small">${tr("Answer:")} <b>${n.answer.label || n.answer.action_id || '–'}</b>
          ${n.answer.by ? html` da ${n.answer.by}` : nothing} · ${when(n.answer.at)}
          ${n.answer.outcome_text ? html` · <span class="muted">${n.answer.outcome_text}</span>` : nothing}</div>`
        : n.actions?.length ? html`<div class="small muted">${tr("Actions:")} ${n.actions.join(' · ')}</div>` : nothing}
      ${isOpen ? html`<div class="small muted">${tr("Type")} <code>${n.event_type}</code> · ${tr('state')} <code>${n.state}</code>
          ${n.seen?.at ? html` · ${tr('seen {0}', when(n.seen.at))}${n.seen.by ? tr('dev:: on {0}', n.seen.by) : ''}` : nothing} · id <code>${n.id}</code></div>` : nothing}
      <div><hxk-button size="sm" variant="ghost" @click=${() => (this.open = isOpen ? '' : n.id)}>${isOpen ? tr('Less') : tr('Details')}</hxk-button></div>
    </div>`;
  }

  private renderSubs() {
    if (this.subs === null) return nothing;
    return html`<hxk-card heading=${tr("Active subscriptions")} subtitle=${tr("Which events become notifications and for whom")}>
      ${this.subs.length ? this.subs.map(s => html`<div class="subrow">
          <b>${s.domain || '*'}</b> · <code>${s.event_type || '*'}</code>
          → ${(s.channels || []).map((c: any) => c.type === 'client' ? tr('only {0}', c.client) : tr('all clients')).join(', ') || tr('all clients')}
          ${Object.keys(s.filters || {}).length ? html`<div class="small muted">${tr("Filters:")} ${Object.entries(s.filters).map(([k, v]) => `${k} = ${typeof v === 'object' ? JSON.stringify(v) : v}`).join(' · ')}</div>` : nothing}
        </div>`) : html`<hxk-state kind="empty" text=${tr("No active subscription")}></hxk-state>`}
    </hxk-card>`;
  }

  render() {
    if (this.error) return html`<div class="page"><h1>${tr("Deliveries")}</h1><hxk-state kind="offline" text=${this.error}></hxk-state></div>`;
    return html`<div class="page">
      <div class="head"><h1>${tr("Deliveries")}</h1><span class="sub">${tr("What was sent, to whom and how it went")}</span></div>
      ${this.renderStats()}
      <div class="row wrap">
        <div class="chips grow">${FILTERS.map(f => html`<button class="chip" aria-pressed=${this.flag === f.id} @click=${() => this.setFlag(f.id)}>${f.label}</button>`)}</div>
        ${this.clients.length ? html`<select aria-label=${tr("Client")} @change=${(e: Event) => this.setClient(e)}>
          <option value="">${tr("All clients")}</option>${this.clients.map(c => html`<option value=${c} ?selected=${this.client === c}>${c}</option>`)}</select>` : nothing}
      </div>
      ${this.items === null ? html`<hxk-state kind="loading"></hxk-state>`
        : this.items.length ? html`<div class="card">${this.items.map(n => this.renderItem(n))}
            ${this.next ? html`<div style="padding-top:8px"><hxk-button size="sm" ?loading=${this.more} @click=${() => this.load(true)}>${tr("Load more")}</hxk-button></div>` : nothing}</div>`
        : html`<hxk-state kind="empty" text=${tr("No notification with this filter")}></hxk-state>`}
      <div class="sec">
        ${this.renderSubs()}
        <p class="small muted">${tr("Clients reached now:")} ${this.clients.length ? this.clients.join(', ') : tr('none')}${tr(". The notifications to read and answer are in Notifications.")}</p>
      </div>
    </div>`;
  }
}
