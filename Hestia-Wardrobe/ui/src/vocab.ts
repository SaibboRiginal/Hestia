/**
 * <wardrobe-vocab> — the user's own lists (categories, styles, occasions, colours, patterns, fits, places):
 * rename, hide, reorder, add. Keys stay stable so pieces never lose their values.
 */
import { css, html, nothing, tr } from '@hestia/webui-sdk';
import { WardrobeElement, call, meta, wardrobeStyles } from './util';

const NAMES: Record<string, string> = { category: tr('Categories'), style: tr('Styles'), occasion: tr('Occasions'), color: tr('Colours'), pattern: tr('Patterns'), fit: tr('Fit'), location: tr('Places') };

export class WardrobeVocab extends WardrobeElement {
  static properties = { ...WardrobeElement.properties, tab: { state: true }, rows: { state: true }, dirty: { state: true }, busy: { state: true } };
  declare tab: string; declare rows: any[]; declare dirty: boolean; declare busy: boolean;
  static styles = [...WardrobeElement.styles, wardrobeStyles, css`
    .r { display: flex; align-items: center; gap: 8px; padding: 5px 0; border-bottom: 1px solid var(--border); }
    .r.sub { padding-left: 26px; } .r.hidden input.in { opacity: .5; }
    .r input.lab { flex: 1; min-width: 0; }
    input[type=color] { width: 32px; height: 28px; border: none; background: none; padding: 0; cursor: pointer; }
  `];
  constructor() { super(); this.tab = 'category'; this.rows = []; this.dirty = false; this.busy = false; }
  protected async load() { if (!this.dirty) this.rows = (this.m?.vocabularies?.[this.tab] || []).map(v => ({ ...v })); }
  private async setTab(t: string) {
    if (this.dirty && !(await this.host.confirm(tr('Unsaved changes'), tr('Changing list you lose them.'), { label: tr('Change list') }))) return;
    this.tab = t; this.dirty = false; this.load();
  }
  private edit(i: number, k: string, v: any) { this.rows = this.rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)); this.dirty = true; }
  private move(i: number, d: number) {
    const j = i + d;
    if (j < 0 || j >= this.rows.length) return;
    const rows = [...this.rows];
    [rows[i], rows[j]] = [rows[j], rows[i]];
    this.rows = rows; this.dirty = true;
  }
  private add(parent = '') {
    const base: any = { key: '', label: '', hidden: false };
    if (this.tab === 'category') {
      const p = this.rows.find(r => r.key === parent);
      Object.assign(base, { parent, kind: p?.kind || 'garment', slot: p?.slot || 'top' });
    }
    if (this.tab === 'color') base.hex = '#888888';
    const at = parent ? this.rows.findIndex(r => r.key === parent) + 1 + this.rows.filter(r => r.parent === parent).length : this.rows.length;
    const rows = [...this.rows]; rows.splice(at, 0, base); this.rows = rows; this.dirty = true;
  }
  private async save() {
    this.busy = true;
    const values = this.rows.filter(r => (r.label || '').trim()).map((r, i) => ({ ...r, order: i }));
    const r = await call(this.host, 'PUT', `/vocabularies/${this.tab}`, { values });
    this.busy = false;
    if (r.ok) { this.dirty = false; this.m = await meta(this.host, true); this.load(); this.host.toast(tr('Saved'), 'success'); }
  }
  render() {
    const m = this.m;
    const rows = this.rows;
    const isCat = this.tab === 'category';
    return html`<div class="page">
      <div class="head"><h1>${tr("Vocabularies")}</h1><span class="sub">${tr("Your lists: rename, hide or add items.")}</span></div>
      <div class="tabs">${Object.entries(NAMES).map(([k, v]) => html`<button class="chip soft" aria-pressed=${this.tab === k} @click=${() => this.setTab(k)}>${v}</button>`)}</div>
      <div class="card col">
        ${rows.map((r, i) => html`<div class="r ${isCat && r.parent ? 'sub' : ''} ${r.hidden ? 'hidden' : ''}">
          ${this.tab === 'color' ? html`<input type="color" .value=${r.hex || '#888888'} @input=${(e: any) => this.edit(i, 'hex', e.target.value)}>` : nothing}
          <input class="in lab" placeholder=${tr("Name")} .value=${r.label} @input=${(e: any) => this.edit(i, 'label', e.target.value)}>
          ${isCat && !r.parent ? html`<select class="in" @change=${(e: any) => this.edit(i, 'kind', e.target.value)}>${Object.entries(m?.kinds || {}).map(([k, v]) => html`<option value=${k} ?selected=${r.kind === k}>${v}</option>`)}</select>` : nothing}
          ${isCat ? html`<select class="in" title=${tr("Position in the outfit")} @change=${(e: any) => this.edit(i, 'slot', e.target.value)}>${Object.entries(m?.slots || {}).map(([k, v]) => html`<option value=${k} ?selected=${r.slot === k}>${v}</option>`)}</select>` : nothing}
          <hxk-button size="sm" variant="ghost" title="Su" @click=${() => this.move(i, -1)}>↑</hxk-button>
          <hxk-button size="sm" variant="ghost" title=${r.hidden ? tr('Show') : tr('Hide')} @click=${() => this.edit(i, 'hidden', !r.hidden)}>${r.hidden ? tr('Show') : tr('Hide')}</hxk-button>
          ${isCat && !r.parent ? html`<hxk-button size="sm" variant="ghost" icon="plus" title=${tr("Subcategory")} @click=${() => this.add(r.key)}></hxk-button>` : nothing}
          ${!r.key ? html`<hxk-button size="sm" variant="ghost" icon="x" @click=${() => { this.rows = rows.filter((_, j) => j !== i); }}></hxk-button>` : nothing}
        </div>`)}
        <div class="row"><hxk-button size="sm" icon="plus" @click=${() => this.add()}>${tr("Add")}</hxk-button><span class="grow"></span>
          ${this.dirty ? html`<hxk-button size="sm" variant="ghost" @click=${() => { this.dirty = false; this.load(); }}>${tr("Cancel")}</hxk-button>` : nothing}
          <hxk-button size="sm" variant="primary" ?disabled=${!this.dirty} ?loading=${this.busy} @click=${() => this.save()}>${tr("Save")}</hxk-button></div>
        <span class="small muted">${tr("Items used by clothes can't be removed: hide them.")}${isCat ? tr(' The position says where the item goes in an outfit (top, bottom, outerwear…).') : ''}</span>
      </div>
      <span class="small muted">${tr("Export / import the whole wardrobe:")} <button class="link" @click=${() => this.host.navigate('statistics')}>${tr("Statistics")}</button>${' · '}
        <button class="link" @click=${() => this.importFile()}>${tr("Import JSON")}</button></span>
    </div>`;
  }
  private async importFile() {
    const input = document.createElement('input');
    input.type = 'file'; input.accept = 'application/json,.json';
    input.onchange = async () => {
      const f = input.files?.[0]; if (!f) return;
      if (!(await this.host.confirm(tr('Import'), tr("I'm merging «{0}» into the wardrobe (same ids = replaced).", f.name), { label: tr('Import') }))) return;
      const r = await call(this.host, 'POST', '/import', { text: await f.text() });
      if (r.ok) { this.host.toast(tr('Imported'), 'success'); this.m = await meta(this.host, true); this.load(); }
    };
    input.click();
  }
}

