/**
 * <athena-signals> — "Signals": what the life reflection reads (docs/work/2026-10-20-layered-reflection).
 * Active signals of each area (worst first), the weekly series as small charts, the links found between areas and
 * the latest observations (they reach the user only in the evening recap). Reads GET /api/athena/signals.
 */
import { HestiaElement, html, css, nothing, tr } from '@hestia/webui-sdk';
import { API, SEVERITY, ago, area, linkText, when } from './util';

export class AthenaSignals extends HestiaElement {
  static properties = { ...HestiaElement.properties, data: { state: true }, error: { state: true }, domain: { state: true } };
  declare data: any; declare error: string; declare domain: string;

  static styles = [...HestiaElement.styles, css`
    .head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    .sub { color: var(--text-3); font-size: 13px; }
    .filters { display: flex; gap: 6px; flex-wrap: wrap; }
    .filters button { border: 1px solid var(--border); background: var(--surface); font: inherit; font-size: 12.5px; padding: 3px 10px; border-radius: var(--radius-full); color: var(--text-2); cursor: pointer; }
    .filters button[aria-pressed="true"] { border-color: var(--accent); color: var(--accent); }
    .sig { display: flex; gap: 10px; align-items: flex-start; padding: 8px 0; border-top: 1px solid var(--border); }
    .sig:first-child { border-top: 0; }
    .grid { display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(min(100%, 280px), 1fr)); }
    .obs { padding: 8px 0; border-top: 1px solid var(--border); }
    .obs:first-child { border-top: 0; }
    .line { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
    .items { margin: 0; padding-left: 16px; }
    .items li { margin: 3px 0; }
  `];

  constructor() { super(); this.data = null; this.error = ''; this.domain = ''; }

  connectedCallback() {
    super.connectedCallback();
    this.load();
    this.onHost('refresh', () => this.load());
    this.onHost('visible', () => this.load());
  }

  private async load() {
    const r = await this.host.api('GET', `${API}/signals`, { query: { limit: 100, weeks: 12 } });
    if (!r.ok) { this.error = r.status === 0 ? tr('Reflection not reachable') : r.error || tr('Signals not available'); return; }
    this.error = '';
    this.data = r.data;
  }

  private open(s: any) {
    if (s.module && s.page) this.host.navigate(s.page, {}, s.module);
  }

  private signalRow(s: any) {
    const sev = SEVERITY[s.severity] || SEVERITY.info;
    return html`<div class="sig">
      <hxk-icon name=${sev.icon} style=${`color:var(--${sev.tone === 'neutral' ? 'text-3' : sev.tone})`}></hxk-icon>
      <div class="grow"><div>${s.text}</div>
        <div class="small muted">${area(s.domain)} · ${sev.label} · ${tr("updated {0}", ago(s.updated_at))}</div></div>
      ${s.page ? html`<hxk-button size="sm" variant="ghost" icon="chevron-right" @click=${() => this.open(s)}>${tr("Open")}</hxk-button>` : nothing}
    </div>`;
  }

  private seriesCard(name: string, s: any) {
    const weeks = Object.keys(s.values || {}).sort();
    if (weeks.length < 2) return nothing;
    const labels = weeks.map(w => `S${w.split('-W')[1]}`);
    return html`<hxk-card heading=${s.label || name} subtitle=${area(s.domain)}>
      <hxk-chart type="line" .labels=${labels} .series=${[{ name: s.label || name, values: weeks.map(w => Number(s.values[w])) }]} height="110"></hxk-chart>
    </hxk-card>`;
  }

  render() {
    if (this.error) return html`<div class="page"><hxk-state kind="offline" text=${this.error} @retry=${() => this.load()}></hxk-state></div>`;
    const d = this.data;
    if (!d) return html`<div class="page"><hxk-state kind="loading"></hxk-state></div>`;
    const all: any[] = d.signals || [];
    const domains = [...new Set([...all.map(s => s.domain), ...Object.values(d.series || {}).map((s: any) => s.domain)])].filter(Boolean) as string[];
    const sig = this.domain ? all.filter(s => s.domain === this.domain) : all;
    const series = Object.entries(d.series || {}).filter(([, s]: any) => !this.domain || s.domain === this.domain);
    const links: any[] = (d.links || []).filter((l: any) => !this.domain || l.a_domain === this.domain || l.b_domain === this.domain);
    const obs: any[] = d.observations || [];
    return html`<div class="page">
      <hxk-page-head heading=${tr("Signals")} sub=${tr("What each area notices in its data, and what the reflection gets from it")} ask=${tr("Signals")}>
        <hxk-button variant="ghost" icon="refresh" title=${tr("Refresh")} @click=${() => this.load()}></hxk-button></hxk-page-head>
      ${domains.length > 1 ? html`<div class="filters" role="group" aria-label=${tr("Area")}>
        <button aria-pressed=${String(!this.domain)} @click=${() => (this.domain = '')}>${tr("All")}</button>
        ${domains.map(dm => html`<button aria-pressed=${String(this.domain === dm)} @click=${() => (this.domain = dm)}>${area(dm)}</button>`)}</div>` : nothing}

      <hxk-card heading=${tr("Active signals")} subtitle=${tr("Short sentences computed from the areas")}>
        ${sig.length ? sig.map(s => this.signalRow(s))
          : html`<div class="small muted">${tr("No active signal. The areas publish them as they collect data.")}</div>`}
      </hxk-card>

      <hxk-card heading=${tr("Links between areas")} subtitle=${tr("Two trends that move together for weeks: it doesn't mean one causes the other")}>
        ${links.length ? html`<ul class="items">${links.map(l => html`<li class="small">${linkText(l)}</li>`)}</ul>`
          : html`<div class="small muted">${tr("No link strong enough for now: a few weeks of data in at least two areas are needed.")}</div>`}
      </hxk-card>

      <hxk-card heading=${tr("Recent observations")} subtitle=${tr("They arrive in the evening recap, under «To keep an eye on»")}>
        ${obs.length ? obs.map(o => html`<div class="obs"><div class="line"><b class="grow">${o.title}</b>
            ${(o.domains || []).map((dm: string) => html`<span class="small muted">${area(dm)}</span>`)}</div>
          <div>${o.text}</div><div class="small muted">${when(o.at)}</div></div>`)
          : html`<div class="small muted">${tr("No observation yet.")}</div>`}
      </hxk-card>

      ${series.length ? html`<h2>${tr("Weekly trend")}</h2>
        <div class="grid">${series.map(([n, s]) => this.seriesCard(n, s))}</div>` : nothing}
    </div>`;
  }
}
