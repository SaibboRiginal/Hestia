/**
 * <argus-performance> — «Prestazioni»: per module memory, processor, response time, uptime and restarts from the
 * last sample, over your limits highlighted; Hub round trip; database and blob size with growth per day; the
 * selected module's last 24 hours as a chart. Limits are settings («Prestazioni» in Argus' settings).
 * Reads GET /api/argus/performance and /api/argus/performance/history. Dossier 2026-10-24-tutto-brainstorm-cindy
 * D16 + Cindy 25 (W3) + W7.
 */
import { HestiaElement, html, css, nothing } from '@hestia/webui-sdk';

const API = '/api/argus';
const METRICS = [{ id: 'mem_mb', label: 'Memoria', unit: 'MB' }, { id: 'cpu', label: 'Processore', unit: '%' },
                 { id: 'ms', label: 'Risposta', unit: 'ms' }];

function bytes(n?: number | null): string {
  if (n === null || n === undefined) return '–';
  const u = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0, v = Number(n);
  while (Math.abs(v) >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return `${v.toLocaleString('it-IT', { maximumFractionDigits: i >= 2 ? 1 : 0 })} ${u[i]}`;
}

function uptime(s?: number | null): string {
  if (s === null || s === undefined) return '–';
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))} min`;
  if (s < 86400) return `${Math.round(s / 3600)} h`;
  return `${Math.round(s / 86400)} g`;
}

const num = (v: any, d = 0) => (v === null || v === undefined ? '–' : Number(v).toLocaleString('it-IT', { maximumFractionDigits: d }));

export class ArgusPerformance extends HestiaElement {
  static properties = { ...HestiaElement.properties, data: { state: true }, error: { state: true },
                        pick: { state: true }, metric: { state: true }, hist: { state: true } };
  declare data: any; declare error: string; declare pick: string; declare metric: string; declare hist: any;

  static styles = [...HestiaElement.styles, css`
    .head { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
    .sub { color: var(--text-3); font-size: 13px; }
    .stats { display: grid; gap: 8px; grid-template-columns: repeat(auto-fill, minmax(min(100%, 160px), 1fr)); }
    .stat { border: 1px solid var(--border); border-radius: var(--radius-md); padding: 10px; }
    .stat b { display: block; font-size: 18px; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th { text-align: left; color: var(--text-3); font-weight: 500; padding: 6px 8px; border-bottom: 1px solid var(--border); }
    td { padding: 6px 8px; border-bottom: 1px solid var(--border); white-space: nowrap; }
    tr.sel td { background: var(--accent-soft); }
    tbody tr { cursor: pointer; }
    td.over { color: var(--danger); font-weight: 600; }
    .scroll { overflow-x: auto; }
    .chips { display: flex; gap: 6px; flex-wrap: wrap; }
    .chip { font: inherit; font-size: 13px; padding: 4px 10px; border-radius: 99px; border: 1px solid var(--border-strong);
      background: var(--surface); color: var(--text-2); cursor: pointer; }
    .chip[aria-pressed=true] { background: var(--accent-soft); color: var(--accent); border-color: var(--accent); }
  `];

  constructor() { super(); this.data = null; this.error = ''; this.pick = ''; this.metric = 'mem_mb'; this.hist = null; }

  connectedCallback() {
    super.connectedCallback();
    this.load();
    this.onHost('refresh', () => this.load());
    this.onHost('visible', () => this.load());
  }

  private async load() {
    const r = await this.host.api('GET', `${API}/performance`);
    if (!r.ok) { this.error = r.status === 0 ? 'Non raggiungibile' : r.error || 'Non raggiungibile'; return; }
    this.error = '';
    this.data = r.data;
    if (!this.pick) this.pick = Object.keys(r.data?.services || {})[0] || '';
    this.loadHistory();
  }

  private async loadHistory() {
    if (!this.pick) { this.hist = null; return; }
    const r = await this.host.api('GET', `${API}/performance/history`, { query: { service: this.pick, hours: 24 } });
    this.hist = r.ok ? r.data : null;
  }

  private select(name: string) { this.pick = name; this.loadHistory(); }

  private chart() {
    const rows: any[] = this.hist?.series?.[this.pick] || [];
    if (rows.length < 2) return html`<hxk-state kind="empty" text="Servono un paio di controlli per il grafico."></hxk-state>`;
    const m = METRICS.find(x => x.id === this.metric) || METRICS[0];
    const step = Math.max(1, Math.ceil(rows.length / 48));
    const pts = rows.filter((_, i) => i % step === 0);
    const labels = pts.map(p => new Date(p.at).toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' }));
    return html`<hxk-chart type="line" .labels=${labels} unit=${m.unit}
      .series=${[{ name: m.label, values: pts.map(p => Number(p[m.id]) || 0) }]}></hxk-chart>`;
  }

  render() {
    if (this.error) return html`<div class="page"><h1>Prestazioni</h1><hxk-state kind="offline" text=${this.error} @retry=${() => this.load()}></hxk-state></div>`;
    const d = this.data;
    if (!d) return html`<div class="page"><hxk-state kind="loading"></hxk-state></div>`;
    const t = d.thresholds || {};
    const services = Object.entries<any>(d.services || {});
    const st = d.storage;
    const dbOver = st && t.database_gb && st.database_bytes > t.database_gb * 1024 ** 3;
    const growOver = st && t.growth_mb_day && (st.growth_day_bytes || 0) > t.growth_mb_day * 1024 ** 2;
    return html`<div class="page">
      <div class="head"><h1>Prestazioni</h1><span class="sub">${d.at ? `Ultimo controllo ${new Date(d.at).toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' })}` : 'Nessun controllo ancora'}</span></div>
      <div class="stats">
        <div class="stat"><span class="small muted">Giro attraverso l'hub</span><b>${num(d.hub_ms)} ms</b></div>
        <div class="stat"><span class="small muted">Database</span><b style=${dbOver ? 'color:var(--danger)' : ''}>${bytes(st?.database_bytes)}</b>
          <span class="small muted">limite ${num(t.database_gb)} GB</span></div>
        <div class="stat"><span class="small muted">File salvati</span><b>${bytes(st?.blob_bytes)}</b><span class="small muted">${num(st?.blob_count)} file</span></div>
        <div class="stat"><span class="small muted">Crescita al giorno</span><b style=${growOver ? 'color:var(--danger)' : ''}>${st?.growth_day_bytes === null || st?.growth_day_bytes === undefined ? '–' : bytes(st.growth_day_bytes)}</b>
          <span class="small muted">limite ${num(t.growth_mb_day)} MB</span></div>
      </div>
      ${services.length ? html`<div class="card scroll"><table>
        <thead><tr><th>Modulo</th><th>Memoria</th><th>Processore</th><th>Risposta</th><th>Acceso da</th><th>Riavvii</th></tr></thead>
        <tbody>${services.map(([name, m]) => html`<tr class=${name === this.pick ? 'sel' : ''} @click=${() => this.select(name)}>
          <td>${name.replace(/^hestia[-_]/, '')}</td>
          <td class=${t.memory_mb && m.mem_mb > t.memory_mb ? 'over' : ''}>${num(m.mem_mb)} MB</td>
          <td class=${t.cpu_percent && m.cpu > t.cpu_percent ? 'over' : ''}>${num(m.cpu, 1)}%</td>
          <td class=${t.response_ms && m.ms > t.response_ms ? 'over' : ''}>${num(m.ms)} ms</td>
          <td>${uptime(m.uptime_s)}</td><td>${num(m.restarts)}</td></tr>`)}</tbody></table>
        <div class="small muted" style="margin-top:6px">Limiti: memoria ${num(t.memory_mb)} MB, processore ${num(t.cpu_percent)}%, risposta ${num(t.response_ms)} ms. Oltre il limite arriva un avviso.</div>
      </div>` : html`<hxk-state kind="empty" text="Nessun dato: memoria e processore servono l'accesso in lettura a Docker."></hxk-state>`}
      ${this.pick ? html`<div class="card col">
        <div class="row wrap"><b>${this.pick.replace(/^hestia[-_]/, '')}</b><span class="small muted">ultime 24 ore</span><span class="grow"></span>
          <div class="chips">${METRICS.map(m => html`<button class="chip" aria-pressed=${this.metric === m.id} @click=${() => (this.metric = m.id)}>${m.label}</button>`)}</div></div>
        ${this.chart()}
      </div>` : nothing}
    </div>`;
  }
}
