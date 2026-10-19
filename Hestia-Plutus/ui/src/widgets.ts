/** Plutus widgets for Home and dashboards: the month at a glance, the latest movements. */
import { HestiaElement, html, css, nothing } from '@hestia/webui-sdk';
import { API, budgetBar, money, plutusStyles, txRow } from './util';

abstract class Widget extends HestiaElement {
  static styles = [...HestiaElement.styles, plutusStyles, css`
    :host { display: block; height: 100%; }
    .w { display: flex; flex-direction: column; gap: 8px; height: 100%; padding: 2px; }
    .li { padding: 6px 2px; }
  `];
  connectedCallback() {
    super.connectedCallback();
    this.load();
    this.onHost('refresh', () => this.load());
    this.onHost('visible', () => this.load());
  }
  protected load(): void { /* widget specific */ }
  protected get size() { return this.ctx?.size || 'm'; }
}

export class PlutusMonthWidget extends Widget {
  static properties = { ...HestiaElement.properties, s: { state: true } };
  declare s: any;
  constructor() { super(); this.s = undefined; }
  protected async load() { const r = await this.host.api('GET', `${API}/summary`); this.s = r.ok ? r.data : null; }
  render() {
    const s = this.s;
    if (s === undefined) return html`<hxk-state kind="loading"></hxk-state>`;
    if (s === null) return html`<hxk-state kind="offline" @retry=${() => this.load()}></hxk-state>`;
    const pct = s.budget ? Math.round(100 * s.spent / s.budget) : null;
    const big = this.size === 'l' || this.size === 'xl';
    return html`<div class="w click" @click=${() => this.host.navigate('panoramica')}>
      <div class="between"><span class="small muted">Spese di ${s.label}</span>${s.to_review ? html`<span class="pill warn">${s.to_review} da rivedere</span>` : nothing}</div>
      <div class="big">${money(s.spent, s.currency)}</div>
      ${s.budget ? html`${budgetBar(pct)}<div class="small muted">${s.left >= 0 ? `rimangono ${money(s.left, s.currency)}` : `${money(-s.left, s.currency)} oltre il budget`} · ${pct}%</div>`
        : html`<div class="small muted">${s.days_gone < s.days_total && s.spent ? `a questo ritmo ${money(s.pace, s.currency)}` : `entrate ${money(s.income, s.currency)}`}</div>`}
      ${this.size !== 's' ? html`<div class="col" style="gap:5px">${s.categories.slice(0, big ? 6 : 2).map((c: any) => html`<div class="col" style="gap:2px">
        <div class="between small"><span class="truncate">${c.label}</span><span class="tnum">${money(c.spent, s.currency)}</span></div>
        ${c.budget ? budgetBar(c.pct) : nothing}</div>`)}</div>` : nothing}
      ${big && s.recurring_next.length ? html`<div class="small muted">In arrivo: ${s.recurring_next.slice(0, 3).map((r: any) => `${r.merchant} ${money(r.amount, s.currency)}`).join(' · ')}</div>` : nothing}
    </div>`;
  }
}

export class PlutusLatestWidget extends Widget {
  static properties = { ...HestiaElement.properties, items: { state: true }, cur: { state: true } };
  declare items: any[] | null | undefined;
  declare cur: string;
  constructor() { super(); this.items = undefined; this.cur = 'EUR'; }
  protected async load() {
    const r = await this.host.api('GET', `${API}/transactions`, { query: { limit: this.size === 'l' || this.size === 'xl' ? 7 : 3 } });
    this.items = r.ok ? r.data.items : null;
  }
  render() {
    if (this.items === undefined) return html`<hxk-state kind="loading"></hxk-state>`;
    if (this.items === null) return html`<hxk-state kind="offline" @retry=${() => this.load()}></hxk-state>`;
    return html`<div class="w">
      <div class="between click" @click=${() => this.host.navigate('movimenti')}><span class="small muted">Ultimi movimenti</span><span class="link small">Tutti ›</span></div>
      ${this.items.length ? html`<div class="list">${this.items.map(t => txRow(this.host, t, this.cur))}</div>` : html`<div class="muted small">Ancora nessun movimento.</div>`}
    </div>`;
  }
}
