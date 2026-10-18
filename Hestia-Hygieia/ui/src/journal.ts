/**
 * <hygieia-journal> — diary per body area, used only when wanted:
 * quick 1–5 scores, tags and a note; trends per metric with the routine/product changes around them.
 */
import { HestiaElement, html, css, nothing } from '@hestia/webui-sdk';
import { API, AREA_EMOJI, call, dayLabel, hygieiaStyles, label, meta, today } from './util';

export class HygieiaJournal extends HestiaElement {
  static properties = { ...HestiaElement.properties, m: { state: true }, data: { state: true }, area: { state: true },
    scores: { state: true }, tags: { state: true }, note: { state: true }, date: { state: true }, saving: { state: true } };
  declare m: any;
  declare data: any;
  declare area: string;
  declare scores: Record<string, number>;
  declare tags: string[];
  declare note: string;
  declare date: string;
  declare saving: boolean;
  static styles = [...HestiaElement.styles, hygieiaStyles, css`
    .metric { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
    .metric .lab { min-width: 110px; }
    .dots { display: flex; gap: 4px; }
    .dot { width: 36px; height: 36px; border-radius: 50%; border: 1px solid var(--border-strong); background: var(--surface); cursor: pointer; font: inherit; color: var(--text-2); }
    .dot[aria-pressed=true] { background: var(--accent); border-color: var(--accent); color: var(--accent-contrast); font-weight: 600; }
    .entry { display: flex; gap: 10px; padding: 8px 0; border-bottom: 1px solid var(--border); font-size: 13px; }
    .entry:last-child { border-bottom: none; }
  `];
  constructor() { super(); this.m = null; this.data = undefined; this.area = 'viso'; this.scores = {}; this.tags = []; this.note = ''; this.date = today(); this.saving = false; }
  connectedCallback() { super.connectedCallback(); this.load(); this.onHost('refresh', () => this.load()); }
  private async load() {
    this.m = await meta(this.host);
    const r = await this.host.api('GET', `${API}/journal`, { query: { area: this.area } });
    this.data = r.ok ? r.data : null;
  }
  private metrics(): any[] { return this.m?.metrics?.[this.area] || this.m?.metrics?.['*'] || []; }
  private async save() {
    this.saving = true;
    const r = await call(this.host, 'POST', `${API}/journal`, { body: { date: this.date, entries: [{ area: this.area, scores: this.scores, tags: this.tags, note: this.note }] } });
    this.saving = false;
    if (r.ok) { this.host.toast('Annotato nel diario', 'success'); this.scores = {}; this.tags = []; this.note = ''; this.load(); }
  }
  private async drop(id: string) { await call(this.host, 'DELETE', `${API}/journal/${id}`); this.load(); }
  render() {
    const back = html`<button class="link" @click=${() => this.host.navigate('oggi')}>‹ Oggi</button>`;
    if (!this.m) return html`<div class="page">${back}<hxk-state kind="loading"></hxk-state></div>`;
    const ms = this.metrics(), series = this.data?.series?.[this.area] || {};
    return html`<div class="page">
      ${back}
      <div class="head"><h1>Diario</h1></div>
      <div class="chips">${(this.m.areas || []).map((a: any) => html`<button class="chip" aria-pressed=${this.area === a.value}
        @click=${() => { this.area = a.value; this.scores = {}; this.data = undefined; this.load(); }}>${AREA_EMOJI[a.value] || ''} ${a.label}</button>`)}</div>
      <div class="card col">
        <div class="between"><h2>Com'è oggi</h2><input class="in" type="date" .value=${this.date} max=${today()} @change=${(e: any) => (this.date = e.target.value)}></div>
        ${ms.map(mt => html`<div class="metric"><span class="lab">${mt.label}${mt.lower_better ? html`<span class="small muted"> (1 = poco)</span>` : nothing}</span>
          <div class="dots">${[1, 2, 3, 4, 5].map(n => html`<button class="dot" aria-pressed=${this.scores[mt.value] === n}
            @click=${() => { const s = { ...this.scores }; s[mt.value] === n ? delete s[mt.value] : (s[mt.value] = n); this.scores = s; }}>${n}</button>`)}</div></div>`)}
        <div class="chips">${(this.m.tags || []).map((t: any) => html`<button class="chip" aria-pressed=${this.tags.includes(t.value)}
          @click=${() => (this.tags = this.tags.includes(t.value) ? this.tags.filter(x => x !== t.value) : [...this.tags, t.value])}>${t.label}</button>`)}</div>
        <textarea class="in" rows="2" placeholder="Nota (facoltativa)" .value=${this.note} @input=${(e: any) => (this.note = e.target.value)}></textarea>
        <div class="row"><span class="grow"></span><hxk-button variant="primary" icon="check" ?loading=${this.saving}
          ?disabled=${!Object.keys(this.scores).length && !this.note.trim() && !this.tags.length} @click=${() => this.save()}>Salva</hxk-button></div>
      </div>
      ${this.data === undefined ? html`<hxk-state kind="loading"></hxk-state>` : this.data === null ? html`<hxk-state kind="offline" @retry=${() => this.load()}></hxk-state>` : html`
        ${Object.keys(series).length ? html`<div class="card col"><h2>Andamento</h2>
          ${Object.entries(series).map(([k, pts]: [string, any]) => html`<div class="small muted">${label(ms, k)}</div>
            <hxk-chart type="line" height="110" .labels=${pts.map((x: any) => dayLabel(x.date, false))} .series=${[{ name: label(ms, k), values: pts.map((x: any) => x.value) }]}></hxk-chart>`)}
          ${(this.data.markers || []).length ? html`<h3>Cambi nello stesso periodo</h3>${this.data.markers.slice(0, 10).map((mk: any) => html`<div class="small">
            <span class="muted tnum">${dayLabel(mk.date, false)}</span> · ${mk.title}${mk.text ? html`<span class="muted"> — ${mk.text}</span>` : nothing}</div>`)}` : nothing}
        </div>` : nothing}
        <div class="card list">${(this.data.items || []).length ? this.data.items.map((j: any) => html`<div class="entry">
          <span class="muted tnum" style="min-width:70px">${dayLabel(j.date, false)}</span>
          <div class="grow">${Object.entries(j.scores || {}).map(([k, v]) => `${label(ms, k)} ${v}`).join(' · ')}
            ${(j.tags || []).length ? html`<div class="small muted">${j.tags.join(', ')}</div>` : nothing}
            ${j.note ? html`<div class="small">${j.note}</div>` : nothing}</div>
          <hxk-button size="sm" variant="ghost" icon="trash" @click=${() => this.drop(j.id)}></hxk-button></div>`)
          : html`<div class="empty">Nessuna nota per questa zona.</div>`}</div>`}
    </div>`;
  }
}
