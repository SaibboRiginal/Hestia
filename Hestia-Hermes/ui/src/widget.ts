/** <hermes-today-widget> — «Consegne oggi»: notifications of today, held, failed, waiting for an answer. */
import { HestiaElement, html, css, nothing } from '@hestia/webui-sdk';
import { API, hermesStyles, todayStart } from './util';

export class HermesTodayWidget extends HestiaElement {
  static properties = { ...HestiaElement.properties, s: { state: true }, error: { state: true } };
  declare s: any; declare error: string;
  static styles = [...HestiaElement.styles, hermesStyles, css`
    :host { display: block; height: 100%; }
    .w { display: flex; flex-direction: column; gap: 6px; height: 100%; cursor: pointer; }
    .big { font-size: 26px; font-weight: 650; line-height: 1.1; }
  `];
  constructor() { super(); this.s = null; this.error = ''; }
  connectedCallback() {
    super.connectedCallback();
    this.load();
    this.onHost('refresh', () => this.load());
    this.onHost('visible', () => this.load());
    this.addEventListener('retry', () => this.load());
  }
  private async load() {
    const r = await this.host.api('GET', `${API}/deliveries`, { query: { since: todayStart(), limit: 200 } });
    if (!r.ok) { this.error = 'Hermes non raggiungibile'; return; }
    this.error = ''; this.s = r.data.summary;
  }
  render() {
    if (this.error) return html`<hxk-state kind="offline" text=${this.error}></hxk-state>`;
    const s = this.s;
    if (!s) return html`<hxk-state kind="loading"></hxk-state>`;
    const small = (this.ctx?.size || 'm') === 's';
    const clients = Object.entries(s.clients || {}) as Array<[string, any]>;
    return html`<div class="w" @click=${() => this.host.navigate('consegne')}>
      <span class="small muted">Notifiche di oggi</span>
      <div class="big tnum">${s.total}</div>
      <div class="row wrap">
        ${s.failed ? html`<hxk-badge tone="danger">${s.failed} fallite</hxk-badge>` : nothing}
        ${s.held ? html`<hxk-badge tone="warning">${s.held} trattenute</hxk-badge>` : nothing}
        ${s.pending ? html`<hxk-badge tone="accent">${s.pending} in attesa</hxk-badge>` : nothing}
        ${!s.failed && !s.held && !s.pending ? html`<span class="small muted">tutto consegnato</span>` : nothing}
      </div>
      ${small || !clients.length ? nothing : html`<div class="small muted truncate">${clients.map(([n, c]) => `${n} ${c.delivered}`).join(' · ')}</div>`}
    </div>`;
  }
}
