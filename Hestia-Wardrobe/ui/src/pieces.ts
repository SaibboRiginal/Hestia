/**
 * <wardrobe-pieces>      — every piece as photo tiles: search, filters, quick add, multi-select (laundry, outfit, archive).
 * <wardrobe-accessories> — the same page limited to accessories.
 * <wardrobe-piece>       — one piece: photos, details, status in one tap, outfits, «Indossato», edit, archive/delete.
 */
import { css, html, nothing } from '@hestia/webui-sdk';
import { API, STATUS_TONE, SEASON_ICON, WardrobeElement, call, dayLabel, dots, img, label, money, photo, relDays, vocabOptions, wardrobeStyles } from './util';

const SORTS: Record<string, string> = { recent: 'Aggiunti di recente', name: 'Nome', least_worn: 'Meno usati', last_worn: 'Usati di recente', worn: 'Più usati' };
const QUICK_STATUS = ['active', 'laundry', 'lent', 'to_repair', 'stored', 'to_donate'];

export class WardrobePieces extends WardrobeElement {
  static properties = { ...WardrobeElement.properties, items: { state: true }, total: { state: true }, q: { state: true }, f: { state: true },
                        adding: { state: true }, sel: { state: true }, selecting: { state: true } };
  declare items: any[] | undefined; declare total: number; declare q: string; declare f: Record<string, string>;
  declare adding: boolean; declare sel: string[]; declare selecting: boolean;
  protected fixedKind = '';
  private _t: any = null;
  static styles = [...WardrobeElement.styles, wardrobeStyles, css`
    .filters { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
    .filters select.in { padding: 5px 8px; }
  `];
  constructor() { super(); this.items = undefined; this.total = 0; this.q = ''; this.f = { sort: 'recent' }; this.adding = false; this.sel = []; this.selecting = false; }

  connectedCallback() {
    if (this.ctx?.query?.nuovo !== undefined) this.adding = true;
    if (this.ctx?.query?.status) this.f = { ...this.f, status: this.ctx.query.status };
    super.connectedCallback();
  }

  protected async load() {
    const query: Record<string, any> = { q: this.q, limit: 600, ...this.f };
    if (this.fixedKind) query.kind = this.fixedKind;
    else if (!query.kind) query.kind = 'garment,shoes';
    if (query.favorite === '') delete query.favorite;
    const r = await this.host.api('GET', `${API}/pieces`, { query });
    if (r.ok) { this.items = r.data.items; this.total = r.data.total; } else if (this.items === undefined) this.items = [];
  }
  private filter(k: string, v: string) { this.f = { ...this.f, [k]: this.f[k] === v ? '' : v }; this.load(); }
  private search(v: string) { this.q = v; clearTimeout(this._t); this._t = setTimeout(() => this.load(), 220); }

  private async onSave(e: CustomEvent) {
    const { data, photo: up, again } = e.detail;
    if (this.fixedKind && !data.kind) data.kind = this.fixedKind;
    const r = await call(this.host, 'POST', '/pieces', { ...data, ...(up ? { photo: up } : {}) });
    if (!r.ok) return;
    this.host.toast(`«${r.data.name}» aggiunto`, 'success', { label: 'Apri', run: () => this.host.navigate('capi/' + r.data.id) });
    if (again) (this.renderRoot.querySelector('wardrobe-piece-form') as any)?.reset();
    else this.adding = false;
    this.load();
  }

  private toggleSel(id: string) { this.sel = this.sel.includes(id) ? this.sel.filter(x => x !== id) : [...this.sel, id]; }
  private async bulk(changes: any, text: string) {
    const r = await call(this.host, 'POST', '/pieces/bulk', { ids: this.sel, changes });
    if (r.ok) { this.host.toast(`${r.data.updated} ${text}`, 'success'); this.sel = []; this.selecting = false; this.load(); }
  }
  private async outfitFromSel() {
    const r = await call(this.host, 'POST', '/outfits', { piece_ids: this.sel });
    if (r.ok) { this.sel = []; this.selecting = false; this.host.navigate('outfit/' + r.data.id); }
  }

  protected heading() { return 'Guardaroba'; }

  render() {
    const m = this.m;
    const items = this.items;
    const kindCats = vocabOptions(m, 'category').filter(c => !c.parent && (this.fixedKind ? c.kind === this.fixedKind : c.kind !== 'accessory'));
    const colors = vocabOptions(m, 'color');
    return html`<div class="page">
      <div class="head"><h1>${this.heading()}</h1><span class="sub">${items ? this.total : ''}</span><span class="grow"></span>
        <hxk-button variant=${this.selecting ? 'primary' : 'ghost'} icon="check" @click=${() => { this.selecting = !this.selecting; this.sel = []; }}>${this.selecting ? 'Fine' : 'Seleziona'}</hxk-button>
        <hxk-button variant="primary" icon="plus" @click=${() => (this.adding = !this.adding)}>Aggiungi</hxk-button></div>
      ${this.adding ? html`<div class="card"><wardrobe-piece-form .host=${this.host} .ctx=${this.ctx} .meta=${m} kind=${this.fixedKind || 'garment'}
          @save=${this.onSave} @cancel=${() => (this.adding = false)}></wardrobe-piece-form></div>` : nothing}
      <input class="in" placeholder="Cerca: «camicia azzurra», «lino», «Uniqlo»…" .value=${this.q} @input=${(e: any) => this.search(e.target.value)}>
      <div class="filters">
        ${this.fixedKind ? nothing : html`<button class="chip soft" aria-pressed=${!this.f.kind} @click=${() => { this.f = { ...this.f, kind: '' }; this.load(); }}>Tutto</button>
          <button class="chip soft" aria-pressed=${this.f.kind === 'garment'} @click=${() => this.filter('kind', 'garment')}>Capi</button>
          <button class="chip soft" aria-pressed=${this.f.kind === 'shoes'} @click=${() => this.filter('kind', 'shoes')}>Scarpe</button>`}
        <button class="chip soft" aria-pressed=${this.f.favorite === 'true'} @click=${() => this.filter('favorite', 'true')}>★</button>
        ${m ? Object.entries(m.seasons).map(([k, v]) => html`<button class="chip soft" title=${v} aria-pressed=${this.f.season === k} @click=${() => this.filter('season', k)}>${SEASON_ICON[k]}</button>`) : nothing}
        <select class="in" @change=${(e: any) => { this.f = { ...this.f, category: e.target.value }; this.load(); }}>
          <option value="">Ogni categoria</option>${kindCats.map(c => html`<option value=${c.key} ?selected=${this.f.category === c.key}>${c.label}</option>`)}</select>
        <select class="in" @change=${(e: any) => { this.f = { ...this.f, color: e.target.value }; this.load(); }}>
          <option value="">Ogni colore</option>${colors.map(c => html`<option value=${c.key} ?selected=${this.f.color === c.key}>${c.label}</option>`)}</select>
        <select class="in" @change=${(e: any) => { this.f = { ...this.f, status: e.target.value }; this.load(); }}>
          <option value="">Nell'armadio e altro</option>${m ? Object.entries(m.statuses).map(([k, v]) => html`<option value=${k} ?selected=${this.f.status === k}>${v}</option>`) : nothing}</select>
        <select class="in" @change=${(e: any) => { this.f = { ...this.f, sort: e.target.value }; this.load(); }}>
          ${Object.entries(SORTS).map(([k, v]) => html`<option value=${k} ?selected=${this.f.sort === k}>${v}</option>`)}</select>
      </div>
      ${items === undefined ? html`<hxk-state kind="loading"></hxk-state>` : !items.length ? html`<hxk-state kind="empty"
          text=${this.q || Object.values(this.f).some(v => v && v !== 'recent') ? 'Nessun capo con questi filtri.' : 'Ancora vuoto: «Aggiungi» e scatta una foto, ci vogliono pochi secondi.'}></hxk-state>` : html`
        <div class="tiles">${items.map(p => html`<div class="tile" data-sel=${this.sel.includes(p.id)}
            @click=${() => (this.selecting ? this.toggleSel(p.id) : this.host.navigate('capi/' + p.id))}>
          <div class="ph">${img(this.host, p.photos?.[0], p.name)}</div>
          ${p.status !== 'active' ? html`<hxk-badge class="badge" tone=${STATUS_TONE[p.status] || 'neutral'}>${p.status_label}</hxk-badge>` : nothing}
          ${this.selecting && this.sel.includes(p.id) ? html`<span class="check"><hxk-icon name="check" size="14"></hxk-icon></span>` : p.favorite ? html`<span class="fav">★</span>` : nothing}
          <div class="tx"><span class="nm">${p.name}</span>
            <span class="small muted row" style="gap:6px">${dots(p.colors, 10)}<span class="truncate">${p.subcategory_label || p.category_label}${p.brand ? ' · ' + p.brand : ''}</span></span></div>
        </div>`)}</div>`}
      ${this.selecting && this.sel.length ? html`<div class="bar"><b>${this.sel.length}</b> selezionati<span class="grow"></span>
        <hxk-button size="sm" icon="refresh" @click=${() => this.bulk({ status: 'laundry' }, 'in lavanderia')}>In lavanderia</hxk-button>
        <hxk-button size="sm" icon="home" @click=${() => this.bulk({ status: 'active' }, 'di nuovo nell\'armadio')}>Nell'armadio</hxk-button>
        ${this.fixedKind ? nothing : html`<hxk-button size="sm" variant="primary" icon="plus" @click=${() => this.outfitFromSel()}>Crea outfit</hxk-button>`}
        <hxk-button size="sm" variant="ghost" @click=${() => this.bulk({ status: 'to_donate' }, 'da donare')}>Da donare</hxk-button>
      </div>` : nothing}
    </div>`;
  }
}

export class WardrobeAccessories extends WardrobePieces {
  protected fixedKind = 'accessory';
  protected heading() { return 'Accessori'; }
}

export class WardrobePiece extends WardrobeElement {
  static properties = { ...WardrobeElement.properties, p: { state: true }, editing: { state: true }, cover: { state: true }, busy: { state: true } };
  declare p: any; declare editing: boolean; declare cover: string; declare busy: string;
  static styles = [...WardrobeElement.styles, wardrobeStyles, css`
    .layout { display: grid; grid-template-columns: minmax(240px, 380px) 1fr; gap: 18px; align-items: start; }
    .gallery { display: flex; flex-direction: column; gap: 8px; }
    .main { aspect-ratio: 1; border-radius: var(--radius-lg); background: var(--surface-2); overflow: hidden; display: grid; place-items: center; color: var(--text-3); }
    .main img { width: 100%; height: 100%; object-fit: contain; }
    .thumbs { display: flex; gap: 6px; flex-wrap: wrap; }
    .thumbs button { width: 56px; height: 56px; border-radius: var(--radius-sm); overflow: hidden; border: 2px solid transparent; padding: 0; cursor: pointer; background: var(--surface-2); }
    .thumbs button[aria-pressed=true] { border-color: var(--accent); }
    .thumbs img { width: 100%; height: 100%; object-fit: cover; }
    dl { display: grid; grid-template-columns: max-content 1fr; gap: 6px 14px; margin: 0; font-size: 13.5px; }
    dt { color: var(--text-3); } dd { margin: 0; }
    @media (max-width: 860px) { .layout { grid-template-columns: 1fr; } }
  `];
  constructor() { super(); this.p = undefined; this.editing = false; this.cover = ''; this.busy = ''; }

  protected async load() {
    const id = this.ctx?.params?.id;
    if (!id) return;
    const r = await this.host.api('GET', `${API}/pieces/${id}`);
    this.p = r.ok ? r.data : r.status === 404 ? null : this.p ?? null;
    if (this.p && !this.p.photos?.includes(this.cover)) this.cover = this.p.photos?.[0] || '';
  }
  private async patch(changes: any, msg = '') {
    const r = await call(this.host, 'PATCH', `/pieces/${this.p.id}`, changes);
    if (r.ok) { this.p = r.data; if (msg) this.host.toast(msg, 'success'); }
    return r.ok;
  }
  private async addPhoto() {
    const files = await this.host.upload({ accept: 'image/*', multiple: true, maxSide: 2000 });
    for (const f of files) {
      this.busy = 'photo';
      const r = await call(this.host, 'POST', `/pieces/${this.p.id}/photos`, { photo: f });
      if (r.ok) this.p = r.data.item;
    }
    this.busy = '';
    if (this.p) this.cover = this.p.photos?.[0] || '';
  }
  private async removePhoto(id: string) {
    if (!(await this.host.confirm('Togli foto', 'La foto viene eliminata.', { label: 'Elimina', danger: true }))) return;
    const r = await call(this.host, 'DELETE', `/pieces/${this.p.id}/photos/${id}`);
    if (r.ok) { this.p = r.data.item; this.cover = this.p.photos?.[0] || ''; }
  }
  private async setCover(id: string) {
    const r = await call(this.host, 'POST', `/pieces/${this.p.id}/photos/${id}/cover`);
    if (r.ok) { this.p = r.data; this.cover = id; this.host.toast('Foto principale cambiata', 'success'); }
  }
  private async worn() {
    const r = await call(this.host, 'POST', '/wears', { piece_ids: [this.p.id] });
    if (r.ok) {
      const w = r.data;
      this.host.toast(w.already ? 'Già segnato oggi' : 'Segnato indossato oggi', 'success', w.already ? undefined : { label: 'Annulla', run: async () => { await call(this.host, 'DELETE', `/wears/${w.id}`); this.load(); } });
      this.load();
    }
  }
  private async onSave(e: CustomEvent) {
    if (await this.patch(e.detail.data, 'Salvato')) this.editing = false;
  }
  private async drop(hard: boolean) {
    const ok = await this.host.confirm(hard ? 'Elimina definitivamente' : 'Archivia', hard
      ? `«${this.p.name}» e le sue foto vengono eliminati per sempre. Gli outfit che lo usano andranno rivisti.`
      : `«${this.p.name}» esce dal guardaroba ma resta nello storico. Puoi ripristinarlo.`, { label: hard ? 'Elimina' : 'Archivia', danger: hard });
    if (!ok) return;
    const r = await call(this.host, 'DELETE', `/pieces/${this.p.id}`, undefined, hard ? { hard: true } : undefined);
    if (r.ok) { this.host.toast(hard ? 'Eliminato' : 'Archiviato', 'success'); this.host.navigate(this.p.kind === 'accessory' ? 'accessori' : 'capi'); }
  }

  render() {
    const p = this.p, m = this.m;
    if (p === undefined) return html`<div class="page"><hxk-state kind="loading"></hxk-state></div>`;
    if (p === null) return html`<div class="page"><hxk-state kind="empty" text="Capo non trovato."></hxk-state></div>`;
    const back = p.kind === 'accessory' ? 'accessori' : 'capi';
    const cur = m?.currency || 'EUR';
    const info: Array<[string, any]> = [
      ['Categoria', p.subcategory_label || p.category_label], ['Marca', [p.brand, p.model].filter(Boolean).join(' ')], ['Taglia', p.size],
      ['Colori', p.colors?.length ? html`${dots(p.colors)} ${p.colors.map((c: any) => c.name).join(', ')}` : ''],
      ['Fantasia', p.pattern && p.pattern !== 'plain' ? label(m, 'pattern', p.pattern) : ''],
      ['Materiali', (p.materials || []).map((x: any) => x.percent ? `${x.name} ${x.percent}%` : x.name).join(', ')],
      ['Vestibilità', p.fit ? label(m, 'fit', p.fit) : ''],
      ['Stagioni', (p.seasons || []).length === 4 ? 'tutte' : (p.seasons || []).map((s: string) => `${SEASON_ICON[s]} ${m?.seasons[s] || s}`).join(' ')],
      ['Stile', (p.styles || []).map((s: string) => label(m, 'style', s)).join(', ')],
      ['Occasioni', (p.occasions || []).map((s: string) => label(m, 'occasion', s)).join(', ')],
      ['Calore · formalità', `${p.warmth}/5 · ${p.formality}/5`],
      ['Dove sta', p.location ? label(m, 'location', p.location) : ''], ['Condizione', m?.conditions?.[p.condition] || ''],
      ['Acquisto', [p.purchase?.price != null ? money(p.purchase.price, p.purchase.currency || cur) : '', p.purchase?.date ? dayLabel(p.purchase.date) : '', p.purchase?.store, p.purchase?.gift ? 'regalo' : ''].filter(Boolean).join(' · ')],
      ['Cura', [p.care?.wash_c ? `${p.care.wash_c}°` : '', p.care?.notes].filter(Boolean).join(' · ')],
      ['Note', p.notes],
    ];
    return html`<div class="page">
      <div class="head"><hxk-button variant="ghost" size="sm" @click=${() => this.host.navigate(back)}>‹ ${back === 'capi' ? 'Guardaroba' : 'Accessori'}</hxk-button></div>
      <div class="layout">
        <div class="gallery">
          <div class="main">${this.cover ? html`<img src=${photo(this.host, this.cover, 'medium')} alt=${p.name}>` : html`<hxk-icon name="shirt" size="64"></hxk-icon>`}</div>
          <div class="thumbs">${(p.photos || []).map((id: string) => html`<button aria-pressed=${id === this.cover} @click=${() => (this.cover = id)}><img src=${photo(this.host, id)} alt=""></button>`)}
            <hxk-button size="sm" icon="camera" ?loading=${this.busy === 'photo'} @click=${() => this.addPhoto()}>${p.photos?.length ? 'Altra foto' : 'Aggiungi foto'}</hxk-button></div>
          ${this.cover && p.photos?.length > 1 ? html`<div class="row small">${this.cover !== p.photos[0] ? html`<button class="link" @click=${() => this.setCover(this.cover)}>Usa come principale</button>` : html`<span class="muted">Foto principale</span>`}
            <span class="grow"></span><button class="link" @click=${() => this.removePhoto(this.cover)}>Togli</button></div>`
          : this.cover ? html`<div class="row small"><span class="grow"></span><button class="link" @click=${() => this.removePhoto(this.cover)}>Togli foto</button></div>` : nothing}
        </div>
        <div class="col" style="gap:14px">
          <div class="between"><div><h1>${p.name}</h1><div class="small muted">${p.subcategory_label || p.category_label}${p.brand ? ' · ' + p.brand : ''}</div></div>
            <button class="chip" title="Preferito" aria-pressed=${!!p.favorite} @click=${() => this.patch({ favorite: !p.favorite })}>★</button></div>
          <div class="chips">${QUICK_STATUS.map(s => html`<button class="chip soft" aria-pressed=${p.status === s} @click=${() => p.status !== s && this.patch({ status: s }, m?.statuses[s])}>${m?.statuses[s] || s}</button>`)}
            ${QUICK_STATUS.includes(p.status) ? nothing : html`<hxk-badge tone="neutral">${p.status_label}</hxk-badge>`}</div>
          <hxk-stat .items=${[
            { label: 'Segnato indossato', value: p.wear_count || 0, unit: 'volte', hint: p.last_worn ? relDays(p.last_worn) : 'facoltativo' },
            ...(p.cost_per_wear ? [{ label: 'Costo per utilizzo', value: money(p.cost_per_wear, cur) }] : []),
            { label: 'Outfit', value: p.outfits?.length || 0 },
          ]}></hxk-stat>
          <div class="row wrap">
            <hxk-button icon="check" @click=${() => this.worn()}>Indossato oggi</hxk-button>
            ${p.kind !== 'accessory' ? html`<hxk-button icon="plus" @click=${() => this.host.navigate('outfit', { con: p.id })}>Crea outfit con questo</hxk-button>` : nothing}
            <hxk-button icon="sparkle" variant="ghost" @click=${() => this.host.assistant({ label: p.name, hints: { piece_id: p.id }, prompt: `Con cosa abbino «${p.name}»?`, suggestions: ['Con cosa lo abbino?', 'Come lo lavo?', 'Vale la pena tenerlo?'] })}>Chiedi</hxk-button>
          </div>
          ${this.editing ? html`<div class="card"><wardrobe-piece-form .host=${this.host} .ctx=${this.ctx} .meta=${m} .value=${p} editing kind=${p.kind}
              @save=${this.onSave} @cancel=${() => (this.editing = false)}></wardrobe-piece-form></div>` : html`
            <div class="card col"><div class="between"><h3>Dettagli</h3><hxk-button size="sm" variant="ghost" icon="edit" @click=${() => (this.editing = true)}>Modifica</hxk-button></div>
              <dl>${info.filter(([, v]) => v).map(([k, v]) => html`<dt>${k}</dt><dd>${v}</dd>`)}</dl></div>`}
          ${p.outfits?.length ? html`<div class="card col"><h3>Negli outfit</h3><div class="tiles" style="--tile:120px">${p.outfits.map((o: any) => html`
              <div class="tile" @click=${() => this.host.navigate('outfit/' + o.id)}><div class="ph">${img(this.host, o.photo, o.name)}</div>
                ${o.favorite ? html`<span class="fav">★</span>` : nothing}<div class="tx"><span class="nm">${o.name}</span></div></div>`)}</div></div>` : nothing}
          ${p.wears?.length ? html`<div class="card col"><h3>Segnato indossato</h3><div class="chips">${p.wears.map((w: any) => html`<span class="pill">${dayLabel(w.date)}</span>`)}</div></div>` : nothing}
          <div class="row wrap"><span class="grow"></span>
            ${p.status === 'archived' ? html`<hxk-button size="sm" @click=${() => this.patch({ status: 'active' }, 'Ripristinato')}>Ripristina</hxk-button>`
              : html`<hxk-button size="sm" variant="ghost" @click=${() => this.drop(false)}>Archivia</hxk-button>`}
            <hxk-button size="sm" variant="danger" icon="trash" @click=${() => this.drop(true)}>Elimina</hxk-button></div>
        </div>
      </div>
    </div>`;
  }
}

