/** Wardrobe widgets for Home and dashboards: one-tap «Indossato», today's idea, laundry, forgotten, numbers, recent. */
import { css, html, nothing } from '@hestia/webui-sdk';
import type { QuickAction } from '@hestia/webui-sdk';
import { API, WardrobeElement, call, dayLabel, img, relDays, wardrobeStyles } from './util';
import { collage } from './outfits';

abstract class Widget extends WardrobeElement {
  static styles = [...WardrobeElement.styles, wardrobeStyles, css`
    :host { display: block; height: 100%; }
    .w { display: flex; flex-direction: column; gap: 8px; height: 100%; padding: 2px; min-width: 0; }
    .click { cursor: pointer; }
    .strip { display: flex; gap: 6px; overflow: hidden; }
    .strip .thumb { width: 52px; height: 52px; }
  `];
  protected get size() { return this.ctx?.size || 'm'; }
}

/** «Oggi indosso»: favourite outfits + today's suggestion as chips (tap = Indossato, toast with Annulla). */
export class WardrobeTodayWidget extends Widget {
  static properties = { ...WardrobeElement.properties, goal: { state: true } };
  declare goal: any;
  protected async load() { this.goal = this.m?.goal || null; }
  render() {
    const action: QuickAction = { method: 'POST', path: `${API}/quick/{id}`, undo: { method: 'DELETE', path: `${API}/quick/{id}` } };
    const g = this.goal;
    return html`<div class="w">
      ${g ? html`<div class="between"><span class="small muted">${g.hint}${g.met ? ' ✓' : ''}</span>${g.behind ? html`<hxk-badge tone="warning">indietro</hxk-badge>` : nothing}</div>` : nothing}
      <hxk-quicklog .host=${this.host} ?compact=${this.size === 's'} source=${`${API}/quick/outfits`} .action=${action}
        @logged=${() => this.reload(true)}></hxk-quicklog>
      <div class="row small"><button class="link" @click=${() => this.host.navigate('outfit')}>Tutti gli outfit</button><span class="grow"></span>
        <button class="link" @click=${() => this.host.navigate('cosa-mi-metto', this.ctx?.params?.occasion ? { occasione: this.ctx.params.occasion } : undefined)}>Cosa mi metto?</button></div>
    </div>`;
  }
}

/** Today's best idea with its pieces and reasons. */
export class WardrobeSuggestWidget extends Widget {
  static properties = { ...WardrobeElement.properties, res: { state: true } };
  declare res: any;
  protected async load() {
    const r = await this.host.api('POST', `${API}/suggest`, { body: { occasion: this.ctx?.params?.occasion || '', count: 1 } });
    this.res = r.ok ? r.data : this.res ?? null;
  }
  private async wear(s: any) {
    let id = s.outfit_id;
    if (!id) { const r = await call(this.host, 'POST', '/suggest/save', { slots: s.slots, name: s.name }); if (!r.ok) return; id = r.data.id; }
    const r = await call(this.host, 'POST', `/outfits/${id}/worn`, {});
    if (r.ok) this.host.toast(r.data.label || 'Segnato', 'success', { label: 'Annulla', run: () => call(this.host, 'DELETE', `/wears/${r.data.id}`) });
  }
  render() {
    const res = this.res;
    if (res === undefined) return html`<hxk-state kind="loading"></hxk-state>`;
    const s = res?.items?.[0];
    if (!s) return html`<div class="w"><span class="muted small">${res?.hint || 'Nessuna idea per ora.'}</span>
      <div><hxk-button size="sm" icon="plus" @click=${() => this.host.navigate('capi', { nuovo: '1' })}>Aggiungi capi</hxk-button></div></div>`;
    return html`<div class="w">
      <div class="click" @click=${() => this.host.navigate('cosa-mi-metto')}><b class="truncate">${s.saved ? s.name : 'Idea per oggi'}</b>
        <div class="strip" style="margin-top:6px">${s.pieces.slice(0, this.size === 'l' ? 7 : 4).map((p: any) => html`<span class="thumb" title=${p.name}>${img(this.host, p.photo, p.name)}</span>`)}</div></div>
      <div class="reasons">${s.reasons.slice(0, this.size === 'l' ? 4 : 2).map((r: string) => html`<span class="pill">${r}</span>`)}</div>
      <div class="row"><hxk-button size="sm" variant="primary" icon="check" @click=${() => this.wear(s)}>Indosso questo</hxk-button>
        <hxk-button size="sm" variant="ghost" icon="refresh" @click=${() => this.host.navigate('cosa-mi-metto')}>Altre</hxk-button></div>
    </div>`;
  }
}

/** Pieces in the laundry: tap «Pulito» to put one back in the wardrobe. */
export class WardrobeLaundryWidget extends Widget {
  static properties = { ...WardrobeElement.properties, items: { state: true } };
  declare items: any[] | undefined;
  protected async load() {
    const r = await this.host.api('GET', `${API}/pieces`, { query: { status: 'laundry', kind: '', limit: 50 } });
    this.items = r.ok ? r.data.items : this.items ?? [];
  }
  private async clean(p: any) {
    const r = await call(this.host, 'PATCH', `/pieces/${p.id}`, { status: 'active' });
    if (r.ok) { this.host.toast(`«${p.name}» di nuovo nell'armadio`, 'success', { label: 'Annulla', run: async () => { await call(this.host, 'PATCH', `/pieces/${p.id}`, { status: 'laundry' }); this.load(); } }); this.load(); }
  }
  render() {
    const items = this.items;
    if (items === undefined) return html`<hxk-state kind="loading"></hxk-state>`;
    if (this.size === 's') return html`<div class="w click" @click=${() => this.host.navigate('capi', { status: 'laundry' })}>
      <span class="small muted">In lavanderia</span><div class="big">${items.length}</div><span class="small muted">${items.length ? 'capi' : 'tutto pulito ✓'}</span></div>`;
    return html`<div class="w">${items.length ? html`<div class="list">${items.slice(0, 6).map(p => html`<div class="li" style="cursor:default">
        <span class="thumb">${img(this.host, p.photos?.[0], p.name)}</span><span class="grow truncate">${p.name}</span>
        <hxk-button size="sm" @click=${() => this.clean(p)}>Pulito</hxk-button></div>`)}</div>
        ${items.length > 6 ? html`<button class="link small" @click=${() => this.host.navigate('capi', { status: 'laundry' })}>Altri ${items.length - 6}</button>` : nothing}`
      : html`<span class="muted">Niente in lavanderia ✓</span>`}</div>`;
  }
}

/** Pieces not worn for a long time (the threshold is a setting). */
export class WardrobeForgottenWidget extends Widget {
  static properties = { ...WardrobeElement.properties, items: { state: true } };
  declare items: any[] | undefined;
  protected async load() {
    const r = await this.host.api('GET', `${API}/stats`);
    this.items = r.ok ? r.data.forgotten : this.items ?? [];
  }
  render() {
    const items = this.items;
    if (items === undefined) return html`<hxk-state kind="loading"></hxk-state>`;
    if (!items.length) return html`<div class="w"><span class="muted">Nessun capo dimenticato.</span></div>`;
    return html`<div class="w">
      <span class="small muted">${items.length} capi non messi da tanto: rimettili in giro o valuta di darli via.</span>
      <div class="list">${items.slice(0, this.size === 'l' ? 6 : 3).map(f => html`<div class="li" @click=${() => this.host.navigate('capi/' + f.id)}>
        <span class="thumb">${img(this.host, f.photo, f.name)}</span><span class="grow truncate">${f.name}</span><span class="small muted">${f.last_worn ? relDays(f.last_worn) : 'mai'}</span></div>`)}</div>
    </div>`;
  }
}

/** The wardrobe in numbers. */
export class WardrobeKpiWidget extends Widget {
  static properties = { ...WardrobeElement.properties, s: { state: true } };
  declare s: any;
  protected async load() {
    const r = await this.host.api('GET', `${API}/summary`);
    this.s = r.ok ? r.data : this.s ?? null;
  }
  render() {
    const s = this.s;
    if (s === undefined) return html`<hxk-state kind="loading"></hxk-state>`;
    if (!s) return html`<hxk-state kind="error" text="Non disponibile"></hxk-state>`;
    const t = s.totals;
    if (this.size === 's') return html`<div class="w click" @click=${() => this.host.navigate('statistiche')}>
      <span class="small muted">Guardaroba</span><div class="big">${t.pieces}</div><span class="small muted">${t.outfits} outfit${s.laundry?.length ? ` · ${s.laundry.length} in lavanderia` : ''}</span></div>`;
    return html`<div class="w click" @click=${() => this.host.navigate('statistiche')}>
      <hxk-stat .items=${[{ label: 'Capi', value: t.garments }, { label: 'Scarpe', value: t.shoes }, { label: 'Accessori', value: t.accessories }, { label: 'Outfit', value: t.outfits }]}></hxk-stat>
      ${s.gaps?.length ? html`<span class="small muted truncate">Manca: ${s.gaps[0].toLowerCase()}</span>` : nothing}</div>`;
  }
}

/** Last outfits marked worn. */
export class WardrobeRecentWidget extends Widget {
  static properties = { ...WardrobeElement.properties, items: { state: true }, outfits: { state: true } };
  declare items: any[] | undefined; declare outfits: Map<string, any>;
  protected async load() {
    const [w, o] = await Promise.all([this.host.api('GET', `${API}/wears`, { query: { limit: 8 } }), this.host.api('GET', `${API}/outfits`, { query: { sort: 'least_recent', limit: 400 } })]);
    this.items = w.ok ? w.data.items : this.items ?? [];
    if (o.ok) this.outfits = new Map(o.data.items.map((x: any) => [x.id, x]));
  }
  render() {
    const items = this.items;
    if (items === undefined) return html`<hxk-state kind="loading"></hxk-state>`;
    if (!items.length) return html`<div class="w"><span class="muted small">Nessun outfit segnato: si fa dalla Home con un tocco, quando vuoi.</span></div>`;
    return html`<div class="w"><div class="list">${items.slice(0, this.size === 'l' ? 8 : 4).map(w => {
      const o = w.outfit_id ? this.outfits?.get(w.outfit_id) : null;
      return html`<div class="li" @click=${() => this.host.navigate(o ? 'outfit/' + o.id : 'capi/' + w.pieces?.[0]?.id)}>
        <span class="thumb">${o ? collage(this.host, o) : img(this.host, w.pieces?.[0]?.photo, '')}</span>
        <span class="grow truncate">${w.outfit_name || w.pieces.map((p: any) => p.name).join(' + ')}</span><span class="small muted">${dayLabel(w.date)}</span></div>`; })}</div></div>`;
  }
}
