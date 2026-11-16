/**
 * <chronos-runs> — «Esecuzioni»: every run of the assistant agenda's jobs/tasks (riuscito / fallito / saltato,
 * duration, who started it) and the rules each module registered. «Riprova» = the agenda's run-now action.
 * The calendar stays the WebUI Agenda page. SPEC docs/work/2026-10-18-moduli-core-e-mcp-esterno §A2.
 */
import { HestiaElement, html, css, nothing, tr } from '@hestia/webui-sdk';
import { API, STATUS, ms, retry, when } from './util';

const FILTERS = [{ id: '', label: tr('All') }, { id: 'ok', label: tr('Succeeded') }, { id: 'failed', label: tr('f.pl::Failed') }, { id: 'skipped', label: tr('Skipped') }];
const PERIODS = [{ h: 24, label: tr('Last 24 hours') }, { h: 24 * 7, label: tr('Last 7 days') }, { h: 24 * 30, label: tr('Last 30 days') }];
const TYPES: Record<string, string> = { job: 'job', task: tr('activities'), window: 'finestre', event: 'eventi' };

export class ChronosRuns extends HestiaElement {
  static properties = { ...HestiaElement.properties, data: { state: true }, error: { state: true }, status: { state: true },
                        owner: { state: true }, hours: { state: true }, busy: { state: true }, open: { state: true } };
  declare data: any; declare error: string; declare status: string; declare owner: string; declare hours: number;
  declare busy: string; declare open: string;
  static styles = [...HestiaElement.styles, css`
    .head { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
    .sub { color: var(--text-3); font-size: 13px; }
    .chips { display: flex; gap: 6px; flex-wrap: wrap; }
    .chip { font: inherit; font-size: 13px; padding: 4px 10px; border-radius: 99px; border: 1px solid var(--border-strong);
      background: var(--surface); color: var(--text-2); cursor: pointer; }
    .chip[aria-pressed=true] { background: var(--accent-soft); color: var(--accent); border-color: var(--accent); }
    .chip:focus-visible { outline: none; box-shadow: 0 0 0 3px var(--focus-ring); }
    .r { display: flex; gap: 10px; align-items: flex-start; padding: 10px 0; border-top: 1px solid var(--border); }
    .r:first-child { border-top: 0; }
    .t { font-weight: 550; overflow-wrap: anywhere; }
    .det { font-size: 12px; color: var(--text-2); overflow-wrap: anywhere; }
    .tnum { font-variant-numeric: tabular-nums; }
    .own { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 8px; }
    .o { border: 1px solid var(--border); border-radius: var(--radius-md); padding: 8px 10px; display: flex; flex-direction: column; gap: 4px; }
    code { font-size: 12px; background: var(--surface-2); padding: 0 4px; border-radius: 4px; }
    select { max-width: 100%; }
  `];

  constructor() { super(); this.data = null; this.error = ''; this.status = ''; this.owner = ''; this.hours = 24 * 7; this.busy = ''; this.open = ''; }

  connectedCallback() {
    super.connectedCallback();
    const q = this.ctx?.query?.status;   // «Job falliti» widget opens the page filtered
    if (q && FILTERS.some(f => f.id === q)) this.status = q;
    this.load();
    this.onHost('refresh', () => this.load());
    this.addEventListener('retry', () => this.load());
  }

  private async load() {
    const query: Record<string, any> = { hours: this.hours, limit: 200 };
    if (this.status) query.status = this.status;
    if (this.owner) query.owner = this.owner;
    const r = await this.host.api('GET', `${API}/runs`, { query });
    if (!r.ok) { this.error = r.status === 0 ? tr('Chronos not reachable') : r.error || tr('Chronos not reachable'); return; }
    this.error = ''; this.data = r.data;
  }

  private set(k: 'status' | 'owner' | 'hours', v: any) { (this as any)[k] = v; this.data = null; this.load(); }

  private async run(row: any) {
    this.busy = row.key + row.at;
    await retry(this.host, row.key, row.title);
    this.busy = '';
    this.load();
  }

  private renderRow(row: any) {
    const st = STATUS[row.status] || { text: row.status, tone: 'neutral' };
    const id = row.key + row.at;
    return html`<div class="r">
      <div class="grow col" style="gap:3px">
        <div class="row wrap"><span class="t">${row.title}</span><hxk-badge tone=${st.tone}>${st.text}</hxk-badge>
          ${row.item_status === 'failed' ? html`<hxk-badge tone="danger" title=${tr("It used up the attempts: the agenda doesn't retry it by itself")}>${tr("stopped")}</hxk-badge>` : nothing}</div>
        <div class="small muted tnum">${when(row.at)} · ${row.owner}${row.duration_ms !== null && row.duration_ms !== undefined ? ` · ${ms(row.duration_ms)}` : ''}
          ${row.manual ? html` ${tr("· by hand")}${row.by && row.by !== 'user' ? ` (${row.by})` : ''}` : row.by && row.by !== 'agenda' ? html` · ${row.by}` : nothing}</div>
        ${row.status === 'failed' && row.detail ? html`<div class="det">${row.detail}</div>` : nothing}
        ${this.open === id ? html`<div class="small muted">${tr("Key")} <code>${row.key}</code>${row.occurrence && !row.manual ? html` · ${tr("occurrence")} ${when(row.occurrence)}` : nothing}
          ${row.status === 'ok' && row.detail ? html` · ${tr("response")} <code>${row.detail}</code>` : nothing}</div>` : nothing}
      </div>
      <div class="row">
        ${row.can_run && row.status === 'failed' ? html`<hxk-button size="sm" icon="refresh" ?loading=${this.busy === id} @click=${() => this.run(row)}>${tr("Try again")}</hxk-button>` : nothing}
        <hxk-button size="sm" variant="ghost" @click=${() => (this.open = this.open === id ? '' : id)}>${this.open === id ? tr('Less') : tr('Details')}</hxk-button>
      </div>
    </div>`;
  }

  private renderOwners(owners: any[]) {
    if (!owners?.length) return nothing;
    return html`<hxk-card heading=${tr("Rules per module")} subtitle=${tr("What each module recorded in the assistant's agenda")}>
      <div class="own">${owners.map(o => html`<div class="o">
        <b>${o.owner}</b>
        <div class="small muted">${o.rules} ${tr("rules ·")} ${Object.entries(o.types || {}).map(([t, n]) => `${n} ${TYPES[t] || t}`).join(', ')}</div>
        <div class="row wrap">
          ${o.active ? html`<hxk-badge tone="success">${o.active} ${tr("f.pl::active")}</hxk-badge>` : nothing}
          ${o.paused ? html`<hxk-badge tone="warning">${o.paused} ${tr("paused")}</hxk-badge>` : nothing}
          ${o.failed ? html`<hxk-badge tone="danger">${o.failed} ${tr("f.pl::stopped")}</hxk-badge>` : nothing}
          ${o.user_modified ? html`<hxk-badge tone="info" title=${tr("Changed by you: the module doesn't overwrite them")}>${o.user_modified} ${tr("changed by you")}</hxk-badge>` : nothing}
        </div></div>`)}</div>
    </hxk-card>`;
  }

  render() {
    if (this.error) return html`<div class="page"><h1>${tr("Runs")}</h1><hxk-state kind="offline" text=${this.error}></hxk-state></div>`;
    const d = this.data;
    const s = d?.summary;
    return html`<div class="page">
      <div class="head"><h1>${tr("Runs")}</h1><span class="sub">${tr("The jobs of the assistant's agenda: how each run went")}</span></div>
      ${s ? html`<hxk-stat .items=${[
        { label: tr('pl::Succeeded'), value: s.ok, tone: 'success' },
        { label: tr('pl::Failed'), value: s.failed, tone: s.failed ? 'danger' : 'neutral', delta: s.failed_items ? `${s.failed_items} fermi` : '' },
        { label: tr('pl::Skipped'), value: s.skipped },
        { label: tr('Average duration'), value: s.avg_ms === null ? '–' : ms(s.avg_ms) },
      ]}></hxk-stat>` : nothing}
      <div class="row wrap">
        <div class="chips grow">${FILTERS.map(f => html`<button class="chip" aria-pressed=${this.status === f.id} @click=${() => this.set('status', f.id)}>${f.label}</button>`)}</div>
        <select aria-label=${tr("Period")} @change=${(e: any) => this.set('hours', Number(e.target.value))}>
          ${PERIODS.map(p => html`<option value=${p.h} ?selected=${this.hours === p.h}>${p.label}</option>`)}</select>
        ${d?.owners?.length ? html`<select aria-label=${tr("Module")} @change=${(e: any) => this.set('owner', e.target.value)}>
          <option value="">${tr("All modules")}</option>${d.owners.map((o: any) => html`<option value=${o.owner} ?selected=${this.owner === o.owner}>${o.owner}</option>`)}</select>` : nothing}
      </div>
      ${!d ? html`<hxk-state kind="loading"></hxk-state>`
        : d.runs.length ? html`<div class="card">${d.runs.map((r: any) => this.renderRow(r))}</div>`
        : html`<hxk-state kind="empty" text=${tr("No run in this period")}></hxk-state>`}
      ${d ? this.renderOwners(d.owners) : nothing}
      <p class="small muted">${tr("Each job keeps its last 50 runs. The assistant's calendar is in Agenda.")}</p>
    </div>`;
  }
}
