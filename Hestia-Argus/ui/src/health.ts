/**
 * <argus-health> — "Salute": health per service over time (strip of the last 1/6/24 h), open incidents with
 * what Argus did (alert, repair request, recheck in the agenda, recovery), closed incidents, log viewer with
 * filters, «Ricontrolla» per service. SPEC docs/work/2026-10-18-moduli-core-e-mcp-esterno §A2.
 */
import { HestiaElement, html, css, nothing } from '@hestia/webui-sdk';
import { API, ago, duration, statusOf, stripStyles, when } from './util';

const WINDOWS = [{ value: 60, label: '1 ora' }, { value: 360, label: '6 ore' }, { value: 1440, label: '24 ore' }];
const LEVELS = ['INFO', 'WARNING', 'ERROR', 'CRITICAL'];
const SINCE = [{ value: '30m', label: '30 min' }, { value: '1h', label: '1 ora' }, { value: '6h', label: '6 ore' }, { value: '24h', label: '24 ore' }];
const LEVEL_TONE: Record<string, string> = { INFO: 'info', WARNING: 'warning', ERROR: 'danger', CRITICAL: 'danger' };
/** Incident timeline: action kind → [kit icon, tone] (tone '' = inherit). */
const ACTION_ICON: Record<string, [string, string]> = { detected: ['alert', 'warning'], status: ['arrows-v', 'info'], alert: ['bell', 'warning'],
  remediation: ['wrench', 'accent'], recheck_planned: ['calendar', 'muted'], recheck: ['pulse', 'info'], recovered: ['check-circle', 'success'],
  restart: ['refresh', 'accent'], restart_result: ['pulse', 'info'], gave_up: ['alert', 'danger'] };

export class ArgusHealth extends HestiaElement {
  static properties = { ...HestiaElement.properties, ov: { state: true }, hist: { state: true }, inc: { state: true },
                        error: { state: true }, minutes: { state: true }, busy: { state: true }, logs: { state: true },
                        logErr: { state: true }, logBusy: { state: true }, lf: { state: true }, text: { state: true },
                        showClosed: { state: true } };
  declare ov: any; declare hist: any; declare inc: any; declare error: string; declare minutes: number; declare busy: string;
  declare logs: any[] | null; declare logErr: string; declare logBusy: boolean; declare lf: { service: string; level: string; since: string };
  declare text: string; declare showClosed: boolean;
  static styles = [...HestiaElement.styles, stripStyles, css`
    .head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    .sub { color: var(--text-3); font-size: 13px; }
    section { display: flex; flex-direction: column; gap: 10px; }
    .sec { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    .seg { display: flex; gap: 4px; flex-wrap: wrap; }
    .chip { font: inherit; font-size: 12px; padding: 4px 10px; border-radius: var(--radius-full); border: 1px solid var(--border-strong);
      background: transparent; color: var(--text-2); cursor: pointer; }
    .chip[aria-pressed='true'] { background: var(--accent-soft); color: var(--accent); border-color: transparent; }
    .svc { display: grid; grid-template-columns: minmax(90px, 140px) 1fr auto; gap: 10px; align-items: center; padding: 8px 0;
      border-top: 1px solid var(--border); }
    .svc:first-child { border-top: 0; }
    .svc .name { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
    .svc .right { display: flex; gap: 8px; align-items: center; }
    .axis { display: flex; justify-content: space-between; font-size: 11px; color: var(--text-3); }
    .incident { display: flex; flex-direction: column; gap: 8px; }
    .acts { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
    .acts li { display: flex; gap: 8px; font-size: 13px; }
    .acts .t { color: var(--text-3); font-size: 12px; white-space: nowrap; min-width: 92px; }
    .ko { color: var(--danger); }
    .filters { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
    .filters input { flex: 1; min-width: 140px; }
    .log { display: flex; gap: 8px; align-items: flex-start; padding: 6px 0; border-top: 1px solid var(--border); font-size: 13px; }
    .log:first-child { border-top: 0; }
    .log .msg { font-family: var(--font-mono); font-size: 12px; white-space: pre-wrap; word-break: break-word; }
    .log .t { color: var(--text-3); font-size: 12px; white-space: nowrap; }
    @media (max-width: 600px) {
      .svc { grid-template-columns: 1fr auto; } .svc .bar { grid-column: 1 / -1; grid-row: 2; }
    }
  `];

  constructor() {
    super();
    this.ov = null; this.hist = null; this.inc = null; this.error = ''; this.minutes = 360; this.busy = '';
    this.logs = null; this.logErr = ''; this.logBusy = false; this.lf = { service: '', level: 'WARNING', since: '1h' };
    this.text = ''; this.showClosed = false;
  }

  connectedCallback() {
    super.connectedCallback();
    this.load(); this.loadLogs();
    this.onHost('refresh', () => { this.load(); this.loadLogs(); });
    this.onHost('visible', () => this.load());
  }

  private async load() {
    const [ov, hist, inc] = await Promise.all([
      this.host.api('GET', `${API}/overview`),
      this.host.api('GET', `${API}/history`, { query: { minutes: this.minutes, buckets: 60 } }),
      this.host.api('GET', `${API}/incidents`, { query: { limit: 100 } }),
    ]);
    if (!ov.ok) { this.error = ov.error === 'offline' ? 'Sei offline' : 'Argus non raggiungibile'; return; }
    this.error = ''; this.ov = ov.data;
    if (hist.ok) this.hist = hist.data;
    if (inc.ok) this.inc = inc.data;
  }

  private async loadLogs() {
    this.logBusy = true;
    const q: Record<string, string> = { level: this.lf.level, since: this.lf.since };
    if (this.lf.service) q.service = this.lf.service;
    const r = await this.host.api('GET', `${API}/logs`, { query: q });
    this.logBusy = false;
    if (!r.ok) { this.logErr = 'Log non disponibili'; return; }
    this.logErr = '';
    this.logs = [...(r.data.events || [])].sort((a: any, b: any) => String(b.timestamp).localeCompare(String(a.timestamp)));
  }

  private async recheck(service: string, unhealthy: boolean) {
    if (unhealthy && !(await this.host.confirm(`Ricontrollare ${service}?`,
      'Se non risponde ancora, Argus chiede di nuovo la riparazione a Hephaestus e pianifica il prossimo ricontrollo.',
      { label: 'Ricontrolla' }))) return;
    this.busy = service;
    const r = await this.host.api('POST', `${API}/recheck/${encodeURIComponent(service)}`, { body: { trigger: 'webui' } });
    this.busy = '';
    if (!r.ok) { this.host.toast(r.error === 'unreachable' ? 'Argus non raggiungibile' : 'Ricontrollo non riuscito', 'danger'); return; }
    const h = r.data?.health;
    this.host.toast(r.data?.message || `${service}: ${statusOf(h)[1]}`, h === 'up' ? 'success' : 'warning');
    this.load();
  }

  private setWindow(m: number) { this.minutes = m; this.load(); }
  private setLf(k: 'service' | 'level' | 'since', v: string) { this.lf = { ...this.lf, [k]: v }; this.loadLogs(); }

  private renderIncident(i: any, open: boolean) {
    const [tone, label] = statusOf(i.status);
    return html`<div class="card incident">
      <div class="row wrap"><b>${i.service}</b><hxk-badge tone=${open ? tone : 'success'}>${open ? label : 'risolto'}</hxk-badge>
        <span class="small muted grow">${open ? `da ${duration(i.duration_seconds)}` : `durato ${duration(i.duration_seconds)} · ${when(i.closed_at)}`}</span>
        ${open ? html`<hxk-button size="sm" icon="refresh" ?loading=${this.busy === i.service} @click=${() => this.recheck(i.service, true)}>Ricontrolla</hxk-button>` : nothing}</div>
      ${open && i.error ? html`<div class="small muted">${i.error}</div>` : nothing}
      <ul class="acts">${(i.actions || []).map((a: any) => html`<li><span class="t tnum">${when(a.at)}</span>
        ${((ic: [string, string]) => html`<hxk-icon name=${ic[0]} size=${14} tone=${ic[1]}></hxk-icon>`)(a.ok === false ? ['x-circle', 'danger'] : ACTION_ICON[a.kind] || ['check-circle', 'success'])}<span class=${a.ok === false ? 'ko' : ''}>${a.text}${a.ok === false ? ' — non riuscito' : ''}</span></li>`)}</ul>
    </div>`;
  }

  private renderHistory() {
    const h = this.hist;
    if (!h) return html`<hxk-state kind="loading"></hxk-state>`;
    const names = Object.keys(h.services || {});
    if (!names.length) return html`<hxk-state kind="empty" text="Nessun controllo ancora: Argus raccoglie la storia da quando è partito."></hxk-state>`;
    const bad = (n: string) => h.services[n].status !== 'up';
    names.sort((a, b) => Number(bad(b)) - Number(bad(a)) || a.localeCompare(b));
    const label = WINDOWS.find(w => w.value === h.minutes)?.label || `${h.minutes} min`;
    return html`<div class="card">${names.map(n => {
      const s = h.services[n]; const [tone, lab] = statusOf(s.status);
      return html`<div class="svc">
        <div class="name"><b class="truncate">${n}</b><span class="small muted tnum">${s.uptime_pct == null ? '–' : `${s.uptime_pct}% ok`} · ${ago(s.checked_at)}</span></div>
        <div class="bar" title=${s.error || ''}><div class="strip">${[...String(s.strip || '')].map(c => html`<span class=${c}></span>`)}</div></div>
        <div class="right"><hxk-badge tone=${tone}>${lab}</hxk-badge>
          <hxk-button size="sm" variant="ghost" icon="refresh" ?loading=${this.busy === n} @click=${() => this.recheck(n, s.status !== 'up')}>Ricontrolla</hxk-button></div>
      </div>`;
    })}
      <div class="axis"><span>${label} fa</span><span>adesso</span></div></div>`;
  }

  private renderLogs() {
    const services = Object.keys(this.hist?.services || {}).sort();
    const q = this.text.trim().toLowerCase();
    const rows = (this.logs || []).filter(e => !q || `${e.service} ${e.message}`.toLowerCase().includes(q));
    return html`<section>
      <div class="sec"><h2 class="grow">Log</h2><hxk-button size="sm" variant="ghost" icon="refresh" ?loading=${this.logBusy} @click=${() => this.loadLogs()}>Aggiorna</hxk-button></div>
      <div class="filters">
        <select aria-label="Servizio" .value=${this.lf.service} @change=${(e: any) => this.setLf('service', e.target.value)}>
          <option value="">Tutti i servizi</option>${services.map(s => html`<option value=${s} ?selected=${this.lf.service === s}>${s}</option>`)}</select>
        <select aria-label="Livello minimo" @change=${(e: any) => this.setLf('level', e.target.value)}>
          ${LEVELS.map(l => html`<option value=${l} ?selected=${this.lf.level === l}>da ${l}</option>`)}</select>
        <select aria-label="Periodo" @change=${(e: any) => this.setLf('since', e.target.value)}>
          ${SINCE.map(s => html`<option value=${s.value} ?selected=${this.lf.since === s.value}>ultime ${s.label}</option>`)}</select>
        <input type="search" placeholder="Cerca nel testo" .value=${this.text} @input=${(e: any) => (this.text = e.target.value)}>
      </div>
      ${this.logErr ? html`<hxk-state kind="error" text=${this.logErr} @retry=${() => this.loadLogs()}></hxk-state>`
        : this.logs === null ? html`<hxk-state kind="loading"></hxk-state>`
        : !rows.length ? html`<hxk-state kind="empty" text="Nessun evento con questi filtri."></hxk-state>`
        : html`<div class="card">${rows.slice(0, 300).map(e => html`<div class="log">
            <hxk-badge tone=${LEVEL_TONE[e.level] || 'neutral'}>${e.level}</hxk-badge>
            <div class="grow"><div class="row wrap"><b>${e.service}</b><span class="t tnum">${new Date(e.timestamp).toLocaleString('it-IT', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit' })}</span></div>
              <div class="msg">${e.message}</div></div></div>`)}
            ${rows.length > 300 ? html`<div class="small muted">Mostro i 300 più recenti di ${rows.length}.</div>` : nothing}</div>`}
    </section>`;
  }

  render() {
    if (this.error && !this.ov) return html`<div class="page"><hxk-state kind="offline" text=${this.error} @retry=${() => this.load()}></hxk-state></div>`;
    if (!this.ov) return html`<div class="page"><hxk-state kind="loading"></hxk-state></div>`;
    const ov = this.ov; const open: any[] = this.inc?.open || []; const closed: any[] = this.inc?.recent || [];
    return html`<div class="page">
      <div class="head"><h1>Salute</h1>
        <span class="sub">${ov.last_cycle_at ? `ultimo controllo ${ago(ov.last_cycle_at)}${ov.last_cycle_ms != null ? ` · ${ov.last_cycle_ms} ms` : ''}` : 'primo controllo in corso…'}</span>
        <span class="grow"></span><hxk-button variant="ghost" icon="refresh" @click=${() => { this.load(); this.loadLogs(); }}>Aggiorna</hxk-button></div>
      ${this.error ? html`<hxk-state kind="error" text="${this.error}: mostro gli ultimi dati" @retry=${() => this.load()}></hxk-state>` : nothing}
      <hxk-stat .items=${[
        { label: 'Servizi sani', value: `${ov.healthy}/${ov.total}`, tone: ov.unhealthy ? 'warning' : 'success' },
        { label: 'Non sani', value: ov.unhealthy, tone: ov.unhealthy ? 'danger' : 'neutral' },
        { label: 'Incidenti aperti', value: ov.open_incidents, tone: ov.open_incidents ? 'danger' : 'neutral' },
        { label: 'Controlli', value: ov.cycles, hint: 'Cicli di controllo da quando Argus è partito' },
      ]}></hxk-stat>
      ${open.length ? html`<section><h2>Incidenti aperti</h2>${open.map(i => this.renderIncident(i, true))}</section>` : nothing}
      <section>
        <div class="sec"><h2 class="grow">Servizi nel tempo</h2>
          <div class="seg">${WINDOWS.map(w => html`<button class="chip" aria-pressed=${this.minutes === w.value} @click=${() => this.setWindow(w.value)}>${w.label}</button>`)}</div></div>
        ${this.renderHistory()}
      </section>
      ${closed.length ? html`<section>
        <div class="sec"><h2 class="grow">Registro</h2>
          <hxk-button size="sm" variant="ghost" @click=${() => (this.showClosed = !this.showClosed)}>${this.showClosed ? 'Nascondi' : `Mostra (${closed.length})`}</hxk-button></div>
        ${this.showClosed ? closed.map(i => this.renderIncident(i, false)) : nothing}</section>` : nothing}
      ${this.renderLogs()}
    </div>`;
  }
}
