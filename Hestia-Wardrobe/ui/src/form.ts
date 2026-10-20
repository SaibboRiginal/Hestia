/**
 * <wardrobe-piece-form> — add / edit one piece: photo (with «Riconosci con AI»), the few fields that matter first,
 * the rest under «Altri dettagli». Emits `save` (detail {data, photo, again}) and `cancel`.
 */
import { HestiaElement, css, html, nothing } from '@hestia/webui-sdk';
import type { HestiaHost, Upload } from '@hestia/webui-sdk';
import { API, Meta, seasonIcon, vocabOptions, wardrobeStyles } from './util';

export class WardrobePieceForm extends HestiaElement {
  static properties = { ...HestiaElement.properties, meta: { attribute: false }, value: { attribute: false }, kind: {},
                        d: { state: true }, upload: { state: true }, more: { state: true }, busy: { state: true }, aiMsg: { state: true }, editing: { type: Boolean } };
  declare meta: Meta | null; declare value: any; declare kind: string; declare editing: boolean;
  declare d: any; declare upload: Upload[]; declare more: boolean; declare busy: string; declare aiMsg: string;
  static styles = [...HestiaElement.styles, wardrobeStyles, css`
    :host { display: block; }
    .top { display: flex; gap: 14px; flex-wrap: wrap; align-items: flex-start; }
    .fields { flex: 1; min-width: 240px; display: flex; flex-direction: column; gap: 10px; }
    label.f { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--text-2); font-weight: 500; }
    .sw { width: 26px; height: 26px; border-radius: 50%; border: 2px solid transparent; cursor: pointer; padding: 0; outline: 1px solid var(--border-strong); }
    .sw[aria-pressed=true] { border-color: var(--surface); outline: 2px solid var(--accent); }
    .scale { display: flex; gap: 4px; } .scale .chip { min-width: 34px; justify-content: center; padding: 4px 8px; }
  `];
  constructor() { super(); this.value = null; this.kind = ''; this.editing = false; this.d = null; this.upload = []; this.more = false; this.busy = ''; this.aiMsg = ''; }

  willUpdate(ch: Map<string, unknown>) {
    if (ch.has('value') || this.d === null) {
      const v = this.value || {};
      this.d = {
        name: v.name || '', category: v.subcategory || v.category || '', colors: (v.colors || []).map((c: any) => c.key),
        brand: v.brand || '', size: v.size || '', seasons: v.seasons || [], styles: v.styles || [], occasions: v.occasions || [],
        pattern: v.pattern || '', fit: v.fit || '', materials: (v.materials || []).map((m: any) => m.name).join(', '),
        warmth: v.warmth || null, formality: v.formality || null, status: v.status || (this.kind === 'wishlist' ? 'wishlist' : 'active'),
        condition: v.condition || 'good', location: v.location || '', notes: v.notes || '', favorite: !!v.favorite,
        price: v.purchase?.price ?? null, date: v.purchase?.date || '', store: v.purchase?.store || '', gift: !!v.purchase?.gift,
        rain_ok: v.weather?.rain_ok ?? null, wash_c: v.care?.wash_c ?? null, care_notes: v.care?.notes || '',
      };
      if (!this.editing) this.more = false;
    }
  }

  private set(k: string, v: any) { this.d = { ...this.d, [k]: v }; }
  private toggle(k: string, v: string) {
    const cur: string[] = this.d[k] || [];
    this.set(k, cur.includes(v) ? cur.filter(x => x !== v) : [...cur, v]);
  }

  private async recognise() {
    if (!this.upload.length) return;
    this.busy = 'ai'; this.aiMsg = '';
    const r = await (this.host as HestiaHost).api('POST', `${API}/describe-photo`, { body: { photo: this.upload[0] } });
    this.busy = '';
    if (!r.ok) { this.aiMsg = 'Riconoscimento non riuscito: compila a mano'; return; }
    const f = r.data?.fields || {};
    const next = { ...this.d };
    if (f.name && !next.name) next.name = f.name;
    if (f.subcategory || f.category) next.category = f.subcategory || f.category;
    for (const k of ['colors', 'styles', 'seasons']) if (f[k]?.length) next[k] = f[k];
    for (const k of ['pattern', 'fit', 'brand', 'warmth', 'formality']) if (f[k] && !next[k]) next[k] = f[k];
    if (f.materials?.length && !next.materials) next.materials = f.materials.map((m: any) => m.name).join(', ');
    this.d = next;
    this.aiMsg = r.data?.message || '';
  }

  private emitSave(again = false) {
    const d = this.d;
    if (!d.name.trim()) { this.host.toast('Dai un nome al capo', 'warning'); return; }
    if (!d.category) { this.host.toast('Scegli la categoria', 'warning'); return; }
    const data: any = {
      name: d.name.trim(), category: d.category, colors: d.colors, brand: d.brand, size: d.size, seasons: d.seasons, styles: d.styles,
      occasions: d.occasions, pattern: d.pattern, fit: d.fit, status: d.status, condition: d.condition, location: d.location,
      notes: d.notes, favorite: d.favorite,
      materials: String(d.materials || '').split(',').map((s: string) => s.trim()).filter(Boolean),
      purchase: { price: d.price === '' ? null : d.price, date: d.date || null, store: d.store, gift: d.gift },
      weather: d.rain_ok === null ? {} : { rain_ok: d.rain_ok },
      care: { ...(d.wash_c ? { wash_c: d.wash_c } : {}), ...(d.care_notes ? { notes: d.care_notes } : {}) },
    };
    if (d.warmth) data.warmth = d.warmth;
    if (d.formality) data.formality = d.formality;
    if (this.editing) data.subcategory = '';           // category picker already gives the most specific key
    this.dispatchEvent(new CustomEvent('save', { detail: { data, photo: this.upload[0] || null, again }, bubbles: true, composed: true }));
  }

  /** Clears the form after «Salva e aggiungi un altro» (keeps category, season and status: often the same). */
  reset() {
    this.d = { ...this.d, name: '', colors: [], brand: '', size: '', notes: '', price: null, date: '', materials: '' };
    this.upload = []; this.aiMsg = '';
  }

  private categories() {
    const cats = vocabOptions(this.meta, 'category');
    const kinds = this.kind === 'accessory' ? ['accessory'] : this.kind === 'garment' ? ['garment', 'shoes'] : ['garment', 'shoes', 'accessory'];
    const parents = cats.filter(c => !c.parent && kinds.includes(c.kind || 'garment'));
    return parents.map(p => ({ p, subs: cats.filter(c => c.parent === p.key) }));
  }

  private scale(k: string, lo: string, hi: string) {
    return html`<div class="row small muted" style="gap:6px">${lo}<div class="scale">${[1, 2, 3, 4, 5].map(n => html`<button class="chip soft"
      aria-pressed=${this.d[k] === n} @click=${() => this.set(k, this.d[k] === n ? null : n)}>${n}</button>`)}</div>${hi}</div>`;
  }

  render() {
    const d = this.d, m = this.meta;
    if (!d || !m) return html`<hxk-state kind="loading"></hxk-state>`;
    const colors = vocabOptions(m, 'color');
    return html`<div class="col" style="gap:12px">
      <div class="top">
        ${this.editing ? nothing : html`<div class="col" style="gap:6px;align-items:flex-start">
          <hxk-image-picker .host=${this.host} .value=${this.upload} label="Foto" @change=${(e: CustomEvent) => { e.stopPropagation(); this.upload = e.detail; }}></hxk-image-picker>
          ${this.upload.length ? html`<hxk-button size="sm" icon="sparkle" ?loading=${this.busy === 'ai'} @click=${() => this.recognise()}>Riconosci con AI</hxk-button>` : nothing}
          ${this.aiMsg ? html`<span class="small muted" style="max-width:180px">${this.aiMsg}</span>` : nothing}
        </div>`}
        <div class="fields">
          <label class="f">Nome<input class="in" placeholder="es. Camicia Oxford azzurra" .value=${d.name} @input=${(e: any) => this.set('name', e.target.value)}></label>
          <label class="f">Categoria<select class="in" @change=${(e: any) => this.set('category', e.target.value)}>
            <option value="" ?selected=${!d.category}>Scegli…</option>
            ${this.categories().map(({ p, subs }) => html`<optgroup label=${p.label}>
              <option value=${p.key} ?selected=${d.category === p.key}>${p.label} (generico)</option>
              ${subs.map(s => html`<option value=${s.key} ?selected=${d.category === s.key}>${s.label}</option>`)}</optgroup>`)}
          </select></label>
          <div class="col" style="gap:4px"><span class="small muted">Colori (il primo è il principale)</span>
            <div class="row wrap" style="gap:6px">${colors.map(c => html`<button class="sw" title=${c.label} aria-pressed=${d.colors.includes(c.key)}
              style="background:${c.hex || 'var(--surface-3)'}" @click=${() => this.toggle('colors', c.key)}></button>`)}</div>
            ${d.colors.length ? html`<span class="small">${d.colors.map((k: string) => colors.find(c => c.key === k)?.label || k).join(', ')}</span>` : nothing}</div>
          <div class="col" style="gap:4px"><span class="small muted">Stagioni (nessuna = tutte)</span>
            <div class="chips">${Object.entries(m.seasons).map(([k, v]) => html`<button class="chip soft" aria-pressed=${d.seasons.includes(k)} @click=${() => this.toggle('seasons', k)}>${seasonIcon(k)} ${v}</button>`)}</div></div>
        </div>
      </div>
      <div class="form">
        <label class="f">Marca<input class="in" .value=${d.brand} @input=${(e: any) => this.set('brand', e.target.value)}></label>
        <label class="f">Taglia<input class="in" .value=${d.size} @input=${(e: any) => this.set('size', e.target.value)}></label>
        <label class="f">Prezzo (${m.currency})<input class="in" inputmode="decimal" .value=${d.price ?? ''} @input=${(e: any) => this.set('price', e.target.value === '' ? null : Number(String(e.target.value).replace(',', '.')))}></label>
        <label class="f">Stato<select class="in" @change=${(e: any) => this.set('status', e.target.value)}>${Object.entries(m.statuses).map(([k, v]) => html`<option value=${k} ?selected=${d.status === k}>${v}</option>`)}</select></label>
      </div>
      <div class="col" style="gap:4px"><span class="small muted">Stile</span>
        <div class="chips">${vocabOptions(m, 'style').map(s => html`<button class="chip soft" aria-pressed=${d.styles.includes(s.key)} @click=${() => this.toggle('styles', s.key)}>${s.label}</button>`)}</div></div>
      ${this.more ? html`
        <div class="col" style="gap:4px"><span class="small muted">Occasioni</span>
          <div class="chips">${vocabOptions(m, 'occasion').map(s => html`<button class="chip soft" aria-pressed=${d.occasions.includes(s.key)} @click=${() => this.toggle('occasions', s.key)}>${s.label}</button>`)}</div></div>
        <div class="row wrap" style="gap:18px">
          <div class="col" style="gap:4px"><span class="small muted">Calore</span>${this.scale('warmth', 'leggero', 'caldo')}</div>
          <div class="col" style="gap:4px"><span class="small muted">Formalità</span>${this.scale('formality', 'sportivo', 'elegante')}</div>
          <label class="row small"><input type="checkbox" .checked=${d.rain_ok === true} @change=${(e: any) => this.set('rain_ok', e.target.checked ? true : null)}> va bene con la pioggia</label>
        </div>
        <div class="form">
          <label class="f">Fantasia<select class="in" @change=${(e: any) => this.set('pattern', e.target.value)}><option value="">–</option>${vocabOptions(m, 'pattern').map(o => html`<option value=${o.key} ?selected=${d.pattern === o.key}>${o.label}</option>`)}</select></label>
          <label class="f">Vestibilità<select class="in" @change=${(e: any) => this.set('fit', e.target.value)}><option value="">–</option>${vocabOptions(m, 'fit').map(o => html`<option value=${o.key} ?selected=${d.fit === o.key}>${o.label}</option>`)}</select></label>
          <label class="f">Materiali<input class="in" placeholder="cotone, lino" .value=${d.materials} @input=${(e: any) => this.set('materials', e.target.value)}></label>
          <label class="f">Dove sta<select class="in" @change=${(e: any) => this.set('location', e.target.value)}><option value="">–</option>${vocabOptions(m, 'location').map(o => html`<option value=${o.key} ?selected=${d.location === o.key}>${o.label}</option>`)}</select></label>
          <label class="f">Condizione<select class="in" @change=${(e: any) => this.set('condition', e.target.value)}>${Object.entries(m.conditions).map(([k, v]) => html`<option value=${k} ?selected=${d.condition === k}>${v}</option>`)}</select></label>
          <label class="f">Acquistato il<input class="in" type="date" .value=${d.date} @change=${(e: any) => this.set('date', e.target.value)}></label>
          <label class="f">Negozio<input class="in" .value=${d.store} @input=${(e: any) => this.set('store', e.target.value)}></label>
          <label class="f">Lavaggio °C<input class="in" inputmode="numeric" .value=${d.wash_c ?? ''} @input=${(e: any) => this.set('wash_c', e.target.value ? Number(e.target.value) : null)}></label>
        </div>
        <label class="row small"><input type="checkbox" .checked=${d.gift} @change=${(e: any) => this.set('gift', e.target.checked)}> regalo</label>
        <label class="f">Cura<input class="in" placeholder="es. solo a mano, non in asciugatrice" .value=${d.care_notes} @input=${(e: any) => this.set('care_notes', e.target.value)}></label>
        <label class="f">Note<textarea class="in" rows="2" .value=${d.notes} @input=${(e: any) => this.set('notes', e.target.value)}></textarea></label>
      ` : html`<button class="link small" style="align-self:flex-start" @click=${() => (this.more = true)}>Altri dettagli (occasioni, calore, materiali, acquisto, cura…)</button>`}
      <div class="row wrap">
        <hxk-button variant="primary" icon="check" @click=${() => this.emitSave(false)}>Salva</hxk-button>
        ${this.editing ? nothing : html`<hxk-button icon="plus" @click=${() => this.emitSave(true)}>Salva e aggiungi un altro</hxk-button>`}
        <hxk-button variant="ghost" @click=${() => this.dispatchEvent(new CustomEvent('cancel', { bubbles: true, composed: true }))}>Annulla</hxk-button>
        <span class="grow"></span>
        <label class="row small"><input type="checkbox" .checked=${d.favorite} @change=${(e: any) => this.set('favorite', e.target.checked)}> <hxk-icon name="star" size=${14} tone="warning"></hxk-icon> preferito</label>
      </div>
    </div>`;
  }
}
