import { HestiaElement, css, html, nothing, tr } from '@hestia/webui-sdk';
import { setFlag } from './listings';
import { ListingDetail, ago, euro, num, statusTone } from './shared';

const STATUSES: [string, string][] = [
  ['available', tr('Available')], ['in_negotiation', tr('Under negotiation')], ['investment_occupied', tr('Taken (investment)')],
  ['sold', tr('Sold')], ['unknown', tr('To check')],
];

/** Page «Annuncio» (case/:id): photos, facts, features, summary, the user's mark and status. */
export class ScoutListing extends HestiaElement {
  static properties = { ...HestiaElement.properties, l: { state: true }, error: { state: true }, shot: { state: true } };
  declare l: ListingDetail | null; declare error: string; declare shot: number;

  static styles = [...HestiaElement.styles, css`
    .back { display: inline-flex; align-items: center; gap: 4px; color: var(--text-2); cursor: pointer; font-size: 13px; background: none; border: 0; padding: 0; font: inherit; }
    .back:hover { color: var(--accent); }
    .top { display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(280px, 1fr); gap: 20px; align-items: start; }
    .gal { display: flex; flex-direction: column; gap: 8px; }
    .main { width: 100%; aspect-ratio: 4 / 3; object-fit: cover; border-radius: var(--radius-lg); background: var(--surface-2); display: block; }
    .thumbs { display: flex; gap: 6px; overflow-x: auto; scroll-snap-type: x mandatory; padding-bottom: 2px; }
    .thumbs img { width: 72px; height: 54px; object-fit: cover; border-radius: var(--radius-sm); cursor: pointer; opacity: .7;
                  scroll-snap-align: start; flex: 0 0 auto; border: 2px solid transparent; }
    .thumbs img.on { opacity: 1; border-color: var(--accent); }
    .noimg { aspect-ratio: 4 / 3; border-radius: var(--radius-lg); background: var(--surface-2); display: grid; place-items: center; color: var(--text-3); }
    .side { display: flex; flex-direction: column; gap: 12px; }
    .price { font-family: var(--font-serif); font-size: 30px; font-weight: 600; line-height: 1.1; }
    .ppm { color: var(--text-3); font-size: 13px; }
    .addr { color: var(--text-2); display: flex; gap: 6px; align-items: center; }
    .acts { display: flex; gap: 8px; flex-wrap: wrap; }
    .facts { display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 8px; }
    .fact { background: var(--surface-2); border-radius: var(--radius-md); padding: 8px 10px; }
    .fact .k { font-size: 11.5px; color: var(--text-3); } .fact .v { font-weight: 500; }
    .chips { display: flex; flex-wrap: wrap; gap: 6px; }
    .chip { background: var(--surface-2); border-radius: 999px; padding: 3px 10px; font-size: 12.5px; color: var(--text-2); }
    .summary { white-space: pre-line; color: var(--text-2); }
    table { border-collapse: collapse; width: 100%; font-size: 13px; }
    td { padding: 5px 0; border-bottom: 1px solid var(--border); vertical-align: top; } td:first-child { color: var(--text-3); width: 40%; padding-right: 12px; }
    @media (max-width: 860px) { .top { grid-template-columns: minmax(0, 1fr); } .price { font-size: 26px; } }
  `];

  constructor() { super(); this.l = null; this.error = ''; this.shot = 0; }

  connectedCallback() {
    super.connectedCallback();
    this.load();
    this.onHost('refresh', () => this.load());
  }

  async load() {
    const id = this.ctx.params?.id || this.ctx.query?.id || '';
    const r = await this.host.api<ListingDetail>('GET', `/api/ui/listings/${encodeURIComponent(id)}`);
    if (!r.ok) { this.error = r.status === 404 ? 'missing' : (r.error || 'error'); return; }
    this.error = ''; this.l = r.data; this.shot = 0;
  }

  private async setStatus(status: string) {
    const l = this.l!; const before = l.status;
    const r = await this.host.api<ListingDetail>('PATCH', `/api/ui/listings/${l.id}`, { body: { status } });
    if (!r.ok) { this.host.toast(tr('I couldn\'t save the state'), 'danger'); return; }
    this.l = { ...l, ...r.data };
    this.host.toast(tr('State updated'), 'success', { label: tr('Cancel'), run: () => this.setStatus(before) });
  }

  private ask() {
    const l = this.l!;
    this.host.assistant({
      label: l.title, hints: { listing: l.url, price: l.price ?? '', city: l.city, m2: l.surface_m2 ?? '' },
      suggestions: [tr('Is it worth the price compared with others in the area?'), tr('Write a message to the agency for a visit'), tr('What\'s missing in the listing?')],
    });
  }

  render() {
    if (this.error === 'missing') return html`<div class="page"><hxk-state kind="empty" text=${tr("Listing not found (maybe removed)")}></hxk-state>
      <hxk-button variant="ghost" icon="chevron-left" @click=${() => this.host.navigate('case')}>${tr("All houses")}</hxk-button></div>`;
    if (this.error) return html`<div class="page"><hxk-state kind=${this.error === 'offline' ? 'offline' : 'error'} @retry=${() => this.load()}></hxk-state></div>`;
    if (!this.l) return html`<div class="page"><hxk-state kind="loading"></hxk-state></div>`;
    const l = this.l;
    const imgs = l.images.length ? l.images : (l.image ? [l.image] : []);
    const facts: [string, string][] = ([
      [tr('alt::Area'), l.surface_m2 ? `${num(l.surface_m2)} m²` : ''], [tr('pl::Local'), l.rooms ? String(l.rooms) : ''],
      [tr('Bedrooms'), l.bedrooms ? String(l.bedrooms) : ''], [tr('Bathrooms'), l.bathrooms ? String(l.bathrooms) : ''],
      [tr('Plan'), l.floor || ''], [tr('Year'), l.year_built ? String(l.year_built) : ''],
      [tr('Condominium fees'), l.condo_fees ? (typeof l.condo_fees === 'number' ? tr('{0}/month', euro(l.condo_fees)) : String(l.condo_fees)) : ''],
      [tr('Warm-up'), l.heating || ''], [tr('Property state'), l.property_state || ''],
    ] as [string, string][]).filter(([, v]) => v);
    const extras = [l.elevator && tr('Lift'), l.balcony && tr('Balcony or terrace'), l.parking && tr('Garage or parking space'), ...l.features].filter(Boolean) as string[];
    const map = l.lat && l.lon ? `https://www.openstreetmap.org/?mlat=${l.lat}&mlon=${l.lon}#map=16/${l.lat}/${l.lon}`
      : l.address ? `https://www.openstreetmap.org/search?query=${encodeURIComponent(l.address)}` : '';
    return html`<div class="page">
      <button class="back" @click=${() => this.host.navigate('case')}><hxk-icon name="chevron-left"></hxk-icon>${tr("All houses")}</button>
      <div class="top">
        <div class="gal">
          ${imgs.length ? html`<img class="main" src=${imgs[this.shot] ?? imgs[0]} alt="" referrerpolicy="no-referrer">
            ${imgs.length > 1 ? html`<div class="thumbs">${imgs.map((src, i) => html`<img src=${src} alt=${tr("Photo {0}", i + 1)} loading="lazy"
                referrerpolicy="no-referrer" class=${i === this.shot ? 'on' : ''} @click=${() => this.shot = i}>`)}</div>` : nothing}`
            : html`<div class="noimg"><hxk-icon name="home" size="40"></hxk-icon></div>`}
        </div>
        <div class="side">
          <div>
            <div class="price">${euro(l.price)}</div>
            ${l.price_per_m2 ? html`<div class="ppm">${num(l.price_per_m2)} €/m²</div>` : nothing}
          </div>
          <h2>${l.title}</h2>
          ${l.address ? html`<div class="addr"><hxk-icon name="map-pin"></hxk-icon><span class="grow">${l.address}</span>
            ${map ? html`<a href=${map} target="_blank" rel="noopener">${tr("Map")}</a>` : nothing}</div>` : nothing}
          <div class="row wrap">
            <hxk-badge tone=${statusTone(l.status)}>${l.status_label}</hxk-badge>
            <span class="muted small">${tr("Arrived")} ${ago(l.created_at)}${l.source ? ` · ${l.source}` : ''}${l.agency ? ` · ${l.agency}` : ''}</span>
          </div>
          <div class="acts">
            <hxk-button variant=${l.flag === 'favorite' ? 'primary' : 'default'} icon="star"
                        @click=${() => setFlag(this, l, 'favorite', x => this.l = { ...l, ...x })}>${l.flag === 'favorite' ? tr('f::Favourite') : tr('Add to favourites')}</hxk-button>
            <hxk-button variant="ghost" icon="eye-off" @click=${() => setFlag(this, l, 'discarded', x => this.l = { ...l, ...x })}>${l.flag === 'discarded' ? tr('Discarded') : tr('Discard')}</hxk-button>
          </div>
          <div class="acts">
            <a href=${l.url} target="_blank" rel="noopener"><hxk-button icon="external">${tr("Open listing")}</hxk-button></a>
            <hxk-button variant="ghost" icon="sparkle" @click=${() => this.ask()}>${tr("Ask {assistant}")}</hxk-button>
          </div>
          <label class="col small muted">${tr("Listing state (fix it if it's not right)")}
            <select @change=${(e: Event) => this.setStatus((e.target as HTMLSelectElement).value)}>
              ${STATUSES.map(([v, t]) => html`<option value=${v} ?selected=${v === l.status}>${t}</option>`)}
            </select>
          </label>
        </div>
      </div>
      ${facts.length ? html`<div class="facts">${facts.map(([k, v]) => html`<div class="fact"><div class="k">${k}</div><div class="v">${v}</div></div>`)}</div>` : nothing}
      ${extras.length ? html`<div class="chips">${extras.map(x => html`<span class="chip">${x}</span>`)}</div>` : nothing}
      ${l.summary ? html`<div class="card"><h3>${tr("Description")}</h3><p class="summary">${l.summary}</p></div>` : nothing}
      ${Object.keys(l.characteristics).length ? html`<div class="card"><h3>${tr("Features")}</h3><table>
        ${Object.entries(l.characteristics).map(([k, v]) => html`<tr><td>${k}</td><td>${v}</td></tr>`)}</table></div>` : nothing}
    </div>`;
  }
}
