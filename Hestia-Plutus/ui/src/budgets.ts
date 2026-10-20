/**
 * <plutus-budgets>   — monthly budget per category and in total; type a number, empty/0 removes it.
 * <plutus-recurring> — recurring payments and subscriptions Plutus recognised: confirm or dismiss.
 */
import { HestiaElement, html, nothing } from '@hestia/webui-sdk';
import { API, PERIOD, addMonths, budgetBar, call, catDot, dayLabel, money, plutusStyles } from './util';

export class PlutusBudgets extends HestiaElement {
  static properties = { ...HestiaElement.properties, b: { state: true }, month: { state: true } };
  declare b: any;
  declare month: string;
  static styles = [...HestiaElement.styles, plutusStyles];
  constructor() { super(); this.b = undefined; this.month = ''; }
  connectedCallback() { super.connectedCallback(); this.load(); this.onHost('refresh', () => this.load()); }
  private async load() {
    const r = await this.host.api('GET', `${API}/budgets`, { query: this.month ? { month: this.month } : {} });
    this.b = r.ok ? r.data : null;
    if (r.ok) this.month = r.data.month;
  }
  private async save(category: string, value: string) {
    const r = await call(this.host, 'PUT', `${API}/budgets/${category}`, { body: { amount: value.trim() || 0 } });
    if (r.ok) this.host.toast(r.data.amount ? `Budget ${money(r.data.amount, this.b.currency)}` : 'Budget tolto', 'success');
    this.load();
  }
  private input(category: string, value: number | undefined) {
    return html`<input class="in money" inputmode="decimal" placeholder="nessuno" .value=${value ? String(value).replace('.', ',') : ''}
      @change=${(e: any) => this.save(category, e.target.value)}>`;
  }
  render() {
    const b = this.b;
    if (b === undefined) return html`<div class="page"><hxk-state kind="loading"></hxk-state></div>`;
    if (b === null) return html`<div class="page"><hxk-state kind="offline" @retry=${() => this.load()}></hxk-state></div>`;
    const cur = b.currency;
    const spent: Record<string, any> = Object.fromEntries(b.categories.map((c: any) => [c.id, c]));
    const sumCats = Object.entries(b.budgets).filter(([k]) => k !== 'total').reduce((a, [, v]) => a + Number(v), 0);
    return html`<div class="page">
      <div class="head"><button class="link" @click=${() => this.host.navigate('panoramica')}>‹ Spese</button><h1>Budget</h1>
        <hxk-button size="sm" variant="ghost" icon="chevron-left" @click=${() => { this.month = addMonths(this.month, -1); this.load(); }}></hxk-button>
        <b>${b.label}</b><hxk-button size="sm" variant="ghost" icon="chevron-right" @click=${() => { this.month = addMonths(this.month, 1); this.load(); }}></hxk-button></div>
      <div class="note">Il budget vale per ogni mese. Ti avviso quando una categoria arriva alla soglia e quando la supera (Impostazioni › Spese).</div>
      <div class="card col"><div class="between"><h2>Totale del mese</h2>${this.input('total', b.budgets.total)}</div>
        <div class="small muted">Speso ${money(b.spent, cur)}${b.total ? ` su ${money(b.total, cur)}` : ''}${!b.budgets.total && sumCats ? ` · somma delle categorie ${money(sumCats, cur)}` : ''}</div>
        ${b.total ? budgetBar(Math.round(100 * b.spent / b.total)) : nothing}</div>
      <div class="card list">${b.all_categories.map((c: any) => { const s = spent[c.id];
        return html`<div class="li" style="cursor:default">${catDot(c)}<div class="grow col" style="gap:4px">
          <div class="between"><span class="truncate">${c.label}</span><span class="small muted tnum">${s ? money(s.spent, cur) : ''}</span></div>
          ${s?.pct !== null && s?.pct !== undefined ? budgetBar(s.pct) : nothing}</div>${this.input(c.id, b.budgets[c.id])}</div>`; })}</div>
    </div>`;
  }
}

export class PlutusRecurring extends HestiaElement {
  static properties = { ...HestiaElement.properties, items: { state: true }, cur: { state: true } };
  declare items: any[] | null | undefined;
  declare cur: string;
  static styles = [...HestiaElement.styles, plutusStyles];
  constructor() { super(); this.items = undefined; this.cur = 'EUR'; }
  connectedCallback() { super.connectedCallback(); this.load(); this.onHost('refresh', () => this.load()); }
  private async load() {
    const r = await this.host.api('GET', `${API}/recurring`);
    this.items = r.ok ? r.data.items : null;
    if (r.ok) this.cur = r.data.currency;
  }
  private async set(r: any, status: string) {
    const res = await call(this.host, 'POST', `${API}/recurring/${r.id}`, { body: { status } });
    if (res.ok) this.host.toast(status === 'dismissed' ? `${r.merchant}: non è ricorrente` : `${r.merchant} confermato`, 'success',
      status === 'dismissed' ? { label: 'Annulla', run: async () => { await call(this.host, 'POST', `${API}/recurring/${r.id}`, { body: { status: 'suggested' } }); this.load(); } } : undefined);
    this.load();
  }
  render() {
    const items = this.items;
    const confirmed = (items || []).filter(r => r.status === 'confirmed');
    const monthly = confirmed.reduce((a, r) => a + (r.period === 'weekly' ? r.amount * 52 / 12 : r.period === 'yearly' ? r.amount / 12 : r.amount), 0);
    const row = (r: any) => html`<div class="li" style="cursor:default">
      <div class="grow click" @click=${() => this.host.navigate('movimenti', { q: r.merchant })}><b>${r.merchant}</b>
        <div class="small muted">${PERIOD[r.period] || r.period} · ${r.count} volte · ultimo ${dayLabel(r.last)} · prossimo ${dayLabel(r.next)}</div></div>
      <span class="tnum amt">${money(-r.amount, this.cur, true)}</span>
      ${r.status === 'suggested' ? html`<hxk-button size="sm" icon="check" @click=${() => this.set(r, 'confirmed')}>Sì</hxk-button>` : nothing}
      <hxk-button size="sm" variant="ghost" icon="x" title="Non è ricorrente" @click=${() => this.set(r, 'dismissed')}></hxk-button></div>`;
    return html`<div class="page">
      <div class="head"><button class="link" @click=${() => this.host.navigate('panoramica')}>‹ Spese</button><h1>Abbonamenti</h1></div>
      ${items === undefined ? html`<hxk-state kind="loading"></hxk-state>` : items === null ? html`<hxk-state kind="offline" @retry=${() => this.load()}></hxk-state>` : html`
        ${confirmed.length ? html`<hxk-stat .items=${[{ label: 'Al mese', value: money(monthly, this.cur) }, { label: "All'anno", value: money(monthly * 12, this.cur) },
          { label: 'Attivi', value: confirmed.length }]}></hxk-stat>` : nothing}
        ${items.filter(r => r.status === 'suggested').length ? html`<div class="card col"><h2>Mi sembrano ricorrenti</h2>
          <div class="small muted">Stesso esercente, importo simile, a intervalli regolari. Confermi?</div>
          <div class="list">${items.filter(r => r.status === 'suggested').map(row)}</div></div>` : nothing}
        <div class="card col"><h2>Confermati</h2>${confirmed.length ? html`<div class="list">${confirmed.map(row)}</div>`
          : html`<div class="empty">Nessuno ancora: li riconosco dopo 3 pagamenti uguali (1 all'anno: dopo 2).</div>`}</div>`}
    </div>`;
  }
}
