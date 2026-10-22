/**
 * <athena-signals> — "Segnali": what the life reflection reads (docs/work/2026-10-20-riflessione-a-livelli).
 * Active signals of each area (worst first), the weekly series as small charts, the links found between areas and
 * the latest observations (they reach the user only in the evening recap). Reads GET /api/athena/signals.
 */
import { HestiaElement, html, css, nothing } from '@hestia/webui-sdk';
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
    if (!r.ok) { this.error = r.status === 0 ? 'Riflessione non raggiungibile' : r.error || 'Segnali non disponibili'; return; }
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
        <div class="small muted">${area(s.domain)} · ${sev.label} · aggiornato ${ago(s.updated_at)}</div></div>
      ${s.page ? html`<hxk-button size="sm" variant="ghost" icon="chevron-right" @click=${() => this.open(s)}>Apri</hxk-button>` : nothing}
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
      <div class="head"><h1>Segnali</h1><span class="sub">Quello che ogni area nota sui suoi dati, e cosa ne ricava la riflessione</span>
        <span class="grow"></span><hxk-button variant="ghost" icon="refresh" @click=${() => this.load()}>Aggiorna</hxk-button></div>
      ${domains.length > 1 ? html`<div class="filters" role="group" aria-label="Area">
        <button aria-pressed=${String(!this.domain)} @click=${() => (this.domain = '')}>Tutte</button>
        ${domains.map(dm => html`<button aria-pressed=${String(this.domain === dm)} @click=${() => (this.domain = dm)}>${area(dm)}</button>`)}</div>` : nothing}

      <hxk-card heading="Segnali attivi" subtitle="Frasi brevi calcolate dalle aree, senza intelligenza artificiale">
        ${sig.length ? sig.map(s => this.signalRow(s))
          : html`<div class="small muted">Nessun segnale attivo. Le aree li pubblicano man mano che raccolgono dati.</div>`}
      </hxk-card>

      <hxk-card heading="Collegamenti tra aree" subtitle="Due andamenti che si muovono insieme da settimane: non vuol dire che uno causi l'altro">
        ${links.length ? html`<ul class="items">${links.map(l => html`<li class="small">${linkText(l)}</li>`)}</ul>`
          : html`<div class="small muted">Nessun collegamento abbastanza forte per ora: servono alcune settimane di dati in almeno due aree.</div>`}
      </hxk-card>

      <hxk-card heading="Osservazioni recenti" subtitle="Arrivano nel recap della sera, sotto «Da tenere d'occhio»">
        ${obs.length ? obs.map(o => html`<div class="obs"><div class="line"><b class="grow">${o.title}</b>
            ${(o.domains || []).map((dm: string) => html`<span class="small muted">${area(dm)}</span>`)}</div>
          <div>${o.text}</div><div class="small muted">${when(o.at)}</div></div>`)
          : html`<div class="small muted">Ancora nessuna osservazione.</div>`}
      </hxk-card>

      ${series.length ? html`<h2>Andamento settimanale</h2>
        <div class="grid">${series.map(([n, s]) => this.seriesCard(n, s))}</div>` : nothing}
    </div>`;
  }
}
