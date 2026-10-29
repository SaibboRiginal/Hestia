/**
 * <wardrobe-stats> — composition (category, colour, season, style), value, forgotten pieces, gaps; usage numbers only
 * as hints because «Indossato» is occasional (SPEC §4.3), with the optional goal on top.
 */
import { css, html, nothing, plural } from '@hestia/webui-sdk';
import { API, WardrobeElement, img, money, relDays, wardrobeStyles } from './util';

export class WardrobeStats extends WardrobeElement {
  static properties = { ...WardrobeElement.properties, s: { state: true } };
  declare s: any;
  static styles = [...WardrobeElement.styles, wardrobeStyles, css`
    .bars { display: flex; flex-direction: column; gap: 6px; }
    .b { display: grid; grid-template-columns: 120px 1fr 34px; gap: 8px; align-items: center; font-size: 13px; }
    .b .tr { height: 10px; border-radius: 6px; background: var(--surface-3); overflow: hidden; }
    .b .fl { height: 100%; border-radius: 6px; background: var(--accent); }
    .b .n { text-align: right; color: var(--text-2); font-variant-numeric: tabular-nums; }
  `];
  constructor() { super(); this.s = undefined; }
  protected async load() {
    const r = await this.host.api('GET', `${API}/stats`);
    this.s = r.ok ? r.data : this.s ?? null;
  }
  private bars(rows: any[], color = false) {
    const max = Math.max(1, ...rows.map(r => r.count));
    return html`<div class="bars">${rows.filter(r => r.count).map(r => html`<div class="b"><span class="truncate">${r.label}</span>
      <span class="tr"><span class="fl" style="display:block;width:${(r.count / max) * 100}%;${color && r.hex ? `background:${r.hex}` : ''}"></span></span>
      <span class="n">${r.count}</span></div>`)}</div>`;
  }
  render() {
    const s = this.s, g = this.m?.goal;
    if (s === undefined) return html`<div class="page"><hxk-state kind="loading"></hxk-state></div>`;
    if (s === null) return html`<div class="page"><hxk-state kind="error" text="Statistiche non disponibili ora."></hxk-state></div>`;
    const t = s.totals, u = s.usage;
    return html`<div class="page">
      <div class="head"><h1>Statistiche</h1><span class="grow"></span>
        <hxk-button variant="ghost" icon="sparkle" @click=${() => this.host.assistant({ label: 'Guardaroba', prompt: 'Guarda il mio guardaroba: cosa mi manca e cosa potrei dare via?' })}>Chiedi un parere</hxk-button></div>
      <hxk-stat .items=${s.kpi.items}></hxk-stat>
      ${g ? html`<div class="card between"><div><h3>Obiettivo «Indossato»</h3><div class="big">${g.done}<span class="muted" style="font-size:15px"> / ${g.times}</span></div>
          <div class="small muted">${g.hint}${g.met ? html` · <hxk-icon name="check" size=${12} tone="success"></hxk-icon> fatto` : g.behind ? ' · un po\' indietro' : ''}</div></div>
          <hxk-button icon="check" @click=${() => this.host.navigate('outfit')}>Segna un outfit</hxk-button></div>` : nothing}
      <div class="grid" style="--min:300px">
        <div class="card col"><h3>Per categoria</h3>${this.bars(s.by_category)}</div>
        <div class="card col"><h3>Colori principali</h3>${this.bars(s.by_color, true)}</div>
        <div class="card col"><h3>Stagioni</h3>${this.bars(s.by_season)}<span class="small muted">Un capo può valere per più stagioni.</span></div>
        ${s.by_style.length ? html`<div class="card col"><h3>Stile</h3>${this.bars(s.by_style.map((x: any) => ({ ...x, label: this.m?.vocabularies?.style?.find(v => v.key === x.key)?.label || x.label })))}</div>` : nothing}
      </div>
      ${s.gaps.length ? html`<div class="card col"><h3>Cosa manca</h3>${s.gaps.map((x: string) => html`<div class="row"><hxk-icon name="pin" size="14"></hxk-icon>${x}</div>`)}</div>` : nothing}
      <div class="card col"><div class="between"><h3>Dimenticati</h3><span class="small muted">${plural(s.forgotten.length, 'capo', 'capi')}</span></div>
        ${s.forgotten.length ? html`<div class="list">${s.forgotten.slice(0, 30).map((f: any) => html`<div class="li" @click=${() => this.host.navigate('capi/' + f.id)}>
            <span class="thumb">${img(this.host, f.photo, f.name)}</span><span class="grow truncate">${f.name}</span>
            <span class="small muted">${f.last_worn ? relDays(f.last_worn) : 'mai segnato'}</span></div>`)}</div>`
          : html`<div class="empty">Niente di dimenticato.</div>`}</div>
      <div class="card col"><h3>Uso (indicativo)</h3>
        ${!u.has_marks ? html`<div class="empty">Segni «Indossato» solo quando vuoi: con qualche segno qui compaiono i capi più usati e il costo per utilizzo.</div>` : html`
          ${u.per_month.values.some((v: number) => v) ? html`<hxk-chart type="bar" .labels=${u.per_month.labels.map((l: string) => l.slice(5) + '/' + l.slice(2, 4))} .series=${[{ name: 'Segni', values: u.per_month.values }]} height="140"></hxk-chart>` : nothing}
          <div class="grid" style="--min:260px">
            <div class="col"><span class="small muted">Più messi</span>${u.most_worn.map((p: any) => html`<div class="li" @click=${() => this.host.navigate('capi/' + p.id)}><span class="grow truncate">${p.name}</span><span class="small muted">${p.wears}×</span></div>`)}</div>
            ${u.cost_per_wear.length ? html`<div class="col"><span class="small muted">Costo per utilizzo</span>${u.cost_per_wear.map((p: any) => html`<div class="li" @click=${() => this.host.navigate('capi/' + p.id)}>
              <span class="grow truncate">${p.name}</span><span class="small muted">${money(p.cost_per_wear, t.currency)} · ${p.wears}×</span></div>`)}</div>` : nothing}
          </div>
          <span class="small muted">${plural(u.never_marked, 'capo', 'capi')} mai segnati: normale se non segni ogni giorno.</span>`}
      </div>
      <div class="row small muted"><span>${t.wishlist ? `${t.wishlist} desiderati · ` : ''}${t.marks} segni in tutto</span><span class="grow"></span>
        <button class="link" @click=${async () => { const r = await this.host.api('GET', `${API}/export`); if (r.ok) { const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([r.data.text], { type: 'application/json' })); a.download = r.data.filename; a.click(); } }}>Esporta JSON</button></div>
    </div>`;
  }
}
