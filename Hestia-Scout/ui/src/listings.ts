import { HestiaElement, css, html, nothing } from '@hestia/webui-sdk';
import { Listing, Stats, ago, cardStyles, compactEuro, euro, facts, num, photo, statusTone } from './shared';

interface Filters { q: string; city: string; status: string; flag: string; price_max: string; rooms_min: string; sort: string; }
const EMPTY: Filters = { q: '', city: '', status: '', flag: '', price_max: '', rooms_min: '', sort: 'new' };
const PAGE = 24;

/** Mark/unmark a listing with optimistic update + Annulla. Shared by the list and the detail page. */
export async function setFlag(el: HestiaElement, l: Listing, flag: Listing['flag'], done: (l: Listing) => void) {
  const before = l.flag;
  const next = l.flag === flag ? '' : flag;
  done({ ...l, flag: next });
  const r = await el.host.api<Listing>('PATCH', `/api/ui/listings/${l.id}`, { body: { flag: next } });
  if (!r.ok) {
    done({ ...l, flag: before });
    el.host.toast(r.error === 'offline' ? 'Sei offline: riprova quando torna la rete' : 'Non sono riuscito a salvare', 'danger');
    return;
  }
  const text = next === 'favorite' ? 'Aggiunta alle preferite' : next === 'discarded' ? 'Casa scartata' : 'Segno tolto';
  el.host.toast(text, 'success', {
    label: 'Annulla',
    run: async () => {
      const u = await el.host.api<Listing>('PATCH', `/api/ui/listings/${l.id}`, { body: { flag: before } });
      if (u.ok) done(u.data);
    },
  });
}

/** Page «Case»: KPI, filters, cards. */
export class ScoutListings extends HestiaElement {
  static properties = { ...HestiaElement.properties, items: { state: true }, total: { state: true }, stats: { state: true },
    f: { state: true }, cities: { state: true }, loading: { state: true }, error: { state: true }, more: { state: true },
    showFilters: { state: true }, cycling: { state: true } };
  declare items: Listing[]; declare total: number; declare stats: Stats | null; declare f: Filters;
  declare cities: string[]; declare loading: boolean; declare error: string; declare more: boolean;
  declare showFilters: boolean; declare cycling: boolean;
  private timer = 0;

  static styles = [...HestiaElement.styles, cardStyles, css`
    .head { display: flex; align-items: flex-end; gap: 12px; flex-wrap: wrap; }
    .head .sub { color: var(--text-3); font-size: 13px; margin-top: 2px; }
    .head .acts { margin-left: auto; display: flex; gap: 8px; }
    .bar { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
    .bar .q { flex: 1 1 220px; }
    .seg { display: inline-flex; border: 1px solid var(--border-strong); border-radius: var(--radius-md); overflow: hidden; }
    .seg button { border: 0; background: var(--surface); color: var(--text-2); padding: 6px 12px; font: inherit; cursor: pointer; }
    .seg button + button { border-left: 1px solid var(--border); }
    .seg button.on { background: var(--accent-soft); color: var(--text); font-weight: 500; }
    .adv { display: flex; gap: 8px; flex-wrap: wrap; }
    .adv label { display: flex; flex-direction: column; gap: 3px; font-size: 12px; color: var(--text-3); }
    .adv input { width: 130px; }
    .grid { --min: 250px; }
    .moreb { align-self: center; }
    .ftoggle { display: none; }
    .count { color: var(--text-3); font-size: 13px; }
    @media (max-width: 860px) {
      .ftoggle { display: inline-flex; }
      .adv:not(.open) { display: none; }
      .grid { --min: 100%; }
      .seg { width: 100%; } .seg button { flex: 1; padding: 7px 4px; }
    }
  `];

  constructor() {
    super();
    this.items = []; this.total = 0; this.stats = null; this.cities = []; this.loading = true; this.error = '';
    this.more = false; this.showFilters = false; this.cycling = false; this.f = { ...EMPTY };
  }

  connectedCallback() {
    super.connectedCallback();
    const saved = this.host.config.get<Partial<Filters>>('filters', {});
    const fromQuery: Partial<Filters> = {};
    for (const k of Object.keys(EMPTY) as (keyof Filters)[]) if (this.ctx.query?.[k]) fromQuery[k] = this.ctx.query[k];
    this.f = { ...EMPTY, ...saved, ...fromQuery };
    this.load();
    this.loadStats();
    this.onHost('refresh', () => { this.load(); this.loadStats(); });
    this.onHost('online', () => this.load());
  }

  private query(offset = 0) {
    const q: Record<string, string | number> = { sort: this.f.sort, offset, limit: PAGE };
    for (const k of ['q', 'city', 'status', 'flag', 'price_max', 'rooms_min'] as const) if (this.f[k]) q[k] = this.f[k];
    return q;
  }

  async load(append = false) {
    this.loading = true; this.error = '';
    const r = await this.host.api<{ total: number; items: Listing[]; cities: string[] }>('GET', '/api/ui/listings',
      { query: this.query(append ? this.items.length : 0) });
    this.loading = false;
    if (!r.ok) { this.error = r.error || 'error'; return; }
    this.items = append ? [...this.items, ...r.data.items] : r.data.items;
    this.total = r.data.total; this.cities = r.data.cities;
    this.more = this.items.length < this.total;
  }

  async loadStats() {
    const r = await this.host.api<Stats>('GET', '/api/ui/stats');
    if (r.ok) this.stats = r.data;
  }

  private set<K extends keyof Filters>(k: K, v: Filters[K], debounce = false) {
    this.f = { ...this.f, [k]: v };
    void this.host.config.set('filters', { ...this.f, q: '' });
    clearTimeout(this.timer);
    if (debounce) this.timer = window.setTimeout(() => this.load(), 300); else this.load();
  }

  private replace(l: Listing) {
    const hide = (this.f.flag === '' && l.flag === 'discarded') || (this.f.flag && this.f.flag !== 'all' && l.flag !== this.f.flag);
    this.items = hide ? this.items.filter(i => i.id !== l.id) : this.items.map(i => i.id === l.id ? l : i);
    if (hide) this.total = Math.max(0, this.total - 1);
    this.loadStats();
  }

  private async cycle() {
    this.cycling = true;
    const r = await this.host.api<{ status: string }>('POST', '/api/ui/cycle');
    this.cycling = false;
    if (!r.ok) { this.host.toast('Non riesco ad avviare il controllo', 'danger'); return; }
    this.host.toast(r.data.status === 'busy' ? 'Un controllo è già in corso' : 'Controllo email avviato: le nuove case arrivano a breve', 'info');
    window.setTimeout(() => { this.load(); this.loadStats(); }, 20_000);
  }

  render() {
    const s = this.stats;
    return html`<div class="page">
      <div class="head">
        <div><h1>Case</h1><div class="sub">${s ? `${num(s.total)} case seguite · ${num(s.new)} nuove questa settimana` : 'Annunci arrivati per email'}</div></div>
        <div class="acts">
          <hxk-button variant="ghost" icon="chart" @click=${() => this.host.navigate('statistiche')}>Statistiche</hxk-button>
          <hxk-button icon="refresh" ?loading=${this.cycling} @click=${() => this.cycle()}>Controlla email</hxk-button>
        </div>
      </div>
      ${s && !this.ctx.phone ? html`<hxk-stat .items=${[
        { label: 'Seguite', value: num(s.total) },
        { label: 'Nuove (7 giorni)', value: num(s.new), tone: s.new ? 'success' : undefined },
        { label: 'Preferite', value: num(s.favorites) },
        { label: 'Prezzo medio', value: compactEuro(s.avg_price) },
        { label: '€/m² medio', value: s.avg_ppm2 ? num(s.avg_ppm2) : '—' },
      ]}></hxk-stat>` : nothing}
      <div class="bar">
        <input class="q" type="search" placeholder="Cerca per via, zona, titolo…" .value=${this.f.q}
               @input=${(e: Event) => this.set('q', (e.target as HTMLInputElement).value, true)} aria-label="Cerca">
        <select aria-label="Città" .value=${this.f.city} @change=${(e: Event) => this.set('city', (e.target as HTMLSelectElement).value)}>
          <option value="">Tutte le città</option>
          ${this.cities.map(c => html`<option value=${c} ?selected=${c === this.f.city}>${c}</option>`)}
        </select>
        <select aria-label="Ordina" @change=${(e: Event) => this.set('sort', (e.target as HTMLSelectElement).value)}>
          ${[['new', 'Più recenti'], ['price_asc', 'Prezzo ↑'], ['price_desc', 'Prezzo ↓'], ['ppm2', '€/m² più basso'], ['surface', 'Più grandi']]
            .map(([v, l]) => html`<option value=${v} ?selected=${v === this.f.sort}>${l}</option>`)}
        </select>
        <hxk-button class="ftoggle" variant="ghost" icon="filter" @click=${() => this.showFilters = !this.showFilters}>Filtri</hxk-button>
      </div>
      <div class="adv ${this.showFilters ? 'open' : ''}">
        <div class="seg" role="tablist" aria-label="Quali case">
          ${[['', 'Da valutare'], ['favorite', 'Preferite'], ['discarded', 'Scartate'], ['all', 'Tutte']].map(([v, l]) =>
            html`<button role="tab" class=${this.f.flag === v ? 'on' : ''} aria-selected=${this.f.flag === v} @click=${() => this.set('flag', v)}>${l}</button>`)}
        </div>
        <label>Prezzo max<input type="number" inputmode="numeric" step="10000" placeholder="€" .value=${this.f.price_max}
               @change=${(e: Event) => this.set('price_max', (e.target as HTMLInputElement).value)}></label>
        <label>Locali min<input type="number" inputmode="numeric" min="1" .value=${this.f.rooms_min}
               @change=${(e: Event) => this.set('rooms_min', (e.target as HTMLInputElement).value)}></label>
        <label>Stato<select @change=${(e: Event) => this.set('status', (e.target as HTMLSelectElement).value)}>
          ${[['', 'Tutti'], ['available', 'Disponibile'], ['in_negotiation', 'In trattativa'], ['sold', 'Venduto'], ['unknown', 'Da verificare']]
            .map(([v, l]) => html`<option value=${v} ?selected=${v === this.f.status}>${l}</option>`)}
        </select></label>
      </div>
      ${this.body()}
    </div>`;
  }

  private body() {
    if (this.error && !this.items.length)
      return html`<hxk-state kind=${this.error === 'offline' ? 'offline' : 'error'} @retry=${() => this.load()}></hxk-state>`;
    if (this.loading && !this.items.length) return html`<hxk-state kind="loading"></hxk-state>`;
    if (!this.items.length)
      return html`<hxk-state kind="empty" text=${this.f.flag === 'favorite' ? 'Nessuna preferita: tocca la stella su una casa per salvarla' : 'Nessuna casa con questi filtri'}></hxk-state>`;
    return html`<div class="count">${num(this.total)} case</div>
      <div class="grid">${this.items.map(l => this.card(l))}</div>
      ${this.more ? html`<hxk-button class="moreb" variant="ghost" ?loading=${this.loading} @click=${() => this.load(true)}>Mostra altre</hxk-button>` : nothing}`;
  }

  private card(l: Listing) {
    const stop = (e: Event) => e.stopPropagation();
    return html`<article class="lc ${l.flag}" @click=${() => this.host.navigate('case/' + l.id)}>
      ${photo(l.image)}
      <div class="lb">
        <div class="price">${euro(l.price)}${l.price_per_m2 ? html`<span class="ppm">${num(l.price_per_m2)} €/m²</span>` : nothing}</div>
        <div class="tt truncate" title=${l.title}>${l.title}</div>
        <div class="ft truncate">${facts(l)}</div>
        <div class="foot">
          ${l.status !== 'unknown' ? html`<hxk-badge tone=${statusTone(l.status)}>${l.status_label}</hxk-badge>` : nothing}
          <span class="when">${ago(l.created_at)}</span>
          <button class="flagbtn fav ${l.flag === 'favorite' ? 'on' : ''}" title=${l.flag === 'favorite' ? 'Togli dalle preferite' : 'Preferita'}
                  aria-pressed=${l.flag === 'favorite'} @click=${(e: Event) => { stop(e); setFlag(this, l, 'favorite', x => this.replace(x)); }}>
            <hxk-icon name="star" size="16"></hxk-icon></button>
          <button class="flagbtn dis ${l.flag === 'discarded' ? 'on' : ''}" title=${l.flag === 'discarded' ? 'Rimetti tra le case da valutare' : 'Scarta'}
                  aria-pressed=${l.flag === 'discarded'} @click=${(e: Event) => { stop(e); setFlag(this, l, 'discarded', x => this.replace(x)); }}>
            <hxk-icon name="eye-off" size="16"></hxk-icon></button>
        </div>
      </div>
    </article>`;
  }
}
