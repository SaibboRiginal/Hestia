/**
 * <wardrobe-outfits>        — saved outfits as tiles: search, filters, «✓ oggi» in one tap, new outfit builder.
 * <wardrobe-outfit>         — one outfit: pieces by slot, «Indossato» (today or another day), rating, tags, photos, history.
 * <wardrobe-outfit-builder> — pick pieces (tap = added in its usual slot), change slot, name it, save.
 */
import { HestiaElement, css, html, nothing } from '@hestia/webui-sdk';
import { API, Meta, SEASON_ICON, WardrobeElement, call, dayLabel, dots, img, localDay, norm, photo, relDays, vocabOptions, wardrobeStyles } from './util';

/** 2×2 collage of the pieces when the outfit has no photo of its own. */
function collage(host: any, o: any) {
  if (o.photos?.length) return img(host, o.photos[0], o.name);
  const ps = (o.pieces || []).filter((p: any) => p.photo).slice(0, 4);
  if (!ps.length) return html`<hxk-icon name="shirt" size="28"></hxk-icon>`;
  if (ps.length === 1) return img(host, ps[0].photo, o.name);
  return html`<div style="display:grid;grid-template-columns:1fr 1fr;width:100%;height:100%;gap:1px">${ps.map((p: any) =>
    html`<img loading="lazy" style="width:100%;height:100%;object-fit:cover;aspect-ratio:1" src=${photo(host, p.photo)} alt="">`)}</div>`;
}

export class WardrobeOutfitBuilder extends HestiaElement {
  static properties = { ...HestiaElement.properties, meta: { attribute: false }, value: { attribute: false }, name: {},
                        pieces: { state: true }, slots: { state: true }, q: { state: true }, slotTab: { state: true }, nm: { state: true } };
  declare meta: Meta | null; declare value: any[]; declare name: string;
  declare pieces: any[] | undefined; declare slots: Array<{ slot: string; piece_id: string }>; declare q: string; declare slotTab: string; declare nm: string;
  static styles = [...HestiaElement.styles, wardrobeStyles, css`
    :host { display: block; }
    .sel { display: flex; flex-direction: column; gap: 6px; }
    .srow { display: flex; align-items: center; gap: 8px; }
    .srow select.in { padding: 4px 6px; font-size: 12.5px; }
    .tiles { --tile: 110px; max-height: 420px; overflow: auto; padding: 2px; }
  `];
  constructor() { super(); this.value = []; this.name = ''; this.pieces = undefined; this.slots = []; this.q = ''; this.slotTab = ''; this.nm = ''; }
  connectedCallback() {
    super.connectedCallback();
    this.slots = [...(this.value || [])];
    this.nm = this.name || '';
    this.host.api('GET', `${API}/pieces`, { query: { status: 'active,laundry,lent,stored', limit: 1000, sort: 'name' } })
      .then(r => { this.pieces = r.ok ? r.data.items : []; });
  }
  private add(p: any) {
    if (this.slots.some(s => s.piece_id === p.id)) { this.slots = this.slots.filter(s => s.piece_id !== p.id); return; }
    const slot = p.kind === 'accessory' ? 'accessory' : p.kind === 'shoes' ? 'shoes' : p.slot || 'top';
    this.slots = [...this.slots, { slot, piece_id: p.id }];
  }
  private save() {
    if (!this.slots.length) { this.host.toast('Scegli almeno un capo', 'warning'); return; }
    this.dispatchEvent(new CustomEvent('save', { detail: { slots: this.slots, name: this.nm.trim() }, bubbles: true, composed: true }));
  }
  render() {
    const m = this.meta;
    const byId = new Map((this.pieces || []).map(p => [p.id, p]));
    const order = Object.keys(m?.slots || {});
    const sel = [...this.slots].sort((a, b) => order.indexOf(a.slot) - order.indexOf(b.slot));
    let list = this.pieces || [];
    if (this.slotTab) list = list.filter(p => (p.kind === 'accessory' ? 'accessory' : p.kind === 'shoes' ? 'shoes' : p.slot) === this.slotTab);
    if (this.q) { const w = norm(this.q).split(/\s+/).filter(Boolean); list = list.filter(p => w.every(x => norm(`${p.name} ${p.category_label} ${p.subcategory_label} ${(p.colors || []).map((c: any) => c.name).join(' ')}`).includes(x))); }
    return html`<div class="col" style="gap:12px">
      <input class="in" placeholder="Nome (vuoto = dai capi)" .value=${this.nm} @input=${(e: any) => (this.nm = e.target.value)}>
      <div class="sel">${sel.length ? sel.map(s => { const p = byId.get(s.piece_id); return html`<div class="srow">
          <span class="thumb">${img(this.host, p?.photos?.[0], p?.name || '')}</span>
          <span class="grow truncate">${p?.name || '…'}</span>
          <select class="in" @change=${(e: any) => (this.slots = this.slots.map(x => x.piece_id === s.piece_id ? { ...x, slot: e.target.value } : x))}>
            ${Object.entries(m?.slots || {}).map(([k, v]) => html`<option value=${k} ?selected=${s.slot === k}>${v}</option>`)}</select>
          <hxk-button size="sm" variant="ghost" icon="x" @click=${() => (this.slots = this.slots.filter(x => x.piece_id !== s.piece_id))}></hxk-button></div>`; })
        : html`<div class="empty">Tocca i capi qui sotto: finiscono nella posizione giusta (sopra, sotto, scarpe…).</div>`}</div>
      <div class="row wrap" style="gap:6px">
        <button class="chip soft" aria-pressed=${!this.slotTab} @click=${() => (this.slotTab = '')}>Tutti</button>
        ${Object.entries(m?.slots || {}).map(([k, v]) => html`<button class="chip soft" aria-pressed=${this.slotTab === k} @click=${() => (this.slotTab = this.slotTab === k ? '' : k)}>${v}</button>`)}
        <input class="in grow" style="min-width:140px" placeholder="Cerca…" .value=${this.q} @input=${(e: any) => (this.q = e.target.value)}></div>
      ${this.pieces === undefined ? html`<hxk-state kind="loading"></hxk-state>` : html`<div class="tiles">${list.map(p => html`
        <div class="tile" data-sel=${this.slots.some(s => s.piece_id === p.id)} @click=${() => this.add(p)}>
          <div class="ph">${img(this.host, p.photos?.[0], p.name)}</div>
          ${this.slots.some(s => s.piece_id === p.id) ? html`<span class="check"><hxk-icon name="check" size="14"></hxk-icon></span>` : nothing}
          ${p.status !== 'active' ? html`<hxk-badge class="badge" tone="info">${p.status_label}</hxk-badge>` : nothing}
          <div class="tx"><span class="nm">${p.name}</span></div></div>`)}
        ${list.length ? nothing : html`<div class="empty">Nessun capo qui.</div>`}</div>`}
      <div class="row"><hxk-button variant="primary" icon="check" @click=${() => this.save()}>Salva outfit</hxk-button>
        <hxk-button variant="ghost" @click=${() => this.dispatchEvent(new CustomEvent('cancel', { bubbles: true, composed: true }))}>Annulla</hxk-button></div>
    </div>`;
  }
}

async function markWorn(host: any, o: any, day = '', after?: () => void) {
  const r = await call(host, 'POST', `/outfits/${o.id}/worn`, day ? { date: day } : {});
  if (!r.ok) return;
  const w = r.data;
  if (w.already) { host.toast(`«${o.name}» è già segnato ${day ? 'quel giorno' : 'oggi'}`, 'info'); return; }
  host.toast(w.label || 'Segnato', 'success', { label: 'Annulla', run: async () => { await call(host, 'DELETE', `/wears/${w.id}`); after?.(); } });
  after?.();
}

export class WardrobeOutfits extends WardrobeElement {
  static properties = { ...WardrobeElement.properties, items: { state: true }, q: { state: true }, f: { state: true }, building: { state: true }, seed: { state: true } };
  declare items: any[] | undefined; declare q: string; declare f: Record<string, string>; declare building: boolean; declare seed: any[];
  private _t: any = null;
  static styles = [...WardrobeElement.styles, wardrobeStyles, css`
    .today { position: absolute; bottom: 52px; right: 6px; }
    .tile .ph { aspect-ratio: 4 / 5; }
  `];
  constructor() { super(); this.items = undefined; this.q = ''; this.f = { sort: 'favorites' }; this.building = false; this.seed = []; }
  connectedCallback() {
    const con = this.ctx?.query?.con;
    if (con) { this.building = true; this.seed = [{ slot: 'top', piece_id: con }]; }
    super.connectedCallback();
  }
  protected async load() {
    const query: Record<string, any> = { q: this.q, ...this.f, limit: 400 };
    if (!query.favorite) delete query.favorite;
    if (this.seed.length && this.seed[0].slot === 'top') {               // fix the seeded piece's slot from its category
      const r = await this.host.api('GET', `${API}/pieces/${this.seed[0].piece_id}`);
      if (r.ok) this.seed = [{ slot: r.data.kind === 'shoes' ? 'shoes' : r.data.kind === 'accessory' ? 'accessory' : r.data.slot, piece_id: r.data.id }];
    }
    const r = await this.host.api('GET', `${API}/outfits`, { query });
    if (r.ok) this.items = r.data.items; else if (this.items === undefined) this.items = [];
  }
  private filter(k: string, v: string) { this.f = { ...this.f, [k]: this.f[k] === v ? '' : v }; this.load(); }
  private async create(e: CustomEvent) {
    const r = await call(this.host, 'POST', '/outfits', e.detail);
    if (r.ok) { this.building = false; this.seed = []; this.host.navigate('outfit/' + r.data.id); }
  }
  render() {
    const m = this.m, items = this.items, today = localDay();
    return html`<div class="page">
      <div class="head"><h1>Outfit</h1><span class="sub">${items?.length ?? ''}</span><span class="grow"></span>
        <hxk-button variant="ghost" icon="sparkle" @click=${() => this.host.navigate('cosa-mi-metto')}>Cosa mi metto</hxk-button>
        <hxk-button variant="primary" icon="plus" @click=${() => { this.building = !this.building; this.seed = []; }}>Nuovo outfit</hxk-button></div>
      ${this.building ? html`<div class="card"><wardrobe-outfit-builder .host=${this.host} .ctx=${this.ctx} .meta=${m} .value=${this.seed}
          @save=${this.create} @cancel=${() => { this.building = false; this.seed = []; }}></wardrobe-outfit-builder></div>` : nothing}
      <input class="in" placeholder="Cerca per nome o capo…" .value=${this.q} @input=${(e: any) => { this.q = e.target.value; clearTimeout(this._t); this._t = setTimeout(() => this.load(), 220); }}>
      <div class="chips">
        <button class="chip soft" aria-pressed=${this.f.favorite === 'true'} @click=${() => this.filter('favorite', 'true')}>★ Preferiti</button>
        ${m ? Object.entries(m.seasons).map(([k, v]) => html`<button class="chip soft" title=${v} aria-pressed=${this.f.season === k} @click=${() => this.filter('season', k)}>${SEASON_ICON[k]}</button>`) : nothing}
        <select class="in" @change=${(e: any) => { this.f = { ...this.f, occasion: e.target.value }; this.load(); }}>
          <option value="">Ogni occasione</option>${vocabOptions(m, 'occasion').map(o => html`<option value=${o.key} ?selected=${this.f.occasion === o.key}>${o.label}</option>`)}</select>
        <select class="in" @change=${(e: any) => { this.f = { ...this.f, sort: e.target.value }; this.load(); }}>
          ${Object.entries({ favorites: 'Preferiti prima', recent: 'Creati di recente', least_recent: 'Messi meno di recente', worn: 'Più messi', rating: 'Voto', name: 'Nome' })
            .map(([k, v]) => html`<option value=${k} ?selected=${this.f.sort === k}>${v}</option>`)}</select>
      </div>
      ${items === undefined ? html`<hxk-state kind="loading"></hxk-state>` : !items.length ? html`<hxk-state kind="empty"
          text="Nessun outfit. Creane uno da «Nuovo outfit», da «Cosa mi metto» o selezionando dei capi nel Guardaroba."></hxk-state>` : html`
        <div class="tiles">${items.map(o => html`<div class="tile" @click=${() => this.host.navigate('outfit/' + o.id)}>
          <div class="ph">${collage(this.host, o)}</div>
          ${o.favorite ? html`<span class="fav">★</span>` : nothing}
          ${!o.complete ? html`<hxk-badge class="badge" tone="warning">da rivedere</hxk-badge>` : !o.available ? html`<hxk-badge class="badge" tone="info">non disponibile</hxk-badge>` : nothing}
          <hxk-button class="today" size="sm" variant=${o.last_worn === today ? 'primary' : 'default'} icon="check" title="Indossato oggi"
            @click=${(e: Event) => { e.stopPropagation(); markWorn(this.host, o, '', () => this.load()); }}>${o.last_worn === today ? 'Oggi' : ''}</hxk-button>
          <div class="tx"><span class="nm">${o.name}</span><span class="small muted truncate">${o.pieces.length} capi${o.last_worn ? ' · ' + relDays(o.last_worn) : ''}</span></div>
        </div>`)}</div>`}
    </div>`;
  }
}

export class WardrobeOutfit extends WardrobeElement {
  static properties = { ...WardrobeElement.properties, o: { state: true }, editing: { state: true }, day: { state: true }, busy: { state: true } };
  declare o: any; declare editing: boolean; declare day: string; declare busy: string;
  static styles = [...WardrobeElement.styles, wardrobeStyles, css`
    .slots { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 10px; }
    .slot .lab { font-size: 11px; color: var(--text-3); text-transform: uppercase; letter-spacing: .04em; }
    .stars button { background: none; border: none; font-size: 22px; cursor: pointer; color: var(--border-strong); padding: 0 2px; }
    .stars button[aria-pressed=true] { color: var(--warning); }
    .photos { display: flex; gap: 8px; flex-wrap: wrap; } .photos .ph { width: 120px; height: 150px; border-radius: var(--radius-md); overflow: hidden; position: relative; background: var(--surface-2); }
    .photos img { width: 100%; height: 100%; object-fit: cover; }
    .photos button.x { position: absolute; top: 4px; right: 4px; border: none; border-radius: 50%; width: 22px; height: 22px; background: var(--overlay); color: #fff; cursor: pointer; }
  `];
  constructor() { super(); this.o = undefined; this.editing = false; this.day = ''; this.busy = ''; }
  protected async load() {
    const id = this.ctx?.params?.id;
    if (!id) return;
    const r = await this.host.api('GET', `${API}/outfits/${id}`);
    this.o = r.ok ? r.data : r.status === 404 ? null : this.o ?? null;
  }
  private async patch(changes: any, msg = '') {
    const r = await call(this.host, 'PATCH', `/outfits/${this.o.id}`, changes);
    if (r.ok) { this.o = r.data; if (msg) this.host.toast(msg, 'success'); }
    return r.ok;
  }
  private toggle(k: string, v: string) {
    const cur: string[] = this.o[k] || [];
    this.patch({ [k]: cur.includes(v) ? cur.filter(x => x !== v) : [...cur, v] });
  }
  private async addPhoto() {
    const files = await this.host.upload({ accept: 'image/*', maxSide: 2000 });
    if (!files.length) return;
    this.busy = 'photo';
    const r = await call(this.host, 'POST', `/outfits/${this.o.id}/photos`, { photo: files[0] });
    this.busy = '';
    if (r.ok) this.o = { ...this.o, ...r.data.item };
  }
  private async removePhoto(id: string) {
    const r = await call(this.host, 'DELETE', `/outfits/${this.o.id}/photos/${id}`);
    if (r.ok) this.o = { ...this.o, ...r.data.item };
  }
  private async drop(hard: boolean) {
    const ok = await this.host.confirm(hard ? 'Elimina outfit' : 'Archivia outfit', hard ? `«${this.o.name}» viene eliminato (i capi restano).` : `«${this.o.name}» esce dalla lista ma resta nello storico.`,
      { label: hard ? 'Elimina' : 'Archivia', danger: hard });
    if (!ok) return;
    const r = await call(this.host, 'DELETE', `/outfits/${this.o.id}`, undefined, hard ? { hard: true } : undefined);
    if (r.ok) this.host.navigate('outfit');
  }
  render() {
    const o = this.o, m = this.m;
    if (o === undefined) return html`<div class="page"><hxk-state kind="loading"></hxk-state></div>`;
    if (o === null) return html`<div class="page"><hxk-state kind="empty" text="Outfit non trovato."></hxk-state></div>`;
    const wornToday = o.last_worn === localDay();
    return html`<div class="page">
      <div class="head"><hxk-button variant="ghost" size="sm" @click=${() => this.host.navigate('outfit')}>‹ Outfit</hxk-button></div>
      <div class="between"><div class="grow"><input class="in" style="font-size:20px;font-weight:650;width:100%;background:transparent;border-color:transparent"
          .value=${o.name} @change=${(e: any) => e.target.value.trim() && this.patch({ name: e.target.value.trim() })}>
          <div class="small muted" style="padding-left:10px">${o.wear_count ? `segnato ${o.wear_count} volte · ultima ${relDays(o.last_worn)}` : 'mai segnato'}${o.source === 'assistant' ? ' · proposto dall\'assistente' : ''}</div></div>
        <button class="chip" aria-pressed=${!!o.favorite} title="Preferito (compare nella Home)" @click=${() => this.patch({ favorite: !o.favorite }, o.favorite ? '' : 'Tra i preferiti: lo trovi nella Home')}>★</button></div>
      ${!o.complete ? html`<div class="card" style="border-color:var(--warning)">Alcuni capi non ci sono più o sono stati dati via: modifica i capi dell'outfit.</div>` : nothing}
      <div class="row wrap">
        <hxk-button variant=${wornToday ? 'default' : 'primary'} icon="check" @click=${() => markWorn(this.host, o, '', () => this.load())}>${wornToday ? 'Indossato oggi ✓' : 'Indossato oggi'}</hxk-button>
        <input class="in" type="date" max=${localDay()} .value=${this.day} @change=${(e: any) => (this.day = e.target.value)}>
        ${this.day ? html`<hxk-button size="sm" @click=${() => { markWorn(this.host, o, this.day, () => this.load()); this.day = ''; }}>Segna ${dayLabel(this.day)}</hxk-button>` : nothing}
        <span class="grow"></span>
        <hxk-button variant="ghost" icon="sparkle" @click=${() => this.host.assistant({ label: o.name, hints: { outfit_id: o.id }, prompt: `Cosa ne pensi dell'outfit «${o.name}»?`, suggestions: ['Come lo miglioro?', 'Che accessori ci metto?', 'Per che occasione va bene?'] })}>Chiedi</hxk-button>
      </div>
      ${this.editing ? html`<div class="card"><wardrobe-outfit-builder .host=${this.host} .ctx=${this.ctx} .meta=${m} .value=${o.slots} name=${o.name}
          @save=${async (e: CustomEvent) => { if (await this.patch(e.detail, 'Salvato')) this.editing = false; }} @cancel=${() => (this.editing = false)}></wardrobe-outfit-builder></div>` : html`
        <div class="card col"><div class="between"><h3>Capi</h3><hxk-button size="sm" variant="ghost" icon="edit" @click=${() => (this.editing = true)}>Cambia capi</hxk-button></div>
          <div class="slots">${o.pieces.map((p: any) => html`<div class="tile slot" @click=${() => this.host.navigate('capi/' + p.id)}>
            <div class="ph">${img(this.host, p.photo, p.name)}</div>
            ${!p.available ? html`<hxk-badge class="badge" tone="info">${m?.statuses[p.status] || p.status}</hxk-badge>` : nothing}
            <div class="tx"><span class="lab">${p.slot_label}</span><span class="nm">${p.name}</span>${dots(p.colors, 10)}</div></div>`)}</div></div>`}
      <div class="card col">
        <div class="row wrap" style="gap:14px"><span class="small muted">Voto</span>
          <span class="stars">${[1, 2, 3, 4, 5].map(n => html`<button aria-pressed=${(o.rating || 0) >= n} @click=${() => this.patch({ rating: o.rating === n ? null : n })}>★</button>`)}</span></div>
        <div class="col" style="gap:4px"><span class="small muted">Occasioni</span><div class="chips">${vocabOptions(m, 'occasion').map(v => html`<button class="chip soft" aria-pressed=${(o.occasions || []).includes(v.key)} @click=${() => this.toggle('occasions', v.key)}>${v.label}</button>`)}</div></div>
        <div class="col" style="gap:4px"><span class="small muted">Stile</span><div class="chips">${vocabOptions(m, 'style').map(v => html`<button class="chip soft" aria-pressed=${(o.styles || []).includes(v.key)} @click=${() => this.toggle('styles', v.key)}>${v.label}</button>`)}</div></div>
        <div class="col" style="gap:4px"><span class="small muted">Stagioni</span><div class="chips">${Object.entries(m?.seasons || {}).map(([k, v]) => html`<button class="chip soft" aria-pressed=${(o.seasons || []).includes(k)} @click=${() => this.toggle('seasons', k)}>${SEASON_ICON[k]} ${v}</button>`)}</div></div>
        <textarea class="in" rows="2" placeholder="Note (es. con la cintura marrone)" .value=${o.notes || ''} @change=${(e: any) => this.patch({ notes: e.target.value })}></textarea>
      </div>
      <div class="card col"><div class="between"><h3>Foto indossato</h3><hxk-button size="sm" icon="camera" ?loading=${this.busy === 'photo'} @click=${() => this.addPhoto()}>Aggiungi</hxk-button></div>
        ${o.photos?.length ? html`<div class="photos">${o.photos.map((id: string) => html`<div class="ph"><img src=${photo(this.host, id, 'medium')} alt="">
            <button class="x" title="Togli" @click=${() => this.removePhoto(id)}>×</button></div>`)}</div>`
          : html`<div class="empty">Facoltativo: una foto allo specchio aiuta a ricordare com'era.</div>`}</div>
      ${o.wears?.length ? html`<div class="card col"><h3>Storico</h3><div class="chips">${o.wears.map((w: any) => html`<span class="pill">${dayLabel(w.date)}
          <button class="link" title="Togli" @click=${async () => { await call(this.host, 'DELETE', `/wears/${w.id}`); this.load(); }}>×</button></span>`)}</div></div>` : nothing}
      <div class="row"><span class="grow"></span>
        ${o.status === 'archived' ? html`<hxk-button size="sm" @click=${() => this.patch({ status: 'active' }, 'Ripristinato')}>Ripristina</hxk-button>`
          : html`<hxk-button size="sm" variant="ghost" @click=${() => this.drop(false)}>Archivia</hxk-button>`}
        <hxk-button size="sm" variant="danger" icon="trash" @click=${() => this.drop(true)}>Elimina</hxk-button></div>
    </div>`;
  }
}

export { collage, markWorn };
