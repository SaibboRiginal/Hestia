import { HestiaElement, css, html, nothing } from '@hestia/webui-sdk';
import { Listing, Stats, compactEuro, euro, facts, num } from './shared';

async function loadStats(el: HestiaElement, city = ''): Promise<{ data?: Stats; error?: string }> {
  const r = await el.host.api<Stats>('GET', '/api/ui/stats', { query: city ? { city } : {} });
  return r.ok ? { data: r.data } : { error: r.error || 'error' };
}

const stateOf = (error: string, retry: () => void) =>
  html`<hxk-state kind=${error === 'offline' ? 'offline' : 'error'} @retry=${retry}></hxk-state>`;

/** Page «Statistiche case». */
export class ScoutStats extends HestiaElement {
  static properties = { ...HestiaElement.properties, s: { state: true }, city: { state: true }, error: { state: true } };
  declare s: Stats | null; declare city: string; declare error: string;
  static styles = [...HestiaElement.styles, css`
    .head { display: flex; align-items: flex-end; gap: 12px; flex-wrap: wrap; }
    .head select { margin-left: auto; }
    .two { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
    table { border-collapse: collapse; width: 100%; font-size: 13.5px; }
    th { text-align: left; font-weight: 500; color: var(--text-3); font-size: 12px; padding: 6px 8px; border-bottom: 1px solid var(--border); }
    td { padding: 7px 8px; border-bottom: 1px solid var(--border); } td.n, th.n { text-align: right; font-variant-numeric: tabular-nums; }
    tr.click { cursor: pointer; } tr.click:hover td { background: var(--surface-2); }
    .back { display: inline-flex; align-items: center; gap: 4px; color: var(--text-2); cursor: pointer; font-size: 13px; background: none; border: 0; padding: 0; font: inherit; }
    @media (max-width: 860px) { .two { grid-template-columns: minmax(0, 1fr); } }
  `];
  constructor() { super(); this.s = null; this.city = ''; this.error = ''; }
  connectedCallback() { super.connectedCallback(); this.load(); this.onHost('refresh', () => this.load()); }
  async load() { const r = await loadStats(this, this.city); this.error = r.error ?? ''; if (r.data) this.s = r.data; }

  render() {
    if (this.error && !this.s) return html`<div class="page">${stateOf(this.error, () => this.load())}</div>`;
    if (!this.s) return html`<div class="page"><hxk-state kind="loading"></hxk-state></div>`;
    const s = this.s;
    return html`<div class="page">
      <button class="back" @click=${() => this.host.navigate('case')}><hxk-icon name="chevron-left"></hxk-icon>Case</button>
      <div class="head"><h1>Statistiche case</h1>
        <select aria-label="Città" @change=${(e: Event) => { this.city = (e.target as HTMLSelectElement).value; this.load(); }}>
          <option value="">Tutte le città</option>
          ${s.cities.map(c => html`<option value=${c} ?selected=${c === this.city}>${c}</option>`)}
        </select>
      </div>
      <hxk-stat .items=${[
        { label: 'Seguite', value: num(s.total) }, { label: 'Nuove (7 giorni)', value: num(s.new) },
        { label: 'Disponibili', value: num(s.available) }, { label: 'Preferite', value: num(s.favorites) },
        { label: 'Prezzo medio', value: compactEuro(s.avg_price) }, { label: '€/m² medio', value: s.avg_ppm2 ? num(s.avg_ppm2) : '—' },
      ]}></hxk-stat>
      <div class="two">
        <hxk-card heading="Nuove case per settimana">
          <hxk-chart type="bar" .labels=${s.weeks.map(w => w.label)} .series=${[{ name: 'Nuove', values: s.weeks.map(w => w.count) }]}></hxk-chart>
        </hxk-card>
        <hxk-card heading="Stato degli annunci">
          ${s.by_status.length ? html`<hxk-chart type="donut" .labels=${s.by_status.map(b => b.label)}
              .series=${[{ name: 'Annunci', values: s.by_status.map(b => b.count) }]}></hxk-chart>` : html`<hxk-state kind="empty"></hxk-state>`}
        </hxk-card>
      </div>
      ${this.city ? nothing : html`<hxk-card heading="Prezzi per città">
        ${s.price_by_city.length ? html`<table><thead><tr><th>Città</th><th class="n">Case</th><th class="n">Prezzo medio</th><th class="n">€/m²</th></tr></thead>
          <tbody>${s.price_by_city.map(c => html`<tr class="click" @click=${() => this.host.navigate('case', { city: c.city })}>
            <td>${c.city}</td><td class="n">${c.count}</td><td class="n">${euro(c.avg_price)}</td><td class="n">${c.avg_ppm2 ? num(c.avg_ppm2) : '—'}</td></tr>`)}</tbody></table>`
          : html`<hxk-state kind="empty" text="Le città arrivano dagli indirizzi degli annunci"></hxk-state>`}
      </hxk-card>`}
    </div>`;
  }
}

/** Widget «Case in numeri». */
export class ScoutKpiWidget extends HestiaElement {
  static properties = { ...HestiaElement.properties, s: { state: true }, error: { state: true } };
  declare s: Stats | null; declare error: string;
  constructor() { super(); this.s = null; this.error = ''; }
  connectedCallback() { super.connectedCallback(); this.load(); this.onHost('refresh', () => this.load()); }
  async load() { const r = await loadStats(this); this.error = r.error ?? ''; if (r.data) this.s = r.data; }
  render() {
    if (this.error && !this.s) return stateOf(this.error, () => this.load());
    if (!this.s) return html`<hxk-state kind="loading"></hxk-state>`;
    const s = this.s; const wide = this.ctx.size === 'xl';
    return html`<hxk-stat .items=${[
      { label: 'Nuove (7 gg)', value: num(s.new), tone: s.new ? 'success' : undefined },
      { label: 'Seguite', value: num(s.total) },
      { label: 'Preferite', value: num(s.favorites) },
      ...(wide ? [{ label: 'Prezzo medio', value: compactEuro(s.avg_price) }, { label: '€/m² medio', value: s.avg_ppm2 ? num(s.avg_ppm2) : '—' }] : []),
    ]}></hxk-stat>`;
  }
}

/** Widget «Prezzi per città»: €/m² medio, barre. */
export class ScoutPricesWidget extends HestiaElement {
  static properties = { ...HestiaElement.properties, s: { state: true }, error: { state: true } };
  declare s: Stats | null; declare error: string;
  constructor() { super(); this.s = null; this.error = ''; }
  connectedCallback() { super.connectedCallback(); this.load(); this.onHost('refresh', () => this.load()); }
  async load() { const r = await loadStats(this); this.error = r.error ?? ''; if (r.data) this.s = r.data; }
  render() {
    if (this.error && !this.s) return stateOf(this.error, () => this.load());
    if (!this.s) return html`<hxk-state kind="loading"></hxk-state>`;
    const rows = this.s.price_by_city.filter(c => c.avg_ppm2).slice(0, this.ctx.size === 'xl' ? 10 : 6);
    if (!rows.length) return html`<hxk-state kind="empty" text="Ancora pochi dati per città"></hxk-state>`;
    return html`<hxk-chart type="bar" unit="€/m²" height=${this.ctx.size === 'xl' ? 230 : 210} .labels=${rows.map(c => c.city)}
      .series=${[{ name: '€/m² medio', values: rows.map(c => c.avg_ppm2 ?? 0) }]}></hxk-chart>`;
  }
}

/** Widgets «Nuove case» (param city, days) and «Case preferite»: compact list, tap = open the listing. */
abstract class ListWidget extends HestiaElement {
  static properties = { ...HestiaElement.properties, items: { state: true }, total: { state: true }, error: { state: true } };
  declare items: Listing[] | null; declare total: number; declare error: string;
  static styles = [...HestiaElement.styles, css`
    :host { display: flex; flex-direction: column; min-height: 0; }
    hxk-list { flex: 1; min-height: 0; overflow: auto; }
    .more { font-size: 12.5px; color: var(--accent); cursor: pointer; padding: 6px 6px 0; background: none; border: 0; text-align: left; font: inherit; }
  `];
  abstract query(): Record<string, string | number>;
  abstract emptyText(): string;
  abstract openQuery(): Record<string, string>;
  constructor() { super(); this.items = null; this.total = 0; this.error = ''; }
  connectedCallback() { super.connectedCallback(); this.load(); this.onHost('refresh', () => this.load()); }
  private get limit() { return ({ s: 3, m: 3, l: 7, xl: 7 } as Record<string, number>)[this.ctx.size ?? 'l'] ?? 6; }
  async load() {
    const r = await this.host.api<{ total: number; items: Listing[] }>('GET', '/api/ui/listings', { query: { ...this.query(), limit: this.limit } });
    if (!r.ok) { this.error = r.error || 'error'; return; }
    this.error = ''; this.items = r.data.items; this.total = r.data.total;
  }
  render() {
    if (this.error && !this.items) return stateOf(this.error, () => this.load());
    if (!this.items) return html`<hxk-state kind="loading"></hxk-state>`;
    if (!this.items.length) return html`<hxk-state kind="empty" text=${this.emptyText()}></hxk-state>`;
    return html`<hxk-list .items=${this.items.map(l => ({ id: l.id, title: euro(l.price) + ' · ' + l.title, subtitle: facts(l), image: l.image || undefined,
        icon: l.image ? undefined : 'home', badge: l.flag === 'favorite' ? { text: 'preferita', tone: 'warning' } : undefined }))}
      @item-click=${(e: CustomEvent) => this.host.navigate('case/' + e.detail.id)}></hxk-list>
      ${this.total > this.items.length ? html`<button class="more" @click=${() => this.host.navigate('case', this.openQuery())}>Altre ${this.total - this.items.length} →</button>` : nothing}`;
  }
}

export class ScoutNewWidget extends ListWidget {
  query() {
    const days = Number(this.ctx.params?.days) || 7;
    return { days, sort: 'new', ...(this.ctx.params?.city ? { city: String(this.ctx.params.city) } : {}) };
  }
  emptyText() { return this.ctx.params?.city ? `Nessuna casa nuova a ${this.ctx.params.city}` : 'Nessuna casa nuova in questi giorni'; }
  openQuery(): Record<string, string> { return { sort: 'new', ...(this.ctx.params?.city ? { city: String(this.ctx.params.city) } : {}) }; }
}

export class ScoutFavoritesWidget extends ListWidget {
  query() { return { flag: 'favorite', sort: 'new' }; }
  emptyText() { return 'Nessuna preferita: tocca la stella su una casa per salvarla qui'; }
  openQuery(): Record<string, string> { return { flag: 'favorite' }; }
}
