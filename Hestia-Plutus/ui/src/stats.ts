/**
 * <plutus-stats>      — last months: spent and income per month, per category, top merchants; export.
 * <plutus-categories> — categories (rename, archive, add) and the rules that file movements by merchant.
 */
import { HestiaElement, html, nothing } from '@hestia/webui-sdk';
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
      <div class="head"><button class="link" @click=${() => this.host.navigate('panoramica')}>‹ Spese</button><h1>Statistiche</h1></div>
      <div class="tabs">${[3, 6, 12, 24].map(n => html`<button class="tab" aria-pressed=${this.months === n} @click=${() => { this.months = n; this.s = undefined; this.load(); }}>${n} mesi</button>`)}</div>
      ${s === undefined ? html`<hxk-state kind="loading"></hxk-state>` : s === null ? html`<hxk-state kind="offline" @retry=${() => this.load()}></hxk-state>` : html`
        <hxk-stat .items=${[{ label: 'Media spese al mese', value: money(s.avg_spent, s.currency) },
          { label: 'Totale spese', value: money(s.months.reduce((a: number, m: any) => a + m.spent, 0), s.currency) },
          { label: 'Totale entrate', value: money(s.months.reduce((a: number, m: any) => a + m.income, 0), s.currency) }]}></hxk-stat>
        <div class="card col"><h2>Mese per mese</h2>
          <hxk-chart type="bar" height="180" unit=${unit} .labels=${s.months.map((m: any) => m.label.split(' ')[0].slice(0, 3))}
            .series=${[{ name: 'Spese', values: s.months.map((m: any) => m.spent) }, { name: 'Entrate', values: s.months.map((m: any) => m.income) }]}></hxk-chart></div>
        ${s.categories.length ? html`<div class="card col"><h2>Per categoria</h2>
          <hxk-chart type="line" height="180" unit=${unit} .labels=${s.months.map((m: any) => m.label.split(' ')[0].slice(0, 3))}
            .series=${s.categories.slice(0, 6).map((c: any) => ({ name: c.label, values: s.months.map((m: any) => m.by_category[c.id] || 0) }))}></hxk-chart>
          <div class="list">${s.categories.map((c: any) => html`<div class="li" @click=${() => this.host.navigate('movimenti', { categoria: c.id })}>
            ${catDot(c)}<span class="grow truncate">${c.label}</span><span class="small muted tnum">media ${money(c.avg, s.currency)}</span>
            <span class="tnum amt">${money(c.total, s.currency)}</span></div>`)}</div></div>` : nothing}
        ${s.merchants.length ? html`<div class="card col"><h2>Esercenti</h2>${s.merchants.map((m: any) => html`<div class="between small" style="padding:4px 0">
          <span class="truncate">${m.merchant} <span class="muted">×${m.count}</span></span><span class="tnum">${money(m.total, s.currency)}</span></div>`)}</div>` : nothing}
        <div class="row wrap"><hxk-button variant="ghost" icon="link" @click=${() => this.exportData()}>Esporta tutto (JSON)</hxk-button></div>`}
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
      <div class="head"><button class="link" @click=${() => this.host.navigate('panoramica')}>‹ Spese</button><h1>Categorie e regole</h1></div>
      ${cats === undefined ? html`<hxk-state kind="loading"></hxk-state>` : cats === null ? html`<hxk-state kind="offline" @retry=${() => this.load()}></hxk-state>` : html`
        <div class="card col"><h2>Categorie</h2>
          <div class="list">${cats.map(c => html`<div class="li" style="cursor:default;${c.archived ? 'opacity:.55' : ''}">${catDot(c)}
            <input class="in grow" .value=${c.label} @change=${(e: any) => this.saveCat(c, { label: e.target.value })}>
            <span class="small muted">${c.kind === 'income' ? 'entrata' : c.kind === 'transfer' ? 'non conta' : 'spesa'}</span>
            <hxk-button size="sm" variant="ghost" @click=${() => this.saveCat(c, { archived: !c.archived })}>${c.archived ? 'Riattiva' : 'Archivia'}</hxk-button></div>`)}</div>
          <div class="row"><input class="in grow" placeholder="Nuova categoria" .value=${this.newCat} @input=${(e: any) => (this.newCat = e.target.value)}
            @keydown=${(e: KeyboardEvent) => e.key === 'Enter' && this.addCat()}><hxk-button icon="plus" @click=${() => this.addCat()}>Aggiungi</hxk-button></div></div>
        <div class="card col"><h2>Regole</h2>
          <div class="small muted">Se il nome dell'esercente o la descrizione contiene il testo, il movimento va in quella categoria. Le impari anche
            correggendo un movimento con «usa sempre».</div>
          <div class="row wrap"><input class="in grow" placeholder="Testo, es. palestra" .value=${this.newRule.pattern} @input=${(e: any) => (this.newRule = { ...this.newRule, pattern: e.target.value })}>
            <select class="in" @change=${(e: any) => (this.newRule = { ...this.newRule, category: e.target.value })}>
              <option value="">Categoria…</option>${cats.filter(c => !c.archived).map(c => html`<option value=${c.id} ?selected=${c.id === this.newRule.category}>${c.label}</option>`)}</select>
            <hxk-button icon="plus" ?disabled=${!this.newRule.pattern || !this.newRule.category} @click=${() => this.addRule()}>Aggiungi</hxk-button></div>
          <input class="in" type="search" placeholder="Cerca tra ${this.rules.length} regole" .value=${this.q} @input=${(e: any) => (this.q = e.target.value)}>
          <div class="list">${rules.map(r => html`<div class="li" style="cursor:default"><span class="grow truncate">«${r.pattern}»</span>
            <span class="small">${this.label(r.category)}</span>${r.source === 'user' ? html`<span class="pill good">tua</span>` : nothing}
            <hxk-button size="sm" variant="ghost" icon="trash" @click=${() => this.delRule(r)}></hxk-button></div>`)}</div></div>`}
    </div>`;
  }
}
