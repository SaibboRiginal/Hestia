/**
 * <hygieia-stats>    — how it is going: calendar heatmap, goals and streaks per routine, most used products, spend,
 *                      the history of changes, and "what was I using on…" for any past day.
 * <hygieia-shopping> — what to buy: wishlist, running out, finished and worth buying again.
 */
import { HestiaElement, html, css, nothing, locale, tr } from '@hestia/webui-sdk';
import { API, STATUS_TONE, WEEKDAYS, addDays, call, dayLabel, eventIcon, hygieiaStyles, icon, meta, money, productName, relDays, today } from './util';

export class HygieiaStats extends HestiaElement {
  static properties = { ...HestiaElement.properties, tab: { state: true }, days: { state: true }, st: { state: true }, tl: { state: true },
    day: { state: true }, period: { state: true }, m: { state: true } };
  declare tab: string;
  declare days: number;
  declare st: any;
  declare tl: any[] | null | undefined;
  declare day: string;
  declare period: any;
  declare m: any;
  static styles = [...HestiaElement.styles, hygieiaStyles, css`
    .heat { display: grid; grid-auto-flow: column; grid-template-rows: repeat(7, 1fr); gap: 3px; overflow-x: auto; padding-bottom: 4px; }
    .cell { width: 13px; height: 13px; border-radius: 3px; background: var(--surface-3); }
    .cell.l1 { background: color-mix(in srgb, var(--success) 35%, transparent); }
    .cell.l2 { background: color-mix(in srgb, var(--success) 65%, transparent); }
    .cell.l3 { background: var(--success); }
    .cell.blank { background: transparent; }
    .tl { display: flex; gap: 10px; padding: 7px 0; border-bottom: 1px solid var(--border); font-size: 13px; }
    .tl:last-child { border-bottom: none; }
    .month { margin-top: 8px; }
    .adh { width: 70px; height: 6px; border-radius: 3px; background: var(--surface-3); overflow: hidden; flex: none; }
    .adh > span { display: block; height: 100%; background: var(--success); }
  `];
  constructor() { super(); this.tab = 'panoramica'; this.days = 90; this.st = undefined; this.tl = undefined; this.day = addDays(today(), -30); this.period = null; this.m = null; }
  connectedCallback() {
    super.connectedCallback();
    if (this.ctx?.query?.tab) this.tab = this.ctx.query.tab;
    this.load();
    this.onHost('refresh', () => this.load());
  }
  private async load() {
    this.m = await meta(this.host);
    if (this.tab === 'panoramica') { const r = await this.host.api('GET', `${API}/stats`, { query: { days: this.days } }); this.st = r.ok ? r.data : null; }
    if (this.tab === 'storia') { const r = await this.host.api('GET', `${API}/timeline`, { query: { days: 730 } }); this.tl = r.ok ? r.data.items : null; }
    if (this.tab === 'giorno') { const r = await this.host.api('GET', `${API}/period`, { query: { date: this.day } }); this.period = r.ok ? r.data : null; }
  }
  private heat(items: any[]) {
    if (!items.length) return nothing;
    const first = new Date(items[0].date + 'T12:00:00');
    const pad = (first.getDay() + 6) % 7;
    const max = Math.max(1, ...items.map(i => i.count));
    return html`<div class="heat">${Array.from({ length: pad }, () => html`<span class="cell blank"></span>`)}
      ${items.map(i => html`<span class="cell ${i.count ? 'l' + Math.min(3, Math.ceil((i.count / max) * 3)) : ''}" title="${dayLabel(i.date, false)}: ${i.count}"></span>`)}</div>
      <div class="small muted">${WEEKDAYS[0]} ${tr("at the top,")} ${WEEKDAYS[6]} ${tr("at the bottom · darker = more routines")}</div>`;
  }
  private overview() {
    const s = this.st;
    if (s === undefined) return html`<hxk-state kind="loading"></hxk-state>`;
    if (s === null) return html`<hxk-state kind="offline" @retry=${() => this.load()}></hxk-state>`;
    const cur = this.m?.currency || 'EUR';
    const byStatus = s.products_by_status || {};
    return html`
      <div class="tabs">${[30, 90, 365].map(d => html`<button class="tab" aria-pressed=${this.days === d} @click=${() => { this.days = d; this.st = undefined; this.load(); }}>${d === 365 ? tr('1 year') : tr('{0} days', d)}</button>`)}</div>
      <hxk-stat .items=${[{ label: tr('This week'), value: s.week.logs, unit: tr('times') },
        { label: tr('Week goals'), value: s.week.goals ? `${s.week.goals_met}/${s.week.goals}` : '–' },
        { label: tr('Products in use'), value: byStatus.in_use || 0, hint: byStatus.stock ? tr("{0} in stock", byStatus.stock) : '' },
        { label: tr('pl::Finished'), value: byStatus.finished || 0 }]}></hxk-stat>
      <div class="card col"><h2>${tr("Calendar")}</h2>${this.heat(s.heatmap || [])}</div>
      <div class="card col"><h2>${tr("Routine")}</h2>
        ${(s.routines || []).length ? html`<div class="list">${s.routines.map((r: any) => html`<div class="li" @click=${() => this.host.navigate('routine/' + r.routine_id)}>
          <div class="grow"><div class="truncate"><b>${r.name}</b></div><div class="small muted">${r.cadence} · ${r.total} ${tr("times")}${r.streak ? html` · ${r.streak} ${r.per === 'month' ? tr('months') : tr('weeks')} ${tr("in a row")} ${icon('flame', 12, 'warning')}` : ''} ${tr("· last")} ${relDays(r.last_done)}</div></div>
          ${r.adherence !== null && r.adherence !== undefined ? html`<span class="adh"><span style="width:${r.adherence}%"></span></span><span class="small tnum">${r.adherence}%</span>` : nothing}
        </div>`)}</div>` : html`<div class="empty">${tr("No routines.")}</div>`}
      </div>
      ${(s.top_products || []).length ? html`<div class="card col"><h2>${tr("Most used products")}</h2>
        <hxk-chart type="bar" height="160" .labels=${s.top_products.map((p: any) => p.name)} .series=${[{ name: tr('Uses'), values: s.top_products.map((p: any) => p.uses) }]}></hxk-chart></div>` : nothing}
      ${(s.spend || []).some((x: any) => x.amount) ? html`<div class="card col"><div class="between"><h2>${tr("Expense")}</h2>
          <span class="small muted">${money(s.spend.reduce((a: number, x: any) => a + x.amount, 0), cur)} ${tr("in 12 months")}</span></div>
        <hxk-chart type="bar" height="140" unit=${cur === 'EUR' ? '€' : cur} .labels=${s.spend.map((x: any) => x.month.slice(5) + '/' + x.month.slice(2, 4))}
          .series=${[{ name: tr('Expense'), values: s.spend.map((x: any) => x.amount) }]}></hxk-chart></div>` : nothing}
      <div class="row wrap"><hxk-button variant="ghost" icon="link" @click=${() => this.exportData()}>${tr("Export everything (JSON)")}</hxk-button></div>`;
  }
  private async exportData() {
    const r = await call(this.host, 'GET', `${API}/export`);
    if (!r.ok) return;
    const blob = new Blob([JSON.stringify(r.data.data, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = r.data.filename; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  }
  private history() {
    const items = this.tl;
    if (items === undefined) return html`<hxk-state kind="loading"></hxk-state>`;
    if (items === null) return html`<hxk-state kind="offline" @retry=${() => this.load()}></hxk-state>`;
    if (!items.length) return html`<div class="card muted">${tr("No change recorded yet.")}</div>`;
    const months: Record<string, any[]> = {};
    for (const t of items) (months[t.date.slice(0, 7)] ||= []).push(t);
    return html`${Object.entries(months).map(([mo, list]) => html`<h3 class="month">${new Date(mo + '-15').toLocaleDateString(locale(), { month: 'long', year: 'numeric' })}</h3>
      <div class="card list">${list.map(t => html`<div class="tl ${t.product_id || t.routine_id ? 'click' : ''}"
        @click=${() => t.product_id ? this.host.navigate('products/' + t.product_id) : t.routine_id ? this.host.navigate('routine/' + t.routine_id) : null}>
        <span>${eventIcon(t.type)}</span><span class="muted tnum" style="min-width:60px">${dayLabel(t.date, false)}</span>
        <div class="grow"><b>${t.title}</b>${t.text ? html`<span class="muted"> — ${t.text}</span>` : nothing}</div></div>`)}</div>`)}`;
  }
  private pastDay() {
    const p = this.period;
    return html`<div class="card col">
      <div class="row wrap"><span>${tr("What I used on")}</span><input class="in" type="date" max=${today()} .value=${this.day}
        @change=${(e: any) => { this.day = e.target.value; this.load(); }}></div>
      ${!p ? html`<hxk-state kind="loading"></hxk-state>` : html`
        <h3>${tr("Routine")}</h3>
        ${p.routines.length ? p.routines.map((r: any) => html`<div><b>${r.name}</b> <span class="small muted">v${r.version}</span><div class="small">${r.steps.join(' → ') || '—'}</div></div>`)
          : html`<div class="empty">${tr("No routine on that date.")}</div>`}
        <h3>${tr("Opened products")}</h3>
        ${p.products.length ? html`<div class="chips">${p.products.map((x: any) => html`<span class="pill click" @click=${() => this.host.navigate('products/' + x.id)}>${productName(x)}</span>`)}</div>`
          : html`<div class="empty">${tr("None.")}</div>`}
        ${p.journal.length ? html`<h3>${tr("Diary (± 7 days)")}</h3>${p.journal.map((j: any) => html`<div class="small"><span class="muted">${dayLabel(j.date, false)}</span> · ${j.area}: ${Object.entries(j.scores || {}).map(([k, v]) => `${k} ${v}`).join(', ')}${j.note ? ' — ' + j.note : ''}</div>`)}` : nothing}`}
    </div>`;
  }
  render() {
    const tabs: Array<[string, string]> = [['panoramica', tr('Overview')], ['storia', tr('Change history')], ['giorno', tr('A day has passed')]];
    return html`<div class="page">
      <div class="head"><button class="link" @click=${() => this.host.navigate('today')}>${tr("‹ Today")}</button><h1>${tr("Statistics")}</h1></div>
      <div class="tabs">${tabs.map(([k, l]) => html`<button class="tab" aria-pressed=${this.tab === k} @click=${() => { this.tab = k; this.load(); }}>${l}</button>`)}</div>
      ${this.tab === 'panoramica' ? this.overview() : this.tab === 'storia' ? this.history() : this.pastDay()}
    </div>`;
  }
}

export class HygieiaShopping extends HestiaElement {
  static properties = { ...HestiaElement.properties, data: { state: true }, form: { state: true } };
  declare data: any;
  declare form: boolean;
  static styles = [...HestiaElement.styles, hygieiaStyles];
  constructor() { super(); this.data = undefined; this.form = false; }
  connectedCallback() { super.connectedCallback(); this.load(); this.onHost('refresh', () => this.load()); }
  private async load() { const r = await this.host.api('GET', `${API}/shopping`); this.data = r.ok ? r.data : null; }
  private async bought(p: any, how: 'stock' | 'repurchase') {
    const r = how === 'repurchase' ? await call(this.host, 'POST', `${API}/products/${p.id}/repurchase`, { body: {} })
      : await call(this.host, 'POST', `${API}/products/${p.id}/status`, { body: { status: 'stock' } });
    if (r.ok) this.host.toast(tr('{0}: bought', p.name), 'success');
    this.load();
  }
  private section(title: string, items: any[], how: 'stock' | 'repurchase', empty: string) {
    return html`<div class="card col"><h2>${title} ${items.length ? html`<span class="muted">${items.length}</span>` : nothing}</h2>
      ${items.length ? html`<div class="list">${items.map(p => html`<div class="li">
        <div class="grow click" @click=${() => this.host.navigate('products/' + p.id)}><div class="truncate"><b>${p.name}</b>${p.brand ? html`<span class="muted"> · ${p.brand}</span>` : nothing}</div>
          <div class="small muted truncate">${[p.why, p.price ? money(p.price, p.currency) : '', p.shop].filter(Boolean).join(' · ')}</div></div>
        <hxk-badge tone=${STATUS_TONE[p.status] || 'neutral'}>${p.status_label}</hxk-badge>
        <hxk-button size="sm" icon="check" @click=${() => this.bought(p, how)}>${tr("Bought")}</hxk-button></div>`)}</div>` : html`<div class="empty">${empty}</div>`}</div>`;
  }
  render() {
    const d = this.data;
    return html`<div class="page">
      <div class="between wrap"><div class="head"><button class="link" @click=${() => this.host.navigate('products')}>${tr('‹ Products')}</button><h1>${tr("Shopping list")}</h1></div>
        <hxk-button icon="plus" @click=${() => (this.form = true)}>${tr("Wish")}</hxk-button></div>
      ${d === undefined ? html`<hxk-state kind="loading"></hxk-state>` : d === null ? html`<hxk-state kind="offline" @retry=${() => this.load()}></hxk-state>` : html`
        ${this.section(tr('Running out'), d.restock, 'repurchase', tr('Nothing running out.'))}
        ${this.section(tr('Finished, to buy again'), d.repurchase, 'repurchase', tr('Mark «I\'d buy it again» on a finished product to see it here.'))}
        ${this.section(tr('Wishes'), d.wishlist, 'stock', tr('No wishes.'))}`}
      ${this.form ? html`<hygieia-product-form .host=${this.host} .product=${{ status: 'wishlist' }} @close=${() => { this.form = false; this.load(); }}></hygieia-product-form>` : nothing}
    </div>`;
  }
}
