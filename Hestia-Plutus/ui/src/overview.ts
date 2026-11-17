/**
 * <plutus-overview> — the budget month: spent vs budget and pace, categories, latest movements, payments coming,
 *                     what needs a look (to review, PayPal check, statement import).
 */
import { HestiaElement, html, nothing, plural, tr } from '@hestia/webui-sdk';
import { API, PERIOD, addMonths, budgetBar, call, dayLabel, meta, money, plutusStyles, txRow } from './util';

export class PlutusOverview extends HestiaElement {
  static properties = { ...HestiaElement.properties, s: { state: true }, latest: { state: true }, m: { state: true }, month: { state: true },
    form: { state: true }, checking: { state: true } };
  declare s: any;
  declare latest: any[];
  declare m: any;
  declare month: string;
  declare form: boolean;
  declare checking: boolean;
  static styles = [...HestiaElement.styles, plutusStyles];
  constructor() { super(); this.s = undefined; this.latest = []; this.m = null; this.month = ''; this.form = false; this.checking = false; }
  connectedCallback() { super.connectedCallback(); this.load(); this.onHost('refresh', () => this.load()); }
  private async load() {
    this.m = await meta(this.host);
    const q = this.month ? { month: this.month } : {};
    const [s, t] = await Promise.all([this.host.api('GET', `${API}/summary`, { query: q }),
      this.host.api('GET', `${API}/transactions`, { query: { ...q, month: this.month || this.m?.month || '', limit: 8 } })]);
    this.s = s.ok ? s.data : null;
    this.latest = t.ok ? t.data.items : [];
    if (s.ok && !this.month) this.month = s.data.month;
  }
  private shift(n: number) { this.month = addMonths(this.month, n); this.s = undefined; this.load(); }
  private async checkMail() {
    this.checking = true;
    const r = await call(this.host, 'POST', `${API}/mail/check`, { body: { days: 7 } });
    this.checking = false;
    if (r.ok) this.host.toast(tr('I recheck the PayPal emails of the last 7 days'), 'info');
    setTimeout(() => this.load(), 4000);
  }
  render() {
    const s = this.s;
    if (s === undefined) return html`<div class="page"><hxk-state kind="loading"></hxk-state></div>`;
    if (s === null) return html`<div class="page"><hxk-state kind="offline" @retry=${() => this.load()}></hxk-state></div>`;
    const cur = s.currency;
    const pct = s.budget ? Math.round(100 * s.spent / s.budget) : null;
    const running = s.days_gone < s.days_total;
    return html`<div class="page">
      <div class="between wrap"><div class="head"><h1>${tr("Expenses")}</h1>
          <hxk-button size="sm" variant="ghost" icon="chevron-left" @click=${() => this.shift(-1)}></hxk-button>
          <b>${s.label}</b><hxk-button size="sm" variant="ghost" icon="chevron-right" @click=${() => this.shift(1)}></hxk-button></div>
        <div class="row wrap"><hxk-button variant="primary" icon="plus" @click=${() => (this.form = true)}>${tr("Expense")}</hxk-button>
          <hxk-button icon="upload" @click=${() => this.host.navigate('import')}>${tr("Bank statement")}</hxk-button></div></div>
      ${s.to_review ? html`<div class="note warning between click" @click=${() => this.host.navigate('transactions', { rivedere: '1' })}>
        <span>${plural(s.to_review, 'transaction', 'transactions')} ${tr("with the category to check")}</span><span class="link">${tr("Review ›")}</span></div>` : nothing}
      <hxk-stat .items=${[
        { label: tr('Spent'), value: money(s.spent, cur), hint: s.linked ? tr("{0} linked, counted once", plural(s.linked, 'transaction', 'transactions')) : '' },
        { label: tr('f.pl::Income'), value: money(s.income, cur) },
        s.budget ? { label: tr('Left'), value: money(s.left, cur), tone: s.left < 0 ? 'danger' : 'success', delta: tr("{0}% of the budget", pct) }
          : { label: tr('Budget'), value: '–', hint: tr('Set a budget in the Budget page') },
        running && s.spent ? { label: tr('At this pace'), value: money(s.pace, cur), hint: tr("day {0} of {1}", s.days_gone, s.days_total),
          tone: s.budget && s.pace > s.budget ? 'danger' : 'neutral', delta: s.budget && s.pace > s.budget ? tr('over budget') : '' }
          : { label: tr('Balance'), value: money(s.net, cur, true) }]}></hxk-stat>
      ${s.budget ? html`<div class="card col"><div class="between"><span class="small muted">${tr("Monthly budget")}</span>
        <span class="small tnum">${money(s.spent, cur)} / ${money(s.budget, cur)}</span></div>${budgetBar(pct)}</div>` : nothing}
      <div class="card col"><div class="between"><h2>${tr("Categories")}</h2><button class="link" @click=${() => this.host.navigate('budget')}>${tr("Budget ›")}</button></div>
        ${s.categories.length ? html`<div class="list">${s.categories.map((c: any, i: number) => html`<div class="li" @click=${() => this.host.navigate('transactions', { categoria: c.id, mese: s.month })}>
          <span class="dot" style="background:var(--cal-${(i % 8) + 1})" title=${tr("same color as the chart")}></span><div class="grow col" style="gap:4px"><div class="between"><span class="truncate">${c.label}</span>
            <span class="tnum small">${money(c.spent, cur)}${c.budget ? html`<span class="muted"> / ${money(c.budget, cur)}</span>` : nothing}</span></div>
            ${budgetBar(c.pct)}</div></div>`)}</div>` : html`<div class="empty">${tr("No expenses this month.")}</div>`}
      </div>
      ${s.categories.length > 1 ? html`<div class="card col"><h2>${tr("Where the money goes")}</h2>
        <hxk-chart type="donut" height="180" unit=${cur === 'EUR' ? '€' : cur} .labels=${s.categories.map((c: any) => c.label)}
          .series=${[{ name: tr('Spent'), values: s.categories.map((c: any) => c.spent) }]}></hxk-chart></div>` : nothing}
      <div class="card col"><div class="between"><h2>${tr("Latest transactions")}</h2><button class="link" @click=${() => this.host.navigate('transactions', { mese: s.month })}>${tr("All ›")}</button></div>
        ${this.latest.length ? html`<div class="list">${this.latest.map(t => txRow(this.host, t, cur))}</div>` : html`<div class="empty">${tr("Nothing yet: PayPal emails arrive by themselves, you add the rest here or in chat.")}</div>`}</div>
      ${s.recurring_next.length ? html`<div class="card col"><div class="between"><h2>${tr("Coming")}</h2><button class="link" @click=${() => this.host.navigate('subscriptions')}>${tr("Subscriptions ›")}</button></div>
        <div class="list">${s.recurring_next.map((r: any) => html`<div class="li" @click=${() => this.host.navigate('subscriptions')}>
          <div class="grow"><b>${r.merchant}</b><div class="small muted">${PERIOD[r.period] || r.period} · ${dayLabel(r.next)}</div></div>
          <span class="tnum amt">${money(-r.amount, cur, true)}</span></div>`)}</div></div>` : nothing}
      ${s.top_merchants.length ? html`<div class="card col"><h2>${tr("Main merchants")}</h2>
        ${s.top_merchants.map((x: any) => html`<div class="between small" style="padding:3px 0"><span class="truncate">${x.merchant}</span><span class="tnum">${money(x.spent, cur)}</span></div>`)}</div>` : nothing}
      <div class="row wrap"><hxk-button variant="ghost" icon="refresh" ?loading=${this.checking} @click=${() => this.checkMail()}>${tr("Recheck PayPal emails")}</hxk-button>
        <hxk-button variant="ghost" icon="chart" @click=${() => this.host.navigate('stats')}>${tr("Statistics")}</hxk-button>
        <hxk-button variant="ghost" icon="sparkle" @click=${() => this.host.assistant({ label: tr("Expenses of {0}", s.label), hints: { month: s.month },
          suggestions: [tr('How did the month go?'), tr('Where can I save?'), tr('How much did I spend at restaurants?')] })}>${tr("Ask")}</hxk-button></div>
      ${this.form ? html`<plutus-tx-form .host=${this.host} @close=${() => { this.form = false; this.load(); }}></plutus-tx-form>` : nothing}
    </div>`;
  }
}
