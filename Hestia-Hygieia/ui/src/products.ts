/**
 * <hygieia-products>     — the cabinet: what is in use, in stock, wanted, finished; search and filters.
 * <hygieia-product>      — one product: life of the bottle (opened, level, expiry), uses, routines, history, repurchases.
 * <hygieia-product-form> — add / edit sheet (only the name is required; the rest when you want).
 */
import { HestiaElement, LitElement, html, css, nothing } from '@hestia/webui-sdk';
import { API, AREA_EMOJI, STATUS_TONE, call, dayLabel, dropMeta, hygieiaStyles, inDays, label, meta, money, productName, relDays } from './util';

const EMPTY = { name: '', brand: '', line: '', category: '', areas: [] as string[], actives: [] as any[], size: null, unit: 'ml', price: null,
  shop: '', url: '', status: 'in_use', purchased_at: '', opened_at: '', pao_months: null, expires_at: '', level: '', rating: null, verdict: '',
  favorite: false, tags: [] as string[], notes: '', inci: '' };

export class HygieiaProductForm extends LitElement {
  static properties = { host: { attribute: false }, product: { attribute: false }, m: { state: true }, v: { state: true },
    more: { state: true }, activeQ: { state: true }, saving: { state: true } };
  declare host: any;
  declare product: any;
  declare m: any;
  declare v: any;
  declare more: boolean;
  declare activeQ: string;
  declare saving: boolean;
  static styles = [...HestiaElement.styles, hygieiaStyles];
  constructor() { super(); this.product = null; this.m = null; this.v = { ...EMPTY }; this.more = false; this.activeQ = ''; this.saving = false; }
  async connectedCallback() {
    super.connectedCallback();
    this.v = this.product ? { ...EMPTY, ...this.product } : { ...EMPTY };
    this.more = !!this.product?.id;
    this.m = await meta(this.host);
  }
  private set(k: string, val: any) { this.v = { ...this.v, [k]: val }; }
  private close(saved: any = null) { this.dispatchEvent(new CustomEvent('close', { detail: saved, bubbles: true, composed: true })); }
  private async addActive() {
    const name = this.activeQ.trim();
    if (!name) return;
    const known = (this.m?.actives || []).find((a: any) => a.label.toLowerCase() === name.toLowerCase() || a.value === name.toLowerCase());
    if (!known) {
      const r = await call(this.host, 'POST', `${API}/options/actives`, { body: { label: name } });
      if (!r.ok) return;
      dropMeta();
      this.m = await meta(this.host, true);
      this.set('actives', [...this.v.actives, { name: r.data.value }]);
    } else if (!this.v.actives.some((a: any) => a.name === known.value)) {
      this.set('actives', [...this.v.actives, { name: known.value }]);
    }
    this.activeQ = '';
  }
  private async save() {
    if (!this.v.name.trim()) { this.host.toast('Il nome è obbligatorio', 'warning'); return; }
    this.saving = true;
    const body: any = {};
    for (const k of Object.keys(EMPTY)) body[k] = this.v[k] === '' ? null : this.v[k];
    body.name = this.v.name.trim();
    const r = this.product?.id ? await call(this.host, 'PUT', `${API}/products/${this.product.id}`, { body })
      : await call(this.host, 'POST', `${API}/products`, { body });
    this.saving = false;
    if (r.ok) { this.host.toast(this.product?.id ? 'Prodotto aggiornato' : `${r.data.name} aggiunto`, 'success'); this.close(r.data); }
  }
  render() {
    const v = this.v, m = this.m;
    const cats = (m?.categories || []).filter((c: any) => !v.areas.length || !c.area || v.areas.includes(c.area));
    const activeOpts = (m?.actives || []).filter((a: any) => this.activeQ && a.label.toLowerCase().includes(this.activeQ.toLowerCase())
      && !v.actives.some((x: any) => x.name === a.value)).slice(0, 8);
    return html`<div class="sheet" @click=${(e: Event) => { if (e.target === e.currentTarget) this.close(); }}><div class="card col">
      <div class="between"><h2>${this.product?.id ? 'Modifica prodotto' : 'Nuovo prodotto'}</h2><hxk-button variant="ghost" icon="x" @click=${() => this.close()}></hxk-button></div>
      <div class="form">
        <hxk-field label="Nome *" placeholder="es. Retinol 0.2% in Squalane" .value=${v.name} @change=${(e: CustomEvent) => this.set('name', e.detail)}></hxk-field>
        <hxk-field label="Marca" placeholder="es. The Ordinary" .value=${v.brand} @change=${(e: CustomEvent) => this.set('brand', e.detail)}></hxk-field>
      </div>
      <h3>Zone</h3>
      <div class="chips">${(m?.areas || []).map((a: any) => html`<button class="chip" aria-pressed=${v.areas.includes(a.value)}
        @click=${() => this.set('areas', v.areas.includes(a.value) ? v.areas.filter((x: string) => x !== a.value) : [...v.areas, a.value])}>${AREA_EMOJI[a.value] || ''} ${a.label}</button>`)}</div>
      <div class="form">
        <hxk-field label="Tipo" type="enum" .options=${[{ value: '', label: '—' }, ...cats.map((c: any) => ({ value: c.value, label: c.label }))]} .value=${v.category || ''}
          @change=${(e: CustomEvent) => this.set('category', e.detail)}></hxk-field>
        <hxk-field label="Stato" type="enum" .options=${Object.entries(m?.statuses || {}).map(([value, l]) => ({ value, label: l as string }))} .value=${v.status}
          @change=${(e: CustomEvent) => this.set('status', e.detail)}></hxk-field>
      </div>
      <h3>Attivi</h3>
      <div class="chips">${v.actives.map((a: any) => html`<button class="chip" aria-pressed="true" title="Togli"
        @click=${() => this.set('actives', v.actives.filter((x: any) => x.name !== a.name))}>${label(m?.actives, a.name)}${a.percent ? ` ${a.percent}%` : ''} ✕</button>`)}</div>
      <div class="row"><input class="in grow" placeholder="Aggiungi attivo (retinolo, niacinamide…)" .value=${this.activeQ}
        @input=${(e: any) => (this.activeQ = e.target.value)} @keydown=${(e: KeyboardEvent) => e.key === 'Enter' && this.addActive()}>
        <hxk-button size="sm" icon="plus" @click=${() => this.addActive()}>Aggiungi</hxk-button></div>
      ${activeOpts.length ? html`<div class="chips">${activeOpts.map((a: any) => html`<button class="chip"
        @click=${() => { this.set('actives', [...v.actives, { name: a.value }]); this.activeQ = ''; }}>${a.label}</button>`)}</div>` : nothing}
      <div class="row"><hxk-field label="Preferito (in Home)" type="bool" .value=${!!v.favorite} @change=${(e: CustomEvent) => this.set('favorite', e.detail)}></hxk-field></div>
      <button class="link small" @click=${() => (this.more = !this.more)}>${this.more ? 'Meno dettagli' : 'Altri dettagli: prezzo, date, scadenza, voto…'}</button>
      ${this.more ? html`<div class="form">
        <hxk-field label="Linea" .value=${v.line || ''} @change=${(e: CustomEvent) => this.set('line', e.detail)}></hxk-field>
        <hxk-field label="Formato" type="float" .value=${v.size} unit=${v.unit || 'ml'} @change=${(e: CustomEvent) => this.set('size', e.detail)}></hxk-field>
        <hxk-field label="Unità" type="enum" .options=${m?.units || ['ml', 'g']} .value=${v.unit || 'ml'} @change=${(e: CustomEvent) => this.set('unit', e.detail)}></hxk-field>
        <hxk-field label="Prezzo" type="float" unit=${m?.currency || 'EUR'} .value=${v.price} @change=${(e: CustomEvent) => this.set('price', e.detail)}></hxk-field>
        <hxk-field label="Negozio" .value=${v.shop || ''} @change=${(e: CustomEvent) => this.set('shop', e.detail)}></hxk-field>
        <hxk-field label="Link" .value=${v.url || ''} @change=${(e: CustomEvent) => this.set('url', e.detail)}></hxk-field>
        <hxk-field label="Comprato il" type="date" .value=${v.purchased_at || ''} @change=${(e: CustomEvent) => this.set('purchased_at', e.detail)}></hxk-field>
        <hxk-field label="Aperto il" type="date" .value=${v.opened_at || ''} @change=${(e: CustomEvent) => this.set('opened_at', e.detail)}></hxk-field>
        <hxk-field label="Dopo l'apertura (PAO)" type="int" unit="mesi" .value=${v.pao_months} @change=${(e: CustomEvent) => this.set('pao_months', e.detail)}></hxk-field>
        <hxk-field label="Scadenza" type="date" .value=${v.expires_at || ''} @change=${(e: CustomEvent) => this.set('expires_at', e.detail)}></hxk-field>
        <hxk-field label="Livello" type="enum" .options=${[{ value: '', label: '—' }, ...Object.entries(m?.levels || {}).map(([value, l]) => ({ value, label: l as string }))]}
          .value=${v.level || ''} @change=${(e: CustomEvent) => this.set('level', e.detail)}></hxk-field>
        <hxk-field label="Voto (1–5)" type="int" .value=${v.rating} @change=${(e: CustomEvent) => this.set('rating', e.detail)}></hxk-field>
        <hxk-field label="Lo ricompreresti?" type="enum" .options=${[{ value: '', label: '—' }, ...Object.entries(m?.verdicts || {}).map(([value, l]) => ({ value, label: l as string }))]}
          .value=${v.verdict || ''} @change=${(e: CustomEvent) => this.set('verdict', e.detail)}></hxk-field>
        <hxk-field label="Etichette" type="list" .value=${v.tags || []} @change=${(e: CustomEvent) => this.set('tags', e.detail)}></hxk-field>
        <hxk-field class="full" label="Note" type="textarea" .value=${v.notes || ''} @change=${(e: CustomEvent) => this.set('notes', e.detail)}></hxk-field>
        <hxk-field class="full" label="INCI (ingredienti)" type="textarea" .value=${v.inci || ''} @change=${(e: CustomEvent) => this.set('inci', e.detail)}></hxk-field>
      </div>` : nothing}
      <div class="row"><span class="grow"></span><hxk-button variant="ghost" @click=${() => this.close()}>Annulla</hxk-button>
        <hxk-button variant="primary" icon="check" ?loading=${this.saving} @click=${() => this.save()}>Salva</hxk-button></div>
    </div></div>`;
  }
}

const VIEWS: Array<[string, string]> = [['current', 'In uso e scorta'], ['wishlist', 'Desideri'], ['finished,discarded', 'Finiti'], ['', 'Tutti']];
const SORTS: Array<[string, string]> = [['', 'Più usati'], ['expiry', 'Scadenza'], ['last_used', 'Usati di recente'], ['name', 'Nome'], ['price', 'Prezzo']];

export class HygieiaProducts extends HestiaElement {
  static properties = { ...HestiaElement.properties, items: { state: true }, view: { state: true }, area: { state: true }, q: { state: true },
    sort: { state: true }, m: { state: true }, form: { state: true } };
  declare items: any[] | null | undefined;
  declare view: string;
  declare area: string;
  declare q: string;
  declare sort: string;
  declare m: any;
  declare form: boolean;
  private qTimer: any = null;
  static styles = [...HestiaElement.styles, hygieiaStyles, css`
    .star { color: var(--warning); }
    .lvl { width: 38px; height: 6px; border-radius: 3px; background: var(--surface-3); overflow: hidden; flex: none; }
    .lvl > span { display: block; height: 100%; background: var(--accent); }
    .filters { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
  `];
  constructor() { super(); this.items = undefined; this.view = 'current'; this.area = ''; this.q = ''; this.sort = ''; this.m = null; this.form = false; }
  connectedCallback() {
    super.connectedCallback();
    if (this.ctx?.query?.nuovo) this.form = true;
    if (this.ctx?.query?.zona) this.area = this.ctx.query.zona;
    this.load();
    this.onHost('refresh', () => this.load());
  }
  private async load() {
    const [r, m] = await Promise.all([this.host.api('GET', `${API}/products`, { query: { status: this.view, area: this.area, q: this.q, sort: this.sort } }), meta(this.host)]);
    this.items = r.ok ? r.data.items : null;
    this.m = m;
  }
  private setQ(v: string) { this.q = v; clearTimeout(this.qTimer); this.qTimer = setTimeout(() => this.load(), 250); }
  private row(p: any) {
    const level = ({ full: 1, '3/4': .75, half: .5, '1/4': .25, almost_empty: .08 } as Record<string, number>)[p.level];
    const exp = p.expires_in;
    return html`<div class="li" @click=${() => this.host.navigate('prodotti/' + p.id)}>
      <div class="grow">
        <div class="truncate">${p.favorite ? html`<span class="star">★ </span>` : nothing}<b>${p.name}</b>${p.brand ? html`<span class="muted"> · ${p.brand}</span>` : nothing}</div>
        <div class="small muted truncate">${[label(this.m?.categories, p.category), p.uses ? `${p.uses} usi` : '', p.last_used ? `ultimo ${relDays(p.last_used)}` : '',
          (p.routines || []).map((r: any) => r.name).join(', ')].filter(Boolean).join(' · ')}</div>
      </div>
      ${exp !== null && exp !== undefined && exp <= 60 && ['in_use', 'stock'].includes(p.status) ? html`<span class="pill ${exp < 0 ? 'bad' : 'warn'}">⏳ ${inDays(exp)}</span>` : nothing}
      ${level !== undefined && p.status === 'in_use' ? html`<span class="lvl" title=${this.m?.levels?.[p.level] || ''}><span style="width:${level * 100}%"></span></span>` : nothing}
      <hxk-badge tone=${STATUS_TONE[p.status] || 'neutral'}>${p.status_label}</hxk-badge>
    </div>`;
  }
  render() {
    const head = html`<div class="between wrap"><div class="head"><button class="link" @click=${() => this.host.navigate('oggi')}>‹ Oggi</button><h1>Prodotti</h1>
      ${this.items ? html`<span class="sub">${this.items.length}</span>` : nothing}</div>
      <div class="row"><hxk-button icon="calendar" variant="ghost" @click=${() => this.host.navigate('spesa')}>Spesa</hxk-button>
        <hxk-button variant="primary" icon="plus" @click=${() => (this.form = true)}>Nuovo</hxk-button></div></div>`;
    return html`<div class="page">${head}
      <div class="filters">
        <input class="in grow" style="min-width:180px" placeholder="Cerca per nome, marca, tipo…" .value=${this.q} @input=${(e: any) => this.setQ(e.target.value)}>
        <select class="in" @change=${(e: any) => { this.sort = e.target.value; this.load(); }}>${SORTS.map(([v, l]) => html`<option value=${v} ?selected=${v === this.sort}>${l}</option>`)}</select>
      </div>
      <div class="tabs">${VIEWS.map(([v, l]) => html`<button class="tab" aria-pressed=${this.view === v} @click=${() => { this.view = v; this.load(); }}>${l}</button>`)}</div>
      <div class="chips">${(this.m?.areas || []).map((a: any) => html`<button class="chip" aria-pressed=${this.area === a.value}
        @click=${() => { this.area = this.area === a.value ? '' : a.value; this.load(); }}>${AREA_EMOJI[a.value] || ''} ${a.label}</button>`)}</div>
      ${this.items === undefined ? html`<hxk-state kind="loading"></hxk-state>`
        : this.items === null ? html`<hxk-state kind="offline" @retry=${() => this.load()}></hxk-state>`
        : this.items.length ? html`<div class="card list">${this.items.map(p => this.row(p))}</div>`
        : html`<div class="card col" style="align-items:flex-start"><div class="muted">${this.q || this.area ? 'Nessun prodotto con questi filtri.' : 'Ancora nessun prodotto qui.'}</div>
            <hxk-button icon="plus" @click=${() => (this.form = true)}>Aggiungi un prodotto</hxk-button></div>`}
      ${this.form ? html`<hygieia-product-form .host=${this.host} @close=${(e: CustomEvent) => { this.form = false; if (e.detail) this.host.navigate('prodotti/' + e.detail.id); }}></hygieia-product-form>` : nothing}
    </div>`;
  }
}

const EVENT_ICON: Record<string, string> = { bought: '🛍️', opened: '🔓', level_changed: '📉', finished: '✅', discarded: '🗑️', rated: '⭐', replaced: '🔁', note: '📝', status: '•' };

export class HygieiaProduct extends HestiaElement {
  static properties = { ...HestiaElement.properties, p: { state: true }, m: { state: true }, form: { state: true } };
  declare p: any;
  declare m: any;
  declare form: boolean;
  static styles = [...HestiaElement.styles, hygieiaStyles, css`
    .sec { display: flex; flex-direction: column; gap: 10px; }
    .ev { display: flex; gap: 10px; padding: 6px 0; font-size: 13px; }
    .lvls { display: flex; gap: 4px; flex-wrap: wrap; }
  `];
  constructor() { super(); this.p = undefined; this.m = null; this.form = false; }
  private get rid() { return this.ctx?.params?.id || ''; }
  connectedCallback() { super.connectedCallback(); this.load(); this.onHost('refresh', () => this.load()); }
  private async load() {
    const [r, m] = await Promise.all([this.host.api('GET', `${API}/products/${this.rid}`), meta(this.host)]);
    this.p = r.ok ? r.data : r.status === 404 ? 'missing' : null;
    this.m = m;
  }
  private async act(path: string, body: any = {}, msg = '') {
    const r = await call(this.host, 'POST', `${API}/products/${this.rid}/${path}`, { body });
    if (r.ok) { if (msg || r.data.label) this.host.toast(msg || r.data.label, 'success'); if (path === 'repurchase') this.host.navigate('prodotti/' + r.data.id); else this.load(); }
  }
  private async use() {
    const r = await call(this.host, 'POST', `${API}/products/${this.rid}/use`, { body: {} });
    if (r.ok) this.host.toast('Uso segnato', 'success', { label: 'Annulla', run: async () => { await call(this.host, 'DELETE', `${API}/products/${this.rid}/use`); this.load(); } });
    this.load();
  }
  private async drop() {
    if (!await this.host.confirm('Elimina prodotto', 'Lo togli dall\'elenco. Se l\'hai finito o buttato, meglio segnarlo così: resta nello storico.', { label: 'Elimina', danger: true })) return;
    const r = await call(this.host, 'DELETE', `${API}/products/${this.rid}`);
    if (r.ok) this.host.navigate('prodotti');
  }
  render() {
    const back = html`<button class="link" @click=${() => this.host.navigate('prodotti')}>‹ Prodotti</button>`;
    if (this.p === undefined) return html`<div class="page">${back}<hxk-state kind="loading"></hxk-state></div>`;
    if (this.p === 'missing') return html`<div class="page">${back}<hxk-state kind="empty" text="Prodotto non trovato"></hxk-state></div>`;
    if (this.p === null) return html`<div class="page">${back}<hxk-state kind="offline" @retry=${() => this.load()}></hxk-state></div>`;
    const p = this.p, m = this.m;
    const fe = p.finish_estimate;
    const current = ['in_use', 'stock', 'paused'].includes(p.status);
    return html`<div class="page">
      ${back}
      <div class="between wrap">
        <div class="col" style="gap:2px"><h1>${p.favorite ? html`<span style="color:var(--warning)">★ </span>` : nothing}${p.name}</h1>
          <div class="muted">${[p.brand, p.line, label(m?.categories, p.category), (p.areas || []).map((a: string) => label(m?.areas, a)).join(', ')].filter(Boolean).join(' · ')}</div></div>
        <div class="row"><hxk-badge tone=${STATUS_TONE[p.status] || 'neutral'}>${p.status_label}</hxk-badge>
          <hxk-button size="sm" icon="edit" @click=${() => (this.form = true)}>Modifica</hxk-button></div>
      </div>
      <div class="row wrap">
        ${current ? html`<hxk-button variant="primary" icon="check" @click=${() => this.use()}>Usato oggi</hxk-button>` : nothing}
        ${p.status === 'stock' || p.status === 'paused' || p.status === 'wishlist' ? html`<hxk-button icon="play" @click=${() => this.act('status', { status: 'in_use' })}>${p.status === 'wishlist' ? 'Comprato, in uso' : 'Inizia a usarlo'}</hxk-button>` : nothing}
        ${p.status === 'wishlist' ? html`<hxk-button @click=${() => this.act('status', { status: 'stock' })}>Comprato, in scorta</hxk-button>` : nothing}
        ${p.status === 'in_use' ? html`<hxk-button icon="pause" @click=${() => this.act('status', { status: 'paused' })}>Pausa</hxk-button>
          <hxk-button icon="check" @click=${() => this.act('status', { status: 'finished' })}>Finito</hxk-button>` : nothing}
        ${current ? html`<hxk-button variant="ghost" icon="trash" @click=${() => this.act('status', { status: 'discarded' })}>Buttato</hxk-button>` : nothing}
        <hxk-button icon="refresh" @click=${() => this.act('repurchase')}>Ricomprato</hxk-button>
        <hxk-button variant="ghost" icon="star" @click=${() => call(this.host, 'PUT', `${API}/products/${this.rid}`, { body: { favorite: !p.favorite } }).then(() => this.load())}>${p.favorite ? 'Togli dai preferiti' : 'Preferito'}</hxk-button>
      </div>
      <hxk-stat .items=${[{ label: 'Usi', value: p.uses || 0, hint: p.last_used ? `ultimo ${relDays(p.last_used)}` : '' },
        { label: 'Aperto da', value: p.days_open ?? '–', unit: p.days_open !== null && p.days_open !== undefined ? 'giorni' : '' },
        { label: 'Scadenza', value: p.expiry ? dayLabel(p.expiry, false) : '–', hint: inDays(p.expires_in), tone: p.expires_in !== null && p.expires_in < 0 ? 'danger' : p.expires_in !== null && p.expires_in <= 30 ? 'warning' : '' },
        ...(fe ? [{ label: 'Finisce tra', value: `~${fe.days_left}`, unit: 'giorni', hint: fe.basis }] : []),
        ...(p.price ? [{ label: 'Prezzo', value: money(p.price, p.currency), hint: p.price_per_use ? `${money(p.price_per_use, p.currency)} a uso` : '' }] : [])]}></hxk-stat>
      ${p.status === 'in_use' ? html`<div class="card sec"><h2>Quanto ne resta</h2>
        <div class="lvls">${Object.entries(m?.levels || {}).map(([k, l]) => html`<button class="chip" aria-pressed=${p.level === k} @click=${() => this.act('level', { level: k }, 'Livello aggiornato')}>${l}</button>`)}</div></div>` : nothing}
      ${(p.actives || []).length ? html`<div class="card sec"><h2>Attivi</h2><div class="chips">${p.actives.map((a: any) => html`<span class="pill">${label(m?.actives, a.name)}${a.percent ? ` ${a.percent}%` : ''}</span>`)}</div></div>` : nothing}
      <div class="card sec"><h2>Nelle routine</h2>
        ${(p.routines || []).length ? html`<div class="list">${p.routines.map((r: any) => html`<div class="li" @click=${() => this.host.navigate('routine/' + r.id)}><span class="grow">${r.name}</span><hxk-icon name="chevron-right"></hxk-icon></div>`)}</div>`
          : html`<div class="empty">In nessuna routine: lo segni con «Usato oggi» o aggiungilo a una routine.</div>`}</div>
      ${(p.usage_weeks || []).length > 1 ? html`<div class="card sec"><h2>Uso per settimana</h2>
        <hxk-chart type="bar" height="120" .labels=${p.usage_weeks.map((w: any) => dayLabel(w.week, false))} .series=${[{ name: 'Usi', values: p.usage_weeks.map((w: any) => w.uses) }]}></hxk-chart></div>` : nothing}
      ${p.rating || p.verdict || p.notes ? html`<div class="card sec"><h2>Giudizio</h2>
        ${p.rating ? html`<div>${'★'.repeat(Math.round(p.rating))}${'☆'.repeat(5 - Math.round(p.rating))}</div>` : nothing}
        ${p.verdict ? html`<div>${m?.verdicts?.[p.verdict] || p.verdict}</div>` : nothing}
        ${p.notes ? html`<div class="small" style="white-space:pre-wrap">${p.notes}</div>` : nothing}</div>` : nothing}
      ${(p.siblings || []).length ? html`<div class="card sec"><h2>Altre confezioni</h2><div class="list">${p.siblings.map((s: any) => html`
        <div class="li" @click=${() => this.host.navigate('prodotti/' + s.id)}><div class="grow"><div>${s.status_label}${s.purchased_at ? ` · comprato ${dayLabel(s.purchased_at, false)}` : ''}</div>
          <div class="small muted">${s.days_open !== null && s.days_open !== undefined ? `durato ${s.days_open} giorni` : ''}${s.price ? ` · ${money(s.price, s.currency)}` : ''}</div></div></div>`)}</div></div>` : nothing}
      <div class="card sec"><h2>Storia</h2>
        ${(p.events || []).map((e: any) => html`<div class="ev"><span>${EVENT_ICON[e.type] || '•'}</span><span class="muted tnum" style="min-width:70px">${dayLabel(e.date, false)}</span><span>${e.text}</span></div>`)}
        ${p.url ? html`<a class="link small" href=${p.url} target="_blank" rel="noopener">Pagina del prodotto ›</a>` : nothing}
        ${p.inci ? html`<details><summary class="small muted">INCI</summary><div class="small" style="white-space:pre-wrap">${p.inci}</div></details>` : nothing}
      </div>
      <div><hxk-button variant="ghost" icon="trash" @click=${() => this.drop()}>Elimina</hxk-button></div>
      ${this.form ? html`<hygieia-product-form .host=${this.host} .product=${p} @close=${(e: CustomEvent) => { this.form = false; if (e.detail) this.load(); }}></hygieia-product-form>` : nothing}
    </div>`;
  }
}
