/** <oracle-usage-widget> — "Uso modelli oggi": calls, tokens and cost of today, per model (GET /api/ui/stats). */
import { HestiaElement, html, css, nothing } from '@hestia/webui-sdk';
import { API, cost, num } from './util';

export class OracleUsageWidget extends HestiaElement {
  static properties = { ...HestiaElement.properties, data: { state: true } };
  declare data: any;   // undefined = loading, null = unreachable
  static styles = [...HestiaElement.styles, css`
    :host { display: block; height: 100%; }
    .w { display: flex; flex-direction: column; gap: 6px; height: 100%; cursor: pointer; overflow: auto; }
    .big { font-size: 22px; font-weight: 650; line-height: 1.1; font-variant-numeric: tabular-nums; }
    .r { display: flex; justify-content: space-between; gap: 8px; font-size: 12.5px; }
    .r span:last-child { white-space: nowrap; font-variant-numeric: tabular-nums; color: var(--text-2); }
  `];
  connectedCallback() {
    super.connectedCallback();
    this.load();
    this.onHost('refresh', () => this.load());
    this.onHost('visible', () => this.load());
  }
  private async load() {
    const r = await this.host.api('GET', `${API}/stats`, { query: { days: 1 } });
    this.data = r.ok ? r.data : null;
  }
  render() {
    if (this.data === undefined) return html`<hxk-state kind="loading"></hxk-state>`;
    if (this.data === null) return html`<hxk-state kind="offline" text="Assistente non raggiungibile" @retry=${() => this.load()}></hxk-state>`;
    const t = this.data.today || {};
    const rows: any[] = this.data.today_by_model || [];
    const size = this.ctx?.size || 'm';
    return html`<div class="w" @click=${() => this.host.navigate('cervello')}>
      <span class="small muted">Uso modelli oggi</span>
      <div class="big">${num(t.calls)} <span class="small muted" style="font-weight:400">chiamate</span></div>
      <div class="small muted">${num(t.input_tokens)} / ${num(t.output_tokens)} token${t.cost_usd ? ` · ${cost(t.cost_usd)}` : ''}</div>
      ${size === 's' ? nothing : rows.length
        ? rows.slice(0, size === 'm' ? 2 : 6).map(r => html`<div class="r"><span class="truncate">${r.label || r.use_case} · ${r.model}</span>
            <span>${num(r.calls)}</span></div>`)
        : html`<div class="small muted">Nessuna chiamata oggi.</div>`}
    </div>`;
  }
}
