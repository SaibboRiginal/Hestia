/** <athena-last-widget> — "Ultimo pensiero": the latest Athena cycle and what came out of it. */
import { HestiaElement, html, css, nothing } from '@hestia/webui-sdk';
import { API, KINDS, OUTCOMES, ago } from './util';

export class AthenaLastWidget extends HestiaElement {
  static properties = { ...HestiaElement.properties, data: { state: true } };
  declare data: any;   // undefined = loading, null = unreachable
  static styles = [...HestiaElement.styles, css`
    :host { display: block; height: 100%; }
    .w { display: flex; flex-direction: column; gap: 6px; height: 100%; cursor: pointer; overflow: auto; }
    .t { font-weight: 600; }
    .r { display: flex; align-items: center; gap: 6px; font-size: 12.5px; }
  `];
  connectedCallback() {
    super.connectedCallback();
    this.load();
    this.onHost('refresh', () => this.load());
    this.onHost('visible', () => this.load());
  }
  private async load() {
    const r = await this.host.api('GET', `${API}/thinking/summary`, { query: { limit: 1 } });
    this.data = r.ok ? r.data : null;
  }
  render() {
    if (this.data === undefined) return html`<hxk-state kind="loading"></hxk-state>`;
    if (this.data === null) return html`<hxk-state kind="offline" text="Athena non raggiungibile" @retry=${() => this.load()}></hxk-state>`;
    const c = this.data.cycles?.[0];
    const go = () => this.host.navigate('pensieri');
    if (!c) return html`<div class="w" @click=${go}><span class="small muted">Ultimo pensiero</span>
      <div class="muted">${this.data.running ? 'Athena sta pensando…' : 'Nessun ciclo ancora.'}</div></div>`;
    const cands: any[] = c.candidates || [];
    const accepted = cands.filter(x => x.accepted);
    const best = accepted[0] || [...cands].sort((a, b) => b.score - a.score)[0];
    const many = (this.ctx?.size || 'm') !== 'm';
    return html`<div class="w" @click=${go}>
      <div class="r"><span class="small muted grow">Ultimo pensiero · ${ago(c.cycle_at)}</span>
        ${this.data.running ? html`<hxk-badge tone="info">pensa…</hxk-badge>` : nothing}</div>
      ${best ? html`<div class="t truncate" title=${best.title}>${best.title}</div>
        <div class="r"><hxk-badge tone=${best.accepted ? 'success' : 'neutral'}>${best.accepted ? (OUTCOMES[best.outcome]?.label || 'accettata') : 'scartata'}</hxk-badge>
          <span class="small muted truncate">${KINDS[best.kind] || best.kind} · ${Number(best.score || 0).toFixed(2)}</span></div>`
        : html`<div class="muted">Niente da proporre: tutto tranquillo.</div>`}
      <div class="small muted">${cands.length ? `${accepted.length} accettate su ${cands.length} idee` : 'nessuna idea in questo ciclo'}</div>
      ${many && best?.gate_reason ? html`<div class="small muted">${best.gate_reason}</div>` : nothing}
      ${many && best?.reasoning ? html`<div class="small">${best.reasoning}</div>` : nothing}
    </div>`;
  }
}
