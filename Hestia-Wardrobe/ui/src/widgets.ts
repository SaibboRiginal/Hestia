/** Wardrobe widgets for Home and dashboards: one-tap «Indossato», today's idea, laundry, forgotten, numbers, recent. */
import { css, html, nothing, plural, tr } from '@hestia/webui-sdk';
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
      ${g ? html`<div class="between"><span class="small muted">${g.hint}${g.met ? html` <hxk-icon name="check" size=${12} tone="success"></hxk-icon>` : ''}</span>${g.behind ? html`<hxk-badge tone="warning">${tr("behind")}</hxk-badge>` : nothing}</div>` : nothing}
      <hxk-quicklog .host=${this.host} ?compact=${this.size === 's'} source=${`${API}/quick/outfits`} .action=${action}
        @logged=${() => this.reload(true)}></hxk-quicklog>
      <div class="row small"><button class="link" @click=${() => this.host.navigate('outfit')}>${tr("All outfits")}</button><span class="grow"></span>
        <button class="link" @click=${() => this.host.navigate('what-to-wear', this.ctx?.params?.occasion ? { occasione: this.ctx.params.occasion } : undefined)}>${tr("What do I wear?")}</button></div>
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
    if (r.ok) this.host.toast(r.data.label || tr('Marked'), 'success', { label: tr('Cancel'), run: () => call(this.host, 'DELETE', `/wears/${r.data.id}`) });
  }
  render() {
    const res = this.res;
    if (res === undefined) return html`<hxk-state kind="loading"></hxk-state>`;
    const s = res?.items?.[0];
    if (!s) return html`<div class="w"><span class="muted small">${res?.hint || tr('No idea for now.')}</span>
      <div><hxk-button size="sm" icon="plus" @click=${() => this.host.navigate('items', { nuovo: '1' })}>${tr("Add items")}</hxk-button></div></div>`;
    return html`<div class="w">
      <div class="click" @click=${() => this.host.navigate('what-to-wear')}><b class="truncate">${s.saved ? s.name : tr('Idea for today')}</b>
        <div class="strip" style="margin-top:6px">${s.pieces.slice(0, this.size === 'l' ? 7 : 4).map((p: any) => html`<span class="thumb" title=${p.name}>${img(this.host, p.photo, p.name)}</span>`)}</div></div>
      <div class="reasons">${s.reasons.slice(0, this.size === 'l' ? 4 : 2).map((r: string) => html`<span class="pill">${r}</span>`)}</div>
      <div class="row"><hxk-button size="sm" variant="primary" icon="check" @click=${() => this.wear(s)}>${tr("I'm wearing this")}</hxk-button>
        <hxk-button size="sm" variant="ghost" icon="refresh" @click=${() => this.host.navigate('what-to-wear')}>${tr("Others")}</hxk-button></div>
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
    if (r.ok) { this.host.toast(tr("«{0}» back in the wardrobe", p.name), 'success', { label: tr('Cancel'), run: async () => { await call(this.host, 'PATCH', `/pieces/${p.id}`, { status: 'laundry' }); this.load(); } }); this.load(); }
  }
  render() {
    const items = this.items;
    if (items === undefined) return html`<hxk-state kind="loading"></hxk-state>`;
    if (this.size === 's') return html`<div class="w click" @click=${() => this.host.navigate('items', { status: 'laundry' })}>
      <span class="small muted">${tr("In the laundry")}</span><div class="big">${items.length}</div><span class="small muted">${items.length ? tr('garments') : html`<hxk-icon name="check" size=${12} tone="success"></hxk-icon> ${tr("all clean")}`}</span></div>`;
    return html`<div class="w">${items.length ? html`<div class="list">${items.slice(0, 6).map(p => html`<div class="li" style="cursor:default">
        <span class="thumb">${img(this.host, p.photos?.[0], p.name)}</span><span class="grow truncate">${p.name}</span>
        <hxk-button size="sm" @click=${() => this.clean(p)}>${tr("Clean")}</hxk-button></div>`)}</div>
        ${items.length > 6 ? html`<button class="link small" @click=${() => this.host.navigate('items', { status: 'laundry' })}>${tr("pl::Others")} ${items.length - 6}</button>` : nothing}`
      : html`<span class="muted"><hxk-icon name="check" size=${14} tone="success"></hxk-icon> ${tr("Nothing in the laundry")}</span>`}</div>`;
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
    if (!items.length) return html`<div class="w"><span class="muted">${tr("No forgotten item.")}</span></div>`;
    return html`<div class="w">
      <span class="small muted">${plural(items.length, 'garment', 'garments')} ${tr("not worn for a long time: wear them again or consider giving them away.")}</span>
      <div class="list">${items.slice(0, this.size === 'l' ? 6 : 3).map(f => html`<div class="li" @click=${() => this.host.navigate('items/' + f.id)}>
        <span class="thumb">${img(this.host, f.photo, f.name)}</span><span class="grow truncate">${f.name}</span><span class="small muted">${f.last_worn ? relDays(f.last_worn) : tr('never')}</span></div>`)}</div>
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
    if (!s) return html`<hxk-state kind="error" text=${tr("Unavailable")}></hxk-state>`;
    const t = s.totals;
    if (this.size === 's') return html`<div class="w click" @click=${() => this.host.navigate('statistics')}>
      <span class="small muted">${tr("Wardrobe")}</span><div class="big">${t.pieces}</div><span class="small muted">${t.outfits} ${"outfit"}${s.laundry?.length ? tr(" · {0} in the laundry", s.laundry.length) : ''}</span></div>`;
    return html`<div class="w click" @click=${() => this.host.navigate('statistics')}>
      <hxk-stat .items=${[{ label: tr('Items'), value: t.garments }, { label: tr('Shoes'), value: t.shoes }, { label: tr('Accessories'), value: t.accessories }, { label: tr('Outfit'), value: t.outfits }]}></hxk-stat>
      ${s.gaps?.length ? html`<span class="small muted truncate">${tr("Missing: {0}", s.gaps[0].toLowerCase())}</span>` : nothing}</div>`;
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
    if (!items.length) return html`<div class="w"><span class="muted small">${tr("No outfit noted: it's done from Home with one tap, whenever you want.")}</span></div>`;
    return html`<div class="w"><div class="list">${items.slice(0, this.size === 'l' ? 8 : 4).map(w => {
      const o = w.outfit_id ? this.outfits?.get(w.outfit_id) : null;
      return html`<div class="li" @click=${() => this.host.navigate(o ? 'outfit/' + o.id : 'capi/' + w.pieces?.[0]?.id)}>
        <span class="thumb">${o ? collage(this.host, o) : img(this.host, w.pieces?.[0]?.photo, '')}</span>
        <span class="grow truncate">${w.outfit_name || w.pieces.map((p: any) => p.name).join(' + ')}</span><span class="small muted">${dayLabel(w.date)}</span></div>`; })}</div></div>`;
  }
}
