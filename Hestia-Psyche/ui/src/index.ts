/**
 * Psyche («Umore») WebUI plugin (plugin contract docs/work/2026-10-17-client-plugins/SPEC.md §4; dossier
 * docs/work/2026-10-30-diario-umore). Page, widget and quick action declared in Hestia-Psyche/app/main.py.
 */
import { HestiaElement, css, definePlugin, html, nothing } from '@hestia/webui-sdk';
import type { ApiResult, HestiaHost, HttpMethod } from '@hestia/webui-sdk';

const API = '/api/mood';
const LEVELS = [
  { v: 1, icon: 'frown', tone: 'danger', label: 'A terra' },
  { v: 2, icon: 'frown', tone: 'warning', label: 'Giù' },
  { v: 3, icon: 'meh', tone: '', label: 'Così così' },
  { v: 4, icon: 'smile', tone: 'info', label: 'Bene' },
  { v: 5, icon: 'laugh', tone: 'success', label: 'Benissimo' }];
const level = (n: number) => LEVELS[Math.min(5, Math.max(1, Math.round(n))) - 1];
const SOURCES: Record<string, { icon: string; label: string }> = {
  chat: { icon: 'chat', label: 'dalla chat' }, tap: { icon: 'zap', label: 'un tocco' }, webui: { icon: 'edit', label: 'dal sito' },
  telegram: { icon: 'send', label: 'da Telegram' }, external: { icon: 'link', label: 'da un altro assistente' },
  checkin: { icon: 'bell', label: 'dalla domanda della sera' } };

async function call<T = any>(host: HestiaHost, method: HttpMethod, path: string, body?: unknown): Promise<ApiResult<T>> {
  const r = await host.api<T>(method, `${API}${path}`, body === undefined ? undefined : { body });
  if (!r.ok && method !== 'GET') host.toast(r.status === 0 ? 'Non raggiungibile, riprova' : r.error || 'Errore', 'warning');
  return r;
}
const ddmm = (iso: string) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}`;
const hhmm = (iso: string) => String(iso || '').slice(11, 16);

const styles = css`
  .between { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
  .faces { display: flex; gap: 8px; flex-wrap: wrap; }
  .face { display: grid; justify-items: center; gap: 4px; padding: 10px 12px; min-width: 64px; border-radius: var(--radius-sm);
    border: 1px solid var(--border); background: var(--surface-2); cursor: pointer; font-size: 12px; color: var(--text-2); }
  .face.on { border-color: var(--accent); background: var(--accent-soft); color: var(--text); }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; }
  .chip { padding: 3px 10px; border-radius: 999px; background: var(--surface-2); border: 1px solid var(--border); font-size: 13px; cursor: pointer; }
  .chip.on { background: var(--accent-soft); border-color: var(--accent); }
  .scale { display: flex; gap: 4px; align-items: center; }
  .dot { width: 26px; height: 26px; border-radius: 50%; border: 1px solid var(--border); background: var(--surface-2); cursor: pointer;
    font-size: 12px; display: grid; place-items: center; }
  .dot.on { background: var(--accent); color: var(--on-accent, #fff); border-color: var(--accent); }
  .month { display: grid; grid-template-columns: repeat(7, 1fr); gap: 4px; }
  .cell { aspect-ratio: 1; border-radius: 6px; background: var(--surface-2); display: grid; place-items: center; font-size: 11px; color: var(--text-3); }
  .cell.l1 { background: var(--danger-soft); color: var(--danger); } .cell.l2 { background: var(--warning-soft); color: var(--warning); }
  .cell.l3 { background: var(--surface-3, var(--border)); color: var(--text-2); } .cell.l4 { background: var(--info-soft); color: var(--info); }
  .cell.l5 { background: var(--success-soft); color: var(--success); }
  .entry { display: flex; gap: 10px; align-items: flex-start; padding: 8px 2px; border-bottom: 1px solid var(--border); }
  .entry:last-child { border-bottom: 0; }
  .quote { font-style: italic; color: var(--text-2); }
  .week { display: flex; gap: 4px; }
`;

export class PsycheMood extends HestiaElement {
  static properties = { ...HestiaElement.properties, today: { state: true }, hist: { state: true }, ins: { state: true },
                        opts: { state: true }, draft: { state: true }, more: { state: true } };
  declare today: any;
  declare hist: any;
  declare ins: any;
  declare opts: any;
  declare draft: Record<string, any>;
  declare more: boolean;
  static styles = [...HestiaElement.styles, styles];
  constructor() { super(); this.today = undefined; this.hist = undefined; this.ins = undefined; this.opts = { labels: [], causes: [] };
                  this.draft = { labels: [], causes: [] }; this.more = false; }
  connectedCallback() { super.connectedCallback(); this.load(); this.onHost('refresh', () => this.load()); }
  async load() {
    const [t, h, i, o] = await Promise.all([call(this.host, 'GET', '/today'), call(this.host, 'GET', '/history?days=35'),
                                            call(this.host, 'GET', '/insights'), call(this.host, 'GET', '/options')]);
    this.today = t.ok ? t.data : null;
    this.hist = h.ok ? h.data : null;
    this.ins = i.ok ? i.data : null;
    if (o.ok) this.opts = o.data;
  }
  private toggle(field: 'labels' | 'causes', v: string) {
    const cur: string[] = this.draft[field] || [];
    this.draft = { ...this.draft, [field]: cur.includes(v) ? cur.filter(x => x !== v) : [...cur, v] };
  }
  private async save(mood?: number) {
    const body = { ...this.draft, mood: mood ?? this.draft.mood, source: 'webui' };
    if (!body.mood) { this.host.toast('Scegli come stai', 'warning'); return; }
    const r = await call(this.host, 'POST', '', body);
    if (r.ok) { this.draft = { labels: [], causes: [] }; this.more = false; this.host.toast('Segnato', 'success'); this.load(); }
  }
  private async drop(id: string) {
    const r = await call(this.host, 'DELETE', `/${encodeURIComponent(id)}`);
    if (r.ok) { this.host.toast('Tolto', 'success'); this.load(); }
  }
  private scale(field: string, label: string) {
    return html`<div class="between small"><span>${label}</span><div class="scale">${[1, 2, 3, 4, 5].map(n => html`<span
      class="dot ${this.draft[field] === n ? 'on' : ''}" @click=${() => { this.draft = { ...this.draft, [field]: this.draft[field] === n ? null : n }; }}>${n}</span>`)}</div></div>`;
  }
  private month() {
    const days: Record<string, any> = {};
    for (const d of this.hist?.days || []) days[d.date] = d;
    const end = new Date(); const cells = [];
    const start = new Date(end); start.setDate(end.getDate() - 34);
    const lead = (start.getDay() + 6) % 7;
    for (let i = 0; i < lead; i++) cells.push(html`<span></span>`);
    for (let i = 0; i < 35; i++) {
      const d = new Date(start); d.setDate(start.getDate() + i);
      const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
      const s = days[iso];
      cells.push(html`<span class="cell ${s ? 'l' + s.mood : ''}" title=${s ? `${ddmm(iso)} · ${level(s.mood).label}${s.labels.length ? ' · ' + s.labels.join(', ') : ''}` : ddmm(iso)}>${d.getDate()}</span>`);
    }
    return html`<div class="month">${['L', 'M', 'M', 'G', 'V', 'S', 'D'].map(x => html`<span class="small muted" style="text-align:center">${x}</span>`)}${cells}</div>`;
  }
  render() {
    if (this.today === undefined) return html`<hxk-state kind="loading"></hxk-state>`;
    if (this.today === null) return html`<hxk-state kind="offline" @retry=${() => this.load()}></hxk-state>`;
    const s = this.today.summary;
    const days = (this.hist?.days || []).slice(-30);
    return html`<div class="page">
      <div class="between"><h1>Umore</h1>
        <hxk-button variant="ghost" icon="chat" @click=${() => this.host.assistant({ label: 'Umore', suggestions: ['Come sono stato questa settimana?', "Cosa mi fa stare meglio?"] })}>Chiedi</hxk-button></div>
      <div class="card col"><div class="between"><h3>Come stai?</h3>
          ${s ? html`<hxk-badge tone=${level(s.mood).tone || 'neutral'}>Oggi ${s.mood}/5 · ${s.mood_word}</hxk-badge>` : nothing}</div>
        <div class="faces">${LEVELS.map(l => html`<div class="face ${this.draft.mood === l.v ? 'on' : ''}"
            @click=${() => { if (this.more) this.draft = { ...this.draft, mood: l.v }; else this.save(l.v); }}>
          <hxk-icon name=${l.icon} size="26" tone=${l.tone}></hxk-icon>${l.label}</div>`)}</div>
        ${this.more ? html`
          ${this.scale('energy', 'Energia')}${this.scale('stress', 'Stress')}
          <div class="small muted">Come ti senti</div>
          <div class="chips">${this.opts.labels.map((v: string) => html`<span class="chip ${this.draft.labels.includes(v) ? 'on' : ''}" @click=${() => this.toggle('labels', v)}>${v}</span>`)}</div>
          <div class="small muted">Cosa c'entra</div>
          <div class="chips">${this.opts.causes.map((v: string) => html`<span class="chip ${this.draft.causes.includes(v) ? 'on' : ''}" @click=${() => this.toggle('causes', v)}>${v}</span>`)}</div>
          <hxk-field type="textarea" placeholder="Due righe sulla giornata (facoltative)" .value=${this.draft.note || ''} @change=${(e: any) => { this.draft = { ...this.draft, note: e.detail }; }}></hxk-field>
          <div class="row"><hxk-button variant="primary" @click=${() => this.save()}>Salva</hxk-button>
            <hxk-button variant="ghost" @click=${() => { this.more = false; this.draft = { labels: [], causes: [] }; }}>Annulla</hxk-button></div>`
          : html`<div class="row"><span class="small muted grow">Un tocco basta. Se in chat dici come stai, l'assistente lo segna da solo.</span>
              <hxk-button size="sm" variant="ghost" icon="plus" @click=${() => { this.more = true; }}>Dettagli</hxk-button></div>`}
      </div>
      <div class="grid" style="--min: 300px">
        <div class="card col"><h3>Ultime 5 settimane</h3>${this.month()}</div>
        <div class="card col"><h3>Andamento</h3>
          ${days.length >= 2 ? html`<hxk-chart type="line" height="140" .labels=${days.map((d: any) => ddmm(d.date))}
              .series=${[{ name: 'Umore', values: days.map((d: any) => d.mood) },
                         ...(days.some((d: any) => d.energy) ? [{ name: 'Energia', values: days.map((d: any) => d.energy || 0) }] : [])]}></hxk-chart>` : nothing}
          ${(this.ins?.sentences || []).map((t: string) => html`<div class="small">${t}</div>`)}
        </div>
      </div>
      <div class="card col"><h3>Voci</h3>
        ${(this.hist?.items || []).length ? this.hist.items.slice(0, 40).map((r: any) => html`<div class="entry">
            <hxk-icon name=${level(r.mood).icon} tone=${level(r.mood).tone} size="20"></hxk-icon>
            <div class="grow"><div>${r.mood}/5 · ${r.mood_word}${r.energy ? html` <span class="muted small">· energia ${r.energy}/5</span>` : nothing}${r.labels?.length ? html` <span class="muted small">· ${r.labels.join(', ')}</span>` : nothing}</div>
              ${r.quote ? html`<div class="small quote">«${r.quote}»</div>` : nothing}
              ${r.note ? html`<div class="small">${r.note}</div>` : nothing}
              <div class="small muted"><hxk-icon name=${(SOURCES[r.source] || SOURCES.webui).icon} size="12"></hxk-icon> ${ddmm(r.date)} ${hhmm(r.at)} · ${(SOURCES[r.source] || SOURCES.webui).label}</div></div>
            <hxk-button size="sm" variant="ghost" icon="trash" title="Togli" @click=${() => this.drop(r.id)}></hxk-button>
          </div>`) : html`<hxk-state kind="empty" text="Ancora niente: tocca una faccina qui sopra o dillo in chat."></hxk-state>`}
      </div>
    </div>`;
  }
}

export class PsycheWidget extends HestiaElement {
  static properties = { ...HestiaElement.properties, data: { state: true } };
  declare data: any;
  static styles = [...HestiaElement.styles, styles, css`:host { display: block; height: 100%; }`];
  constructor() { super(); this.data = undefined; }
  connectedCallback() { super.connectedCallback(); this.load(); this.onHost('refresh', () => this.load()); this.onHost('visible', () => this.load()); }
  async load() { const r = await call(this.host, 'GET', '/history?days=7'); this.data = r.ok ? r.data : null; }
  private async tap(mood: number) {
    const r = await call(this.host, 'POST', '/tap', { mood });
    if (r.ok) { this.host.toast('Segnato', 'success'); this.load(); }
  }
  render() {
    if (this.data === undefined) return html`<hxk-state kind="loading"></hxk-state>`;
    if (this.data === null) return html`<hxk-state kind="offline" @retry=${() => this.load()}></hxk-state>`;
    const days = this.data.days || [];
    const today = days.length && days[days.length - 1].date === this.data.to ? days[days.length - 1] : null;
    return html`<div class="col" style="gap:8px">
      ${today ? html`<div class="row"><hxk-icon name=${level(today.mood).icon} tone=${level(today.mood).tone} size="22"></hxk-icon>
          <span>Oggi ${today.mood_word}</span></div>`
        : html`<div class="faces">${[2, 3, 4].map(v => html`<span class="face" style="min-width:0;padding:6px" title=${level(v).label} @click=${() => this.tap(v)}>
            <hxk-icon name=${level(v).icon} tone=${level(v).tone} size="20"></hxk-icon></span>`)}</div>`}
      ${days.length ? html`<div class="week">${days.map((d: any) => html`<span class="cell l${d.mood}" style="width:18px;aspect-ratio:1" title=${`${ddmm(d.date)} · ${d.mood_word}`}></span>`)}</div>` : nothing}
    </div>`;
  }
}

definePlugin({ 'psyche-mood': PsycheMood, 'psyche-widget': PsycheWidget });
