/** <chronos-failed-widget> — «Job falliti»: agenda jobs whose last run failed in the last 24 h, with «Riprova». */
import { HestiaElement, html, css, nothing } from '@hestia/webui-sdk';
import { API, retry, when } from './util';

export class ChronosFailedWidget extends HestiaElement {
  static properties = { ...HestiaElement.properties, rows: { state: true }, error: { state: true }, busy: { state: true } };
  declare rows: any[] | null; declare error: string; declare busy: string;
  static styles = [...HestiaElement.styles, css`
    :host { display: block; height: 100%; }
    .w { display: flex; flex-direction: column; gap: 6px; height: 100%; }
    .big { font-size: 26px; font-weight: 650; line-height: 1.1; font-variant-numeric: tabular-nums; cursor: pointer; }
    .j { display: flex; align-items: center; gap: 6px; }
  `];
  constructor() { super(); this.rows = null; this.error = ''; this.busy = ''; }
  connectedCallback() {
    super.connectedCallback();
    this.load();
    this.onHost('refresh', () => this.load());
    this.onHost('visible', () => this.load());
    this.addEventListener('retry', () => this.load());
  }
  private async load() {
    const r = await this.host.api('GET', `${API}/runs/failed`);
    if (!r.ok) { this.error = 'Chronos non raggiungibile'; return; }
    this.error = ''; this.rows = Array.isArray(r.data) ? r.data : [];
  }
  private async run(c: any) {
    this.busy = c.id; await retry(this.host, c.id, c.label); this.busy = ''; this.load();
  }
  render() {
    if (this.error) return html`<hxk-state kind="offline" text=${this.error}></hxk-state>`;
    const rows = this.rows;
    if (!rows) return html`<hxk-state kind="loading"></hxk-state>`;
    const small = (this.ctx?.size || 'm') === 's';
    return html`<div class="w">
      <span class="small muted">Job falliti (24 ore)</span>
      <div class="big" style=${rows.length ? 'color:var(--danger)' : ''} @click=${() => this.host.navigate('esecuzioni', { status: 'failed' })}>${rows.length}</div>
      ${!rows.length ? html`<span class="small muted">Tutto a posto</span>` : small ? nothing
        : rows.slice(0, 3).map(c => html`<div class="j"><div class="grow"><div class="truncate">${c.label}</div>
            <div class="small muted truncate">${c.owner} · ${when(c.at)}</div></div>
            <hxk-button size="sm" icon="refresh" ?loading=${this.busy === c.id} @click=${() => this.run(c)}>Riprova</hxk-button></div>`)}
    </div>`;
  }
}
