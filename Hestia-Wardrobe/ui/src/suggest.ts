/**
 * <wardrobe-suggest> — «What do I wear»: occasion, temperature, rain, day → outfits from what is available, each with its
 * reasons; save one, mark it worn, ask the assistant. Deterministic engine in the module (no LLM).
 * Temperature and rain left empty = the day's forecast (shown above the ideas); typing one overrides it.
 */
import { css, html, nothing, plural, tr } from '@hestia/webui-sdk';
import { API, seasonIcon, WardrobeElement, call, dots, img, localDay, vocabOptions, wardrobeStyles } from './util';

export class WardrobeSuggest extends WardrobeElement {
  static properties = { ...WardrobeElement.properties, res: { state: true }, occasion: { state: true }, temp: { state: true }, rain: { state: true },
                        day: { state: true }, styleKey: { state: true }, busy: { state: true } };
  declare res: any; declare occasion: string; declare temp: string; declare rain: boolean | null; declare day: string; declare styleKey: string; declare busy: boolean;
  static styles = [...WardrobeElement.styles, wardrobeStyles, css`
    .opts { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
    .sug { display: flex; flex-direction: column; gap: 10px; }
    .pcs { display: grid; grid-template-columns: repeat(auto-fill, minmax(104px, 1fr)); gap: 8px; }
    .pcs .tile .ph { aspect-ratio: 1; }
    .pcs .lab { font-size: 10.5px; color: var(--text-3); text-transform: uppercase; letter-spacing: .04em; }
  `];
  constructor() { super(); this.res = undefined; this.occasion = ''; this.temp = ''; this.rain = null; this.day = ''; this.styleKey = ''; this.busy = false; }
  connectedCallback() {
    this.occasion = this.ctx?.query?.occasion || this.host?.config.get('lastOccasion', '') || '';
    super.connectedCallback();
  }
  protected async load() {
    this.busy = true;
    const body: any = { occasion: this.occasion };
    if (this.rain !== null) body.rain = this.rain;
    if (this.temp !== '') body.temp_c = Number(String(this.temp).replace(',', '.'));
    if (this.day) body.date = this.day;
    if (this.styleKey) body.styles = [this.styleKey];
    const r = await this.host.api('POST', `${API}/suggest`, { body });
    this.busy = false;
    this.res = r.ok ? r.data : this.res ?? null;
  }
  private setOcc(k: string) {
    this.occasion = this.occasion === k ? '' : k;
    this.host.config.set('lastOccasion', this.occasion);
    this.load();
  }
  private async save(s: any, worn: boolean) {
    let id = s.outfit_id;
    if (!id) {
      const r = await call(this.host, 'POST', '/suggest/save', { slots: s.slots, name: s.name });
      if (!r.ok) return;
      id = r.data.id;
      if (!worn) this.host.toast(tr('Outfit saved'), 'success', { label: tr('Open'), run: () => this.host.navigate('outfit/' + id) });
    }
    if (worn) {
      const r = await call(this.host, 'POST', `/outfits/${id}/worn`, this.day ? { date: this.day } : {});
      if (r.ok) this.host.toast(r.data.label || tr('Marked'), 'success', { label: tr('Cancel'), run: async () => { await call(this.host, 'DELETE', `/wears/${r.data.id}`); this.load(); } });
    }
    this.load();
  }
  render() {
    const m = this.m, res = this.res, w = res?.weather;
    const manual = this.temp !== '' || this.rain !== null;
    return html`<div class="page">
      <div class="head"><h1>${tr("What should I wear")}</h1>${res ? html`<span class="sub">${seasonIcon(res.season)} ${m?.seasons[res.season] || ''} · ${plural(res.available_pieces, 'garment', 'garments')} ${tr("available")}</span>` : nothing}
        <span class="grow"></span><hxk-button variant="ghost" icon="refresh" ?loading=${this.busy} @click=${() => this.load()}>${tr("More ideas")}</hxk-button></div>
      <div class="chips">${vocabOptions(m, 'occasion').map(o => html`<button class="chip" aria-pressed=${this.occasion === o.key} @click=${() => this.setOcc(o.key)}>${o.label}</button>`)}</div>
      <div class="opts">
        <label class="row small">${tr("Temperature")} <input class="in num" inputmode="decimal" placeholder=${w ? String(w.temp_c ?? '°C') : '°C'} .value=${this.temp} @change=${(e: any) => { this.temp = e.target.value; this.load(); }}> °C</label>
        <button class="chip soft" aria-pressed=${this.rain ?? !!w?.rain} @click=${() => { this.rain = !(this.rain ?? !!w?.rain); this.load(); }}><hxk-icon name="umbrella" size=${14} tone="info"></hxk-icon> ${tr("Rain")}</button>
        <select class="in" @change=${(e: any) => { this.styleKey = e.target.value; this.load(); }}><option value="">${tr("Any style")}</option>
          ${vocabOptions(m, 'style').map(s => html`<option value=${s.key} ?selected=${this.styleKey === s.key}>${s.label}</option>`)}</select>
        <label class="row small">${tr("Day")} <input class="in" type="date" min=${localDay()} .value=${this.day || localDay()} @change=${(e: any) => { this.day = e.target.value === localDay() ? '' : e.target.value; this.load(); }}></label>
      </div>
      ${w ? html`<div class="row small muted"><hxk-icon name=${w.icon || 'cloud'} size=${15} tone=${w.rain ? 'info' : 'warning'}></hxk-icon>
          ${tr("Forecast")} ${w.place ? `${w.place}: ` : ''}${w.min_c != null ? `${w.min_c}–` : ''}${w.temp_c}°${w.condition ? `, ${w.condition}` : ''}
          ${manual ? html`<hxk-button size="sm" variant="ghost" @click=${() => { this.temp = ''; this.rain = null; this.load(); }}>${tr("Use the forecast")}</hxk-button>` : nothing}</div>` : nothing}
      ${res === undefined ? html`<hxk-state kind="loading"></hxk-state>` : res === null ? html`<hxk-state kind="error" text=${tr("Suggestions not available right now.")}></hxk-state>`
        : !res.items.length ? html`<hxk-state kind="empty" text=${res.hint || tr('No proposals.')}></hxk-state>` : html`
        <div class="grid" style="--min:300px">${res.items.map((s: any, i: number) => html`<div class="card sug">
          <div class="between"><h2 class="truncate">${s.saved ? s.name : tr("Idea {0}", i + 1)}</h2>${s.saved ? html`<hxk-badge tone="accent">${tr("saved")}</hxk-badge>` : nothing}</div>
          <div class="pcs">${s.pieces.map((p: any) => html`<div class="tile" @click=${() => this.host.navigate('items/' + p.id)}>
            <div class="ph">${img(this.host, p.photo, p.name)}</div><div class="tx"><span class="lab">${m?.slots[p.slot] || p.slot}</span><span class="nm">${p.name}</span>${dots(p.colors, 9)}</div></div>`)}</div>
          <div class="reasons">${s.reasons.map((r: string) => html`<span class="pill">${r}</span>`)}</div>
          <div class="row wrap"><hxk-button variant="primary" size="sm" icon="check" @click=${() => this.save(s, true)}>${this.day ? tr('Mark for that day') : tr('I\'m wearing this')}</hxk-button>
            ${s.saved ? html`<hxk-button size="sm" variant="ghost" @click=${() => this.host.navigate('outfit/' + s.outfit_id)}>${tr("Open")}</hxk-button>`
              : html`<hxk-button size="sm" icon="plus" @click=${() => this.save(s, false)}>${tr("Save outfit")}</hxk-button>`}
            <span class="grow"></span>
            <hxk-button size="sm" variant="ghost" icon="sparkle" title=${tr("Ask the assistant")} @click=${() => this.host.assistant({ label: tr('What should I wear'), hints: { pieces: s.pieces.map((p: any) => p.id).join(',') },
              prompt: tr("You propose this: {0}. Is it ok{1}?", s.pieces.map((p: any) => p.name).join(', '), this.occasion ? ' per ' + (vocabOptions(m, 'occasion').find(o => o.key === this.occasion)?.label || this.occasion).toLowerCase() : '') })}></hxk-button></div>
        </div>`)}</div>`}
    </div>`;
  }
}
