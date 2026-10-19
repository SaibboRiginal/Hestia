/**
 * <plutus-transactions> — every movement of a month: search, category, account, «da rivedere»; add by hand.
 * <plutus-transaction>  — one movement: edit, change category (and «sempre per questo esercente»), links, delete.
 * <plutus-tx-form>      — add / edit sheet (event 'close', detail = saved row or null).
 */
import { HestiaElement, html, nothing } from '@hestia/webui-sdk';
import { API, SOURCE, addMonths, call, dayLabel, meta, money, plutusStyles, today, txRow } from './util';

export class PlutusTxForm extends HestiaElement {
  static properties = { ...HestiaElement.properties, tx: { attribute: false }, m: { state: true }, f: { state: true }, busy: { state: true } };
  declare tx: any;
  declare m: any;
  declare f: any;
  declare busy: boolean;
  static styles = [...HestiaElement.styles, plutusStyles];
  constructor() { super(); this.tx = null; this.m = null; this.f = {}; this.busy = false; }
  async connectedCallback() {
    super.connectedCallback();
    const t = this.tx || {};
    this.f = { type: t.amount > 0 ? 'income' : 'expense', amount: t.amount ? String(Math.abs(t.amount)).replace('.', ',') : '',
      merchant: t.merchant || '', category: t.category || '', date: t.date || today(), account: t.account || 'contanti',
      notes: t.notes || '', learn: false };
    this.m = await meta(this.host);
  }
  private set(k: string, v: any) { this.f = { ...this.f, [k]: v }; }
  private async save() {
    const f = this.f;
    if (!String(f.amount).trim()) { this.host.toast('Manca l\'importo', 'warning'); return; }
    this.busy = true;
    const body: any = { amount: f.amount, type: f.type, merchant: f.merchant, date: f.date, account: f.account, notes: f.notes };
    if (f.category) body.category = f.category;
    const r = this.tx?.id ? await call(this.host, 'PUT', `${API}/transactions/${this.tx.id}`, { body: { ...body, learn: f.learn } })
      : await call(this.host, 'POST', `${API}/transactions`, { body: { ...body, source: 'manual' } });
    this.busy = false;
    if (r.ok) { this.host.toast(this.tx?.id ? 'Salvato' : `Registrato: ${money(r.data.amount, r.data.currency, true)}`, 'success'); this.close(r.data); }
  }
  private close(saved: any = null) { this.dispatchEvent(new CustomEvent('close', { detail: saved, bubbles: true, composed: true })); }
  render() {
    const f = this.f;
    const cats = (this.m?.categories || []).filter((c: any) => f.type === 'income' ? c.kind !== 'expense' : c.kind !== 'income');
    return html`<div class="sheet" @click=${(e: Event) => { if (e.target === e.currentTarget) this.close(); }}><div class="card col">
      <div class="between"><h2>${this.tx?.id ? 'Modifica movimento' : 'Nuovo movimento'}</h2><hxk-button variant="ghost" icon="x" @click=${() => this.close()}></hxk-button></div>
      <div class="tabs">${[['expense', 'Spesa'], ['income', 'Entrata']].map(([k, l]) => html`<button class="tab" aria-pressed=${f.type === k} @click=${() => this.set('type', k)}>${l}</button>`)}</div>
      <div class="form">
        <label>Importo<input class="in money" inputmode="decimal" placeholder="0,00" .value=${f.amount} @input=${(e: any) => this.set('amount', e.target.value)}></label>
        <label>Data<input class="in" type="date" .value=${f.date} @change=${(e: any) => this.set('date', e.target.value)}></label>
        <label class="full">Dove / cosa<input class="in" placeholder="es. Esselunga, bar, affitto" .value=${f.merchant} @input=${(e: any) => this.set('merchant', e.target.value)}></label>
        <label>Conto<select class="in" @change=${(e: any) => this.set('account', e.target.value)}>
          ${(this.m?.accounts || []).map((a: any) => html`<option value=${a.id} ?selected=${a.id === f.account}>${a.name}</option>`)}</select></label>
        <label>Categoria<select class="in" @change=${(e: any) => this.set('category', e.target.value)}>
          <option value="" ?selected=${!f.category}>Automatica (dalle regole)</option>
          ${cats.map((c: any) => html`<option value=${c.id} ?selected=${c.id === f.category}>${c.label}</option>`)}</select></label>
        <label class="full">Note<input class="in" .value=${f.notes} @input=${(e: any) => this.set('notes', e.target.value)}></label>
        ${this.tx?.id && f.merchant ? html`<label class="full" style="flex-direction:row;align-items:center;gap:8px">
          <input type="checkbox" .checked=${f.learn} @change=${(e: any) => this.set('learn', e.target.checked)}> Da ora in poi stessa categoria per «${f.merchant}»</label>` : nothing}
      </div>
      <div class="row"><hxk-button variant="primary" icon="check" ?loading=${this.busy} @click=${() => this.save()}>Salva</hxk-button></div>
    </div></div>`;
  }
}

export class PlutusTransactions extends HestiaElement {
  static properties = { ...HestiaElement.properties, items: { state: true }, m: { state: true }, month: { state: true }, cat: { state: true },
    account: { state: true }, q: { state: true }, review: { state: true }, form: { state: true }, label: { state: true } };
  declare items: any[] | null | undefined;
  declare m: any;
  declare month: string;
  declare cat: string;
  declare account: string;
  declare q: string;
  declare review: boolean;
  declare form: boolean;
  declare label: string;
  private timer = 0;
  static styles = [...HestiaElement.styles, plutusStyles];
  constructor() { super(); this.items = undefined; this.m = null; this.month = ''; this.cat = ''; this.account = ''; this.q = ''; this.review = false; this.form = false; this.label = ''; }
  connectedCallback() {
    super.connectedCallback();
    const q = this.ctx?.query || {};
    this.cat = q.categoria || ''; this.q = q.q || ''; this.review = q.rivedere === '1'; this.month = q.mese || ''; this.account = q.conto || '';
    if (q.nuovo === '1') this.form = true;
    this.load();
    this.onHost('refresh', () => this.load());
  }
  private async load() {
    this.m = await meta(this.host);
    if (!this.month) this.month = this.m?.month || today();
    const query: any = this.review ? { status: 'to_review', limit: 1000 } : { month: this.month, limit: 2000 };
    if (this.cat) query.category = this.cat;
    if (this.account) query.account = this.account;
    if (this.q) query.q = this.q;
    const [r, s] = await Promise.all([this.host.api('GET', `${API}/transactions`, { query }),
      this.host.api('GET', `${API}/summary`, { query: { month: this.month } })]);
    this.items = r.ok ? r.data.items : null;
    this.label = s.ok ? s.data.label : '';
  }
  private shift(n: number) { this.month = addMonths(this.month, n); this.items = undefined; this.load(); }
  private search(v: string) { this.q = v; clearTimeout(this.timer); this.timer = window.setTimeout(() => this.load(), 300); }
  render() {
    const cur = this.m?.currency || 'EUR';
    const items = this.items;
    const total = (items || []).filter(t => t.counted).reduce((a, t) => a + t.amount, 0);
    const days: Record<string, any[]> = {};
    for (const t of items || []) (days[t.date] ||= []).push(t);
    return html`<div class="page">
      <div class="between wrap"><div class="head"><button class="link" @click=${() => this.host.navigate('panoramica')}>‹ Spese</button><h1>Movimenti</h1></div>
        <hxk-button variant="primary" icon="plus" @click=${() => (this.form = true)}>Nuovo</hxk-button></div>
      <div class="row wrap">
        ${this.review ? html`<span class="pill warn">Solo da rivedere</span>` : html`<hxk-button size="sm" variant="ghost" icon="chevron-left" @click=${() => this.shift(-1)}></hxk-button>
          <b style="min-width:120px;text-align:center">${this.label}</b>
          <hxk-button size="sm" variant="ghost" icon="chevron-right" @click=${() => this.shift(1)}></hxk-button>`}
        <button class="tab" aria-pressed=${this.review} @click=${() => { this.review = !this.review; this.load(); }}>Da rivedere</button>
        <select class="in" @change=${(e: any) => { this.cat = e.target.value; this.load(); }}>
          <option value="">Tutte le categorie</option>
          ${(this.m?.categories || []).map((c: any) => html`<option value=${c.id} ?selected=${c.id === this.cat}>${c.label}</option>`)}</select>
        <select class="in" @change=${(e: any) => { this.account = e.target.value; this.load(); }}>
          <option value="">Tutti i conti</option>
          ${(this.m?.accounts || []).map((a: any) => html`<option value=${a.id} ?selected=${a.id === this.account}>${a.name}</option>`)}</select>
        <input class="in grow" type="search" placeholder="Cerca esercente o nota" .value=${this.q} @input=${(e: any) => this.search(e.target.value)}>
      </div>
      ${items === undefined ? html`<hxk-state kind="loading"></hxk-state>` : items === null ? html`<hxk-state kind="offline" @retry=${() => this.load()}></hxk-state>`
        : !items.length ? html`<div class="card"><hxk-state kind="empty" text=${this.review ? 'Niente da rivedere 👍' : 'Nessun movimento.'}></hxk-state></div>` : html`
        <div class="small muted">${items.length} movimenti · saldo ${money(total, cur, true)}</div>
        ${Object.entries(days).map(([d, list]) => html`<h3 style="margin-top:6px">${dayLabel(d)}</h3>
          <div class="card list">${list.map(t => txRow(this.host, t, cur))}</div>`)}`}
      ${this.form ? html`<plutus-tx-form .host=${this.host} @close=${() => { this.form = false; this.load(); }}></plutus-tx-form>` : nothing}
    </div>`;
  }
}

export class PlutusTransaction extends HestiaElement {
  static properties = { ...HestiaElement.properties, t: { state: true }, m: { state: true }, edit: { state: true } };
  declare t: any;
  declare m: any;
  declare edit: boolean;
  static styles = [...HestiaElement.styles, plutusStyles];
  constructor() { super(); this.t = undefined; this.m = null; this.edit = false; }
  connectedCallback() { super.connectedCallback(); this.load(); this.onHost('refresh', () => this.load()); }
  private get txId() { return this.ctx?.params?.id || ''; }
  private async load() {
    this.m = await meta(this.host);
    const r = await this.host.api('GET', `${API}/transactions/${this.txId}`);
    this.t = r.ok ? r.data : r.status === 404 ? false : null;
  }
  private async setCategory(id: string, always: boolean) {
    const r = await call(this.host, 'PUT', `${API}/transactions/${this.t.id}`, { body: { category: id, learn: always } });
    if (r.ok) this.host.toast(always ? `Categoria salvata, anche per i prossimi «${this.t.merchant}»` : 'Categoria salvata', 'success');
    this.load();
  }
  private async confirmOk() { await call(this.host, 'PUT', `${API}/transactions/${this.t.id}`, { body: { status: 'confirmed' } }); this.load(); }
  private async unlink() { await call(this.host, 'PUT', `${API}/transactions/${this.t.id}`, { body: { linked_to: null } }); this.load(); }
  private async deleteTx() {
    if (!(await this.host.confirm('Eliminare il movimento?', `${this.t.merchant || 'Movimento'} ${money(this.t.amount, this.t.currency, true)}`, { label: 'Elimina', danger: true }))) return;
    const r = await call(this.host, 'DELETE', `${API}/transactions/${this.t.id}`);
    if (r.ok) { this.host.toast(r.data.label, 'success'); this.host.navigate('movimenti'); }
  }
  render() {
    const t = this.t;
    if (t === undefined) return html`<div class="page"><hxk-state kind="loading"></hxk-state></div>`;
    if (t === null) return html`<div class="page"><hxk-state kind="offline" @retry=${() => this.load()}></hxk-state></div>`;
    if (t === false) return html`<div class="page"><hxk-state kind="empty" text="Movimento non trovato"></hxk-state></div>`;
    const cur = t.currency || this.m?.currency || 'EUR';
    const cats = (this.m?.categories || []).filter((c: any) => t.amount > 0 ? c.kind !== 'expense' : c.kind !== 'income');
    const accounts: Record<string, string> = Object.fromEntries((this.m?.accounts || []).map((a: any) => [a.id, a.name]));
    return html`<div class="page">
      <div class="head"><button class="link" @click=${() => this.host.navigate('movimenti')}>‹ Movimenti</button></div>
      <div class="card col">
        <div class="between"><div><h1>${t.merchant || 'Movimento'}</h1><div class="muted small">${dayLabel(t.date)} · ${accounts[t.account] || t.account} · ${SOURCE[t.source] || t.source}</div></div>
          <div class="big amt ${t.amount > 0 ? 'in' : ''}">${money(t.amount, cur, true)}</div></div>
        ${t.status === 'to_review' ? html`<div class="note warning between"><span>Categoria da controllare (${t.category_label}).</span>
          <hxk-button size="sm" icon="check" @click=${() => this.confirmOk()}>Va bene così</hxk-button></div>` : nothing}
        ${!t.counted && t.linked_to ? html`<div class="note">Collegato a un pagamento PayPal: è lo stesso soldo visto due volte, conta una volta sola.
          <button class="link" @click=${() => this.unlink()}>Scollega</button></div>` : nothing}
        ${t.description && t.description !== t.merchant ? html`<div class="small muted">${t.description}</div>` : nothing}
        ${t.notes ? html`<div>${t.notes}</div>` : nothing}
        <h3>Categoria</h3>
        <div class="chips">${cats.map((c: any) => html`<button class="chip" aria-pressed=${c.id === t.category} @click=${() => this.setCategory(c.id, false)}>${c.label}</button>`)}</div>
        ${t.merchant ? html`<div class="small muted"><button class="link" @click=${() => this.setCategory(t.category, true)}>Usa sempre ${t.category_label}</button>
          per «${t.merchant}» (anche per i prossimi movimenti).</div>` : nothing}
        <div class="row wrap"><hxk-button icon="edit" @click=${() => (this.edit = true)}>Modifica</hxk-button>
          <hxk-button variant="danger" icon="trash" @click=${() => this.deleteTx()}>Elimina</hxk-button></div>
      </div>
      ${(t.linked || []).length ? html`<div class="card col"><h2>Collegati</h2><div class="list">${t.linked.map((x: any) => txRow(this.host, x, cur))}</div></div>` : nothing}
      ${(t.similar || []).filter((x: any) => x.id !== t.id).length ? html`<div class="card col"><h2>Altri da ${t.merchant}</h2>
        <div class="list">${t.similar.filter((x: any) => x.id !== t.id).map((x: any) => txRow(this.host, x, cur))}</div></div>` : nothing}
      ${this.edit ? html`<plutus-tx-form .host=${this.host} .tx=${t} @close=${() => { this.edit = false; this.load(); }}></plutus-tx-form>` : nothing}
    </div>`;
  }
}
