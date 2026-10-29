/** <argus-status-widget> — "Stato sistema": healthy / total from Argus's last cycle, open incidents, who is down. */
import { HestiaElement, html, css, nothing } from '@hestia/webui-sdk';
import { API, ago, statusOf } from './util';

export class ArgusStatusWidget extends HestiaElement {
  static properties = { ...HestiaElement.properties, data: { state: true }, error: { state: true } };
  declare data: any; declare error: boolean;
  static styles = [...HestiaElement.styles, css`
    :host { display: block; height: 100%; }
    .w { display: flex; flex-direction: column; gap: 6px; height: 100%; padding: 2px; cursor: pointer; }
    .big { font-size: 24px; font-weight: 650; line-height: 1.1; font-variant-numeric: tabular-nums; }
  `];
  constructor() { super(); this.data = null; this.error = false; }
  connectedCallback() { super.connectedCallback(); this.load(); this.onHost('refresh', () => this.load()); this.onHost('visible', () => this.load()); }
  private async load() {
    const r = await this.host.api('GET', `${API}/overview`);
    this.error = !r.ok; if (r.ok) this.data = r.data;
  }
  render() {
    if (this.error && !this.data) return html`<hxk-state kind="offline" text="Salute del sistema non raggiungibile" @retry=${() => this.load()}></hxk-state>`;
    if (!this.data) return html`<hxk-state kind="loading"></hxk-state>`;
    const d = this.data;
    if (!d.last_cycle_at) return html`<div class="w"><span class="small muted">Stato sistema</span><div class="muted">Primo controllo in corso…</div></div>`;
    const bad: any[] = d.unhealthy_services || [];
    const n = this.ctx?.size === 's' ? 2 : this.ctx?.size === 'l' ? 8 : 4;
    return html`<div class="w" @click=${() => this.host.navigate('salute')}>
      <div class="row"><span class="small muted grow">Stato sistema</span><span class="small muted">${ago(d.last_cycle_at)}</span></div>
      <div class="big">${d.healthy}<span class="muted" style="font-size:15px"> / ${d.total} sani</span></div>
      ${bad.length ? html`<div class="row wrap">${bad.slice(0, n).map(s => html`<hxk-badge tone=${statusOf(s.status)[0]}>${s.service}</hxk-badge>`)}
          ${bad.length > n ? html`<span class="small muted">+${bad.length - n}</span>` : nothing}</div>`
        : html`<hxk-badge tone="success">tutto in ordine</hxk-badge>`}
      ${d.open_incidents && this.ctx?.size !== 's' ? html`<span class="small muted">${d.open_incidents} incidenti aperti</span>` : nothing}
    </div>`;
  }
}
