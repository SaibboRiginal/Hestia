/**
 * <plutus-stats>      — last months: spent and income per month, per category, top merchants; export.
 * <plutus-categories> — categories (rename, archive, add) and the rules that file movements by merchant.
 */
import { HestiaElement, html, nothing, tr } from '@hestia/webui-sdk';
import { API, call, catDot, dropMeta, money, plutusStyles } from './util';

export class PlutusStats extends HestiaElement {
  static properties = { ...HestiaElement.properties, s: { state: true }, months: { state: true } };
  declare s: any;
  declare months: number;
  static styles = [...HestiaElement.styles, plutusStyles];
  constructor() { super(); this.s = undefined; this.months = 6; }
  connectedCallback() { super.connectedCallback(); this.load(); this.onHost('refresh', () => this.load()); }
  private async load() { const r = await this.host.api('GET', `${API}/stats`, { query: { months: this.months } }); this.s = r.ok ? r.data : null; }
  private async exportData() {
    const r = await call(this.host, 'GET', `${API}/export`);
    if (!r.ok) return;
    const blob = new Blob([JSON.stringify(r.data.data, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = r.data.filename; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  }
  render() {
    const s = this.s;
    const unit = s?.currency === 'EUR' ? '€' : s?.currency || '';
    return html`<div class="page">
      <div class="head"><button class="link" @click=${() => this.host.navigate('panoramica')}>${tr('‹ Expenses')}</button><h1>${tr("Statistics")}</h1></div>
      <div class="tabs">${[3, 6, 12, 24].map(n => html`<button class="tab" aria-pressed=${this.months === n} @click=${() => { this.months = n; this.s = undefined; this.load(); }}>${n} ${tr("months")}</button>`)}</div>
      ${s === undefined ? html`<hxk-state kind="loading"></hxk-state>` : s === null ? html`<hxk-state kind="offline" @retry=${() => this.load()}></hxk-state>` : html`
        <hxk-stat .items=${[{ label: tr('Average spending per month'), value: money(s.avg_spent, s.currency) },
          { label: tr('Total expenses'), value: money(s.months.reduce((a: number, m: any) => a + m.spent, 0), s.currency) },
          { label: tr('Total income'), value: money(s.months.reduce((a: number, m: any) => a + m.income, 0), s.currency) }]}></hxk-stat>
        <div class="card col"><h2>${tr("Month by month")}</h2>
          <hxk-chart type="bar" height="180" unit=${unit} .labels=${s.months.map((m: any) => m.label.split(' ')[0].slice(0, 3))}
            .series=${[{ name: tr('Expenses'), values: s.months.map((m: any) => m.spent) }, { name: tr('f.pl::Income'), values: s.months.map((m: any) => m.income) }]}></hxk-chart></div>
        ${s.categories.length ? html`<div class="card col"><h2>${tr("By category")}</h2>
          <hxk-chart type="line" height="180" unit=${unit} .labels=${s.months.map((m: any) => m.label.split(' ')[0].slice(0, 3))}
            .series=${s.categories.slice(0, 6).map((c: any) => ({ name: c.label, values: s.months.map((m: any) => m.by_category[c.id] || 0) }))}></hxk-chart>
          <div class="list">${s.categories.map((c: any) => html`<div class="li" @click=${() => this.host.navigate('movimenti', { categoria: c.id })}>
            ${catDot(c)}<span class="grow truncate">${c.label}</span><span class="small muted tnum">${tr("average")} ${money(c.avg, s.currency)}</span>
            <span class="tnum amt">${money(c.total, s.currency)}</span></div>`)}</div></div>` : nothing}
        ${s.merchants.length ? html`<div class="card col"><h2>${tr("Merchants")}</h2>${s.merchants.map((m: any) => html`<div class="between small" style="padding:4px 0">
          <span class="truncate">${m.merchant} <span class="muted">×${m.count}</span></span><span class="tnum">${money(m.total, s.currency)}</span></div>`)}</div>` : nothing}
        <div class="row wrap"><hxk-button variant="ghost" icon="link" @click=${() => this.exportData()}>${tr("Export everything (JSON)")}</hxk-button></div>`}
    </div>`;
  }
}

export class PlutusCategories extends HestiaElement {
  static properties = { ...HestiaElement.properties, cats: { state: true }, rules: { state: true }, newCat: { state: true },
    newRule: { state: true }, q: { state: true } };
  declare cats: any[] | null | undefined;
  declare rules: any[];
  declare newCat: string;
  declare newRule: { pattern: string; category: string };
  declare q: string;
  static styles = [...HestiaElement.styles, plutusStyles];
  constructor() { super(); this.cats = undefined; this.rules = []; this.newCat = ''; this.newRule = { pattern: '', category: '' }; this.q = ''; }
  connectedCallback() { super.connectedCallback(); this.load(); this.onHost('refresh', () => this.load()); }
  private async load() {
    const [c, r] = await Promise.all([this.host.api('GET', `${API}/categories`, { query: { archived: true } }), this.host.api('GET', `${API}/rules`)]);
    this.cats = c.ok ? c.data.items : null;
    this.rules = r.ok ? r.data.items : [];
  }
  private async saveCat(c: any, patch: any) {
    const r = await call(this.host, 'PUT', `${API}/categories/${c.id}`, { body: patch });
    if (r.ok) { dropMeta(); this.load(); }
  }
  private async addCat() {
    if (!this.newCat.trim()) return;
    const r = await call(this.host, 'POST', `${API}/categories`, { body: { label: this.newCat.trim(), kind: 'expense' } });
    if (r.ok) { this.newCat = ''; dropMeta(); this.load(); }
  }
  private async addRule() {
    const r = await call(this.host, 'POST', `${API}/rules`, { body: this.newRule });
    if (r.ok) { this.host.toast(`«${r.data.pattern}» → ${this.label(r.data.category)}`, 'success'); this.newRule = { pattern: '', category: this.newRule.category }; this.load(); }
  }
  private async delRule(r: any) { const res = await call(this.host, 'DELETE', `${API}/rules/${r.id}`); if (res.ok) this.load(); }
  private label(id: string) { return (this.cats || []).find(c => c.id === id)?.label || id; }
  render() {
    const cats = this.cats;
    const rules = this.rules.filter(r => !this.q || `${r.pattern} ${this.label(r.category)}`.toLowerCase().includes(this.q.toLowerCase()));
    return html`<div class="page">
      <div class="head"><button class="link" @click=${() => this.host.navigate('panoramica')}>${tr('‹ Expenses')}</button><h1>${tr("Categories and rules")}</h1></div>
      ${cats === undefined ? html`<hxk-state kind="loading"></hxk-state>` : cats === null ? html`<hxk-state kind="offline" @retry=${() => this.load()}></hxk-state>` : html`
        <div class="card col"><h2>${tr("Categories")}</h2>
          <div class="list">${cats.map(c => html`<div class="li" style="cursor:default;${c.archived ? 'opacity:.55' : ''}">${catDot(c)}
            <input class="in grow" .value=${c.label} @change=${(e: any) => this.saveCat(c, { label: e.target.value })}>
            <span class="small muted">${c.kind === 'income' ? 'entrata' : c.kind === 'transfer' ? tr('doesn\'t count') : 'spesa'}</span>
            <hxk-button size="sm" variant="ghost" @click=${() => this.saveCat(c, { archived: !c.archived })}>${c.archived ? tr('Turn back on') : tr('f::Archive')}</hxk-button></div>`)}</div>
          <div class="row"><input class="in grow" placeholder=${tr("New category")} .value=${this.newCat} @input=${(e: any) => (this.newCat = e.target.value)}
            @keydown=${(e: KeyboardEvent) => e.key === 'Enter' && this.addCat()}><hxk-button icon="plus" @click=${() => this.addCat()}>${tr("Add")}</hxk-button></div></div>
        <div class="card col"><h2>${tr("Rules")}</h2>
          <div class="small muted">${tr("If the merchant name or the description contains the text, the transaction goes in that category. You also learn them by fixing a transaction with «always use».")}</div>
          <div class="row wrap"><input class="in grow" placeholder=${tr("Text, e.g. gym")} .value=${this.newRule.pattern} @input=${(e: any) => (this.newRule = { ...this.newRule, pattern: e.target.value })}>
            <select class="in" @change=${(e: any) => (this.newRule = { ...this.newRule, category: e.target.value })}>
              <option value="">${tr("Category…")}</option>${cats.filter(c => !c.archived).map(c => html`<option value=${c.id} ?selected=${c.id === this.newRule.category}>${c.label}</option>`)}</select>
            <hxk-button icon="plus" ?disabled=${!this.newRule.pattern || !this.newRule.category} @click=${() => this.addRule()}>${tr("Add")}</hxk-button></div>
          <input class="in" type="search" placeholder=${tr("Search among {0} rules", this.rules.length)} .value=${this.q} @input=${(e: any) => (this.q = e.target.value)}>
          <div class="list">${rules.map(r => html`<div class="li" style="cursor:default"><span class="grow truncate">«${r.pattern}»</span>
            <span class="small">${this.label(r.category)}</span>${r.source === 'user' ? html`<span class="pill good">${tr("f::yours")}</span>` : nothing}
            <hxk-button size="sm" variant="ghost" icon="trash" @click=${() => this.delRule(r)}></hxk-button></div>`)}</div></div>`}
    </div>`;
  }
}
