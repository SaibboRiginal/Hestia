/**
 * <wardrobe-collections> — packing lists, capsules, shopping lists: new list, «Prepara valigia» from trip dates.
 * <wardrobe-collection>  — one list: tick items, add pieces / outfits / free lines, rename, delete.
 */
import { css, html, nothing } from '@hestia/webui-sdk';
import { API, WardrobeElement, call, dayLabel, img, localDay, norm, vocabOptions, wardrobeStyles } from './util';

export class WardrobeCollections extends WardrobeElement {
  static properties = { ...WardrobeElement.properties, items: { state: true }, trip: { state: true }, creating: { state: true }, busy: { state: true } };
  declare items: any[] | undefined; declare trip: any; declare creating: any; declare busy: boolean;
  static styles = [...WardrobeElement.styles, wardrobeStyles, css`
    .prog { height: 6px; border-radius: 4px; background: var(--surface-3); overflow: hidden; } .prog span { display: block; height: 100%; background: var(--success); }
  `];
  constructor() { super(); this.items = undefined; this.trip = null; this.creating = null; this.busy = false; }
  protected async load() {
    const r = await this.host.api('GET', `${API}/collections`);
    if (r.ok) this.items = r.data.items; else if (this.items === undefined) this.items = [];
  }
  private async pack() {
    const t = this.trip;
    if (!t.from) { this.host.toast('Indica quando parti', 'warning'); return; }
    this.busy = true;
    const body: any = { ...t, temp_c: t.temp_c === '' ? null : t.temp_c };
    if (t.rain === null) delete body.rain;   // empty = the forecast at the place for those days
    const r = await call(this.host, 'POST', '/collections/packing', body);
    this.busy = false;
    if (r.ok) this.host.navigate('liste/' + r.data.id);
  }
  private async create() {
    const c = this.creating;
    if (!c.name.trim()) { this.host.toast('Dai un nome alla lista', 'warning'); return; }
    const r = await call(this.host, 'POST', '/collections', { name: c.name.trim(), type: c.type });
    if (r.ok) this.host.navigate('liste/' + r.data.id);
  }
  render() {
    const m = this.m, items = this.items, t = this.trip, c = this.creating;
    return html`<div class="page">
      <div class="head"><h1>Valigie e liste</h1><span class="grow"></span>
        <hxk-button icon="plus" @click=${() => (this.creating = c ? null : { name: '', type: 'capsule' })}>Nuova lista</hxk-button>
        <hxk-button variant="primary" icon="calendar" @click=${() => (this.trip = t ? null : { place: '', from: localDay(), to: '', occasion: '', temp_c: '', rain: null })}>Prepara valigia</hxk-button></div>
      ${t ? html`<div class="card col"><h2>Valigia</h2><div class="form">
          <input class="in" placeholder="Dove (es. Milano)" .value=${t.place} @input=${(e: any) => (this.trip = { ...t, place: e.target.value })}>
          <label class="row small">Dal <input class="in" type="date" .value=${t.from} @change=${(e: any) => (this.trip = { ...t, from: e.target.value })}></label>
          <label class="row small">Al <input class="in" type="date" .value=${t.to} min=${t.from} @change=${(e: any) => (this.trip = { ...t, to: e.target.value })}></label>
          <select class="in" @change=${(e: any) => (this.trip = { ...t, occasion: e.target.value })}><option value="">Occasione…</option>${vocabOptions(m, 'occasion').map(o => html`<option value=${o.key}>${o.label}</option>`)}</select>
          <input class="in" inputmode="decimal" placeholder="Temperatura °C (vuoto = previsione)" .value=${t.temp_c} @input=${(e: any) => (this.trip = { ...t, temp_c: e.target.value })}>
          <label class="row small"><input type="checkbox" .checked=${!!t.rain} .indeterminate=${t.rain === null} @change=${(e: any) => (this.trip = { ...t, rain: e.target.checked })}> pioggia${t.rain === null ? ' (dalla previsione)' : ''}</label>
        </div><div class="row"><hxk-button variant="primary" icon="sparkle" ?loading=${this.busy} @click=${() => this.pack()}>Proponi cosa portare</hxk-button>
          <span class="small muted">Un outfit al giorno dai capi disponibili; poi la modifichi.</span></div></div>` : nothing}
      ${c ? html`<div class="card row wrap"><input class="in grow" placeholder="Nome (es. Capsule estate)" .value=${c.name} @input=${(e: any) => (this.creating = { ...c, name: e.target.value })}>
          <select class="in" @change=${(e: any) => (this.creating = { ...c, type: e.target.value })}>${Object.entries(m?.collection_types || {}).filter(([k]) => k !== 'packing').map(([k, v]) => html`<option value=${k} ?selected=${c.type === k}>${v}</option>`)}</select>
          <hxk-button variant="primary" @click=${() => this.create()}>Crea</hxk-button></div>` : nothing}
      ${items === undefined ? html`<hxk-state kind="loading"></hxk-state>` : !items.length ? html`<hxk-state kind="empty" text="Nessuna lista. Prepara una valigia o crea una capsule."></hxk-state>` : html`
        <div class="grid" style="--min:260px">${items.map(l => html`<div class="card col" style="cursor:pointer" @click=${() => this.host.navigate('liste/' + l.id)}>
          <div class="between"><h2 class="truncate">${l.name}</h2><hxk-badge tone=${l.type === 'packing' ? 'info' : l.type === 'shopping' ? 'accent' : 'neutral'}>${l.type_label}</hxk-badge></div>
          ${l.trip?.from ? html`<span class="small muted">${dayLabel(l.trip.from)}${l.trip.to && l.trip.to !== l.trip.from ? ' → ' + dayLabel(l.trip.to) : ''}${l.trip.place ? ' · ' + l.trip.place : ''}</span>` : nothing}
          ${l.trip?.weather ? html`<span class="small muted row"><hxk-icon name=${l.trip.weather.icon || 'cloud'} size=${14} tone=${l.trip.weather.rain ? 'info' : 'warning'}></hxk-icon> ${l.trip.weather.min_c != null ? `${l.trip.weather.min_c}–` : ''}${l.trip.weather.temp_c}°${l.trip.weather.rain ? ', pioggia' : ''}</span>` : nothing}
          <span class="small muted">${l.progress.checked}/${l.progress.total} pronti</span>
          <div class="prog"><span style="width:${l.progress.total ? (l.progress.checked / l.progress.total) * 100 : 0}%"></span></div></div>`)}</div>`}
    </div>`;
  }
}

export class WardrobeCollection extends WardrobeElement {
  static properties = { ...WardrobeElement.properties, c: { state: true }, adding: { state: true }, pieces: { state: true }, q: { state: true }, line: { state: true } };
  declare c: any; declare adding: boolean; declare pieces: any[] | undefined; declare q: string; declare line: string;
  static styles = [...WardrobeElement.styles, wardrobeStyles, css`
    .li input[type=checkbox] { width: 20px; height: 20px; accent-color: var(--success); }
    .li.done .grow { text-decoration: line-through; color: var(--text-3); }
    .tiles { --tile: 100px; max-height: 360px; overflow: auto; }
  `];
  constructor() { super(); this.c = undefined; this.adding = false; this.pieces = undefined; this.q = ''; this.line = ''; }
  protected async load() {
    const id = this.ctx?.params?.id;
    if (!id) return;
    const r = await this.host.api('GET', `${API}/collections/${id}`);
    this.c = r.ok ? r.data : r.status === 404 ? null : this.c ?? null;
  }
  private async patch(changes: any) {
    const r = await call(this.host, 'PATCH', `/collections/${this.c.id}`, changes);
    if (r.ok) this.c = r.data;
  }
  private async check(item: string) {
    const r = await call(this.host, 'POST', `/collections/${this.c.id}/check`, { item_id: item });
    if (r.ok) this.c = r.data;
  }
  private async openAdd() {
    this.adding = !this.adding;
    if (this.adding && this.pieces === undefined) {
      const r = await this.host.api('GET', `${API}/pieces`, { query: { limit: 1000, sort: 'name', kind: '' } });
      this.pieces = r.ok ? r.data.items : [];
    }
  }
  private togglePiece(id: string) {
    const ids: string[] = this.c.piece_ids || [];
    this.patch({ piece_ids: ids.includes(id) ? ids.filter(x => x !== id) : [...ids, id] });
  }
  private addLine() {
    if (!this.line.trim()) return;
    this.patch({ items: [...(this.c.items || []), { label: this.line.trim() }] });
    this.line = '';
  }
  private async drop() {
    if (!(await this.host.confirm('Elimina lista', `«${this.c.name}» viene eliminata (i capi restano).`, { label: 'Elimina', danger: true }))) return;
    const r = await call(this.host, 'DELETE', `/collections/${this.c.id}`);
    if (r.ok) this.host.navigate('liste');
  }
  render() {
    const c = this.c;
    if (c === undefined) return html`<div class="page"><hxk-state kind="loading"></hxk-state></div>`;
    if (c === null) return html`<div class="page"><hxk-state kind="empty" text="Lista non trovata."></hxk-state></div>`;
    const checked = new Set(c.checked || []);
    let pcs = this.pieces || [];
    if (this.q) { const w = norm(this.q); pcs = pcs.filter(p => norm(p.name).includes(w)); }
    return html`<div class="page">
      <div class="head"><hxk-button variant="ghost" size="sm" @click=${() => this.host.navigate('liste')}>‹ Liste</hxk-button><span class="grow"></span>
        <hxk-badge>${c.type_label}</hxk-badge><span class="small muted">${c.progress.checked}/${c.progress.total} pronti</span></div>
      <input class="in" style="font-size:20px;font-weight:650;background:transparent;border-color:transparent" .value=${c.name} @change=${(e: any) => e.target.value.trim() && this.patch({ name: e.target.value.trim() })}>
      ${c.outfits.length ? html`<div class="card col"><h3>Outfit</h3><div class="list">${c.outfits.map((o: any) => html`<div class="li ${checked.has(o.id) ? 'done' : ''}">
          <input type="checkbox" .checked=${checked.has(o.id)} @change=${() => this.check(o.id)}>
          <span class="grow truncate" @click=${() => this.host.navigate('outfit/' + o.id)}>${o.name}</span></div>`)}</div></div>` : nothing}
      <div class="card col"><div class="between"><h3>Capi</h3><hxk-button size="sm" icon=${this.adding ? 'check' : 'plus'} @click=${() => this.openAdd()}>${this.adding ? 'Fatto' : 'Aggiungi capi'}</hxk-button></div>
        ${this.adding ? html`<input class="in" placeholder="Cerca…" .value=${this.q} @input=${(e: any) => (this.q = e.target.value)}>
          ${this.pieces === undefined ? html`<hxk-state kind="loading"></hxk-state>` : html`<div class="tiles">${pcs.map(p => html`<div class="tile" data-sel=${(c.piece_ids || []).includes(p.id)} @click=${() => this.togglePiece(p.id)}>
            <div class="ph">${img(this.host, p.photos?.[0], p.name)}</div>${(c.piece_ids || []).includes(p.id) ? html`<span class="check"><hxk-icon name="check" size="14"></hxk-icon></span>` : nothing}
            <div class="tx"><span class="nm">${p.name}</span></div></div>`)}</div>`}` : nothing}
        ${c.pieces.length ? html`<div class="list">${c.pieces.map((p: any) => html`<div class="li ${checked.has(p.id) ? 'done' : ''}">
            <input type="checkbox" .checked=${checked.has(p.id)} @change=${() => this.check(p.id)}>
            <span class="thumb">${img(this.host, p.photo, p.name)}</span>
            <span class="grow truncate" @click=${() => this.host.navigate('capi/' + p.id)}>${p.name}</span>
            <hxk-button size="sm" variant="ghost" icon="x" title="Togli" @click=${() => this.togglePiece(p.id)}></hxk-button></div>`)}</div>`
          : this.adding ? nothing : html`<div class="empty">Nessun capo.</div>`}</div>
      <div class="card col"><h3>Altro da portare</h3>
        <div class="list">${(c.items || []).map((i: any) => html`<div class="li ${checked.has(i.id) ? 'done' : ''}">
          <input type="checkbox" .checked=${checked.has(i.id)} @change=${() => this.check(i.id)}><span class="grow">${i.label}</span>
          <hxk-button size="sm" variant="ghost" icon="x" @click=${() => this.patch({ items: c.items.filter((x: any) => x.id !== i.id) })}></hxk-button></div>`)}</div>
        <div class="row"><input class="in grow" placeholder="es. caricabatterie, ombrello" .value=${this.line} @input=${(e: any) => (this.line = e.target.value)} @keydown=${(e: KeyboardEvent) => e.key === 'Enter' && this.addLine()}>
          <hxk-button size="sm" icon="plus" @click=${() => this.addLine()}>Aggiungi</hxk-button></div></div>
      <textarea class="in" rows="2" placeholder="Note" .value=${c.notes || ''} @change=${(e: any) => this.patch({ notes: e.target.value })}></textarea>
      <div class="row"><span class="grow"></span>
        <hxk-button size="sm" variant="ghost" @click=${() => this.patch({ archived: !c.archived })}>${c.archived ? 'Ripristina' : 'Archivia'}</hxk-button>
        <hxk-button size="sm" variant="danger" icon="trash" @click=${() => this.drop()}>Elimina</hxk-button></div>
    </div>`;
  }
}
