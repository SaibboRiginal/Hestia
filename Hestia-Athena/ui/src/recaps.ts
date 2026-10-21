/**
 * <athena-recaps> — "Recap": the daily recaps (docs/work/2026-10-20-recap-giornaliero). Each one shows the text that
 * was delivered and, on demand, the facts of every area it was written from (done / missed / next), with the
 * area's stroke icon. «Recap adesso» composes the evening one now. The time is an agenda job: moved in the calendar.
 * Reads GET /api/athena/recaps; POST /api/athena/recap/now.
 */
import { HestiaElement, html, css, nothing } from '@hestia/webui-sdk';
import { API, when } from './util';

// Recap texts are written for Telegram too: drop pictographs (web clients draw icons, never emoji).
const PICTO = /[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}\u{FE0F}\u{200D}]/gu;

/** Telegram HTML (only <b>) → lit parts; any other tag is dropped, the text stays escaped by lit. */
function richText(text: string) {
  const clean = String(text || '').replace(PICTO, '').replace(/<(?!\/?b>)[^>]*>/g, '');
  return clean.split(/(<b>[\s\S]*?<\/b>)/g).map(part =>
    part.startsWith('<b>') ? html`<b>${part.slice(3, -4)}</b>` : part);
}

const MOMENTS: Record<string, string> = { sera: 'sera', mattina: 'mattina' };
const TRIGGERS: Record<string, string> = { agenda: 'dal calendario', quick: 'a richiesta', manual: 'a richiesta' };

export class AthenaRecaps extends HestiaElement {
  static properties = { ...HestiaElement.properties, data: { state: true }, error: { state: true },
                        busy: { state: true }, open: { state: true } };
  declare data: any[] | null; declare error: string; declare busy: boolean; declare open: Record<string, boolean>;

  static styles = [...HestiaElement.styles, css`
    .head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    .sub { color: var(--text-3); font-size: 13px; }
    .line { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
    .text { white-space: pre-line; line-height: 1.5; }
    .areas { display: grid; gap: 8px; grid-template-columns: repeat(auto-fit, minmax(min(100%, 240px), 1fr)); }
    .area { background: var(--surface-2); border-radius: var(--radius-md); padding: 8px 10px; font-size: 13px;
            display: flex; flex-direction: column; gap: 4px; }
    .area .t { display: flex; align-items: center; gap: 6px; font-weight: 600; }
    .row { display: flex; gap: 6px; align-items: flex-start; }
    .row hxk-icon { flex: none; margin-top: 2px; }
    .link { background: none; border: 0; padding: 0; color: var(--accent); cursor: pointer; font: inherit; font-size: 12.5px; }
  `];

  constructor() { super(); this.data = null; this.error = ''; this.busy = false; this.open = {}; }

  connectedCallback() {
    super.connectedCallback();
    this.load();
    this.onHost('refresh', () => this.load());
    this.onHost('visible', () => this.load());
  }

  private async load() {
    const r = await this.host.api('GET', `${API}/recaps`, { query: { limit: 30 } });
    if (!r.ok) { this.error = r.status === 0 ? 'Athena non raggiungibile' : r.error || 'Athena non raggiungibile'; return; }
    this.error = '';
    this.data = r.data.recaps || [];
  }

  private async now() {
    this.busy = true;
    const r = await this.host.api('POST', `${API}/recap/now`);
    this.busy = false;
    if (!r.ok) { this.host.toast(r.error || 'Recap non riuscito', 'danger'); return; }
    this.host.toast(r.data?.label || 'Recap pronto', r.data?.status === 'empty' ? 'info' : 'success');
    this.load();
  }

  private rows(list: any[] | undefined, icon: string, tone: string) {
    return (list || []).map(x => html`<div class="row"><hxk-icon name=${icon} tone=${x.tone || tone} size="14"></hxk-icon>
      <span>${x.text}</span></div>`);
  }

  private area(p: any) {
    return html`<div class="area">
      <div class="t"><hxk-icon name=${p.icon || 'note'} tone="accent" size="15"></hxk-icon>${p.title}</div>
      ${this.rows(p.done, 'check', 'success')}
      ${this.rows(p.missed, 'x-circle', 'warning')}
      ${this.rows(p.next, 'clock', 'info')}
      ${p.note ? html`<div class="small muted">${p.note}</div>` : nothing}
    </div>`;
  }

  private recap(r: any) {
    const isOpen = !!this.open[r.id];
    const pieces: any[] = r.pieces || [];
    return html`<hxk-card>
      <div class="line"><b class="grow">${when(r.created_at)}</b>
        <hxk-badge tone="neutral">${MOMENTS[r.momento] || r.momento}</hxk-badge>
        <span class="small muted">${TRIGGERS[r.trigger] || ''}</span>
        ${r.fallback ? html`<hxk-badge tone="warning">elenco semplice</hxk-badge>` : nothing}
        ${r.delivered ? nothing : html`<hxk-badge tone="danger">non consegnato</hxk-badge>`}</div>
      <div class="text">${richText(r.text)}</div>
      ${pieces.length ? html`<div class="line"><button class="link" @click=${() => (this.open = { ...this.open, [r.id]: !isOpen })}>
          ${isOpen ? 'Nascondi i fatti' : `I fatti di ${pieces.length} ${pieces.length === 1 ? 'area' : 'aree'}`}</button></div>` : nothing}
      ${isOpen ? html`<div class="areas">${pieces.map(p => this.area(p))}</div>` : nothing}
    </hxk-card>`;
  }

  render() {
    if (this.error) return html`<div class="page"><hxk-state kind="offline" text=${this.error} @retry=${() => this.load()}></hxk-state></div>`;
    if (this.data === null) return html`<div class="page"><hxk-state kind="loading"></hxk-state></div>`;
    return html`<div class="page">
      <div class="head"><h1>Recap</h1><span class="sub">Com'è andata e cosa c'è dopo, un messaggio al giorno</span>
        <span class="grow"></span>
        <hxk-button variant="ghost" icon="refresh" @click=${() => this.load()}>Aggiorna</hxk-button>
        <hxk-button variant="primary" icon="note" ?loading=${this.busy} @click=${() => this.now()}>Recap adesso</hxk-button></div>
      ${this.data.length ? this.data.map(r => this.recap(r))
        : html`<hxk-state kind="empty" text="Nessun recap ancora. Arriva la sera; se la giornata è tranquilla non ti scrivo."></hxk-state>`}
      <p class="small muted">L'orario è nel calendario («Recap della sera», spostabile tra le 20:00 e le 23:30 per non
        cadere sui tuoi impegni). Il recap del mattino si aggiunge da «Da un modulo…». Tono e lunghezza in
        Impostazioni → Sistema → Athena.</p>
    </div>`;
  }
}
