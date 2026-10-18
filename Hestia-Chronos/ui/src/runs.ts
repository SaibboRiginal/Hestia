/**
 * <chronos-runs> — «Esecuzioni»: every run of the assistant agenda's jobs/tasks (riuscito / fallito / saltato,
 * duration, who started it) and the rules each module registered. «Riprova» = the agenda's run-now action.
 * The calendar stays the WebUI Agenda page. SPEC docs/work/2026-10-18-moduli-core-e-mcp-esterno §A2.
 */
import { HestiaElement, html, css, nothing } from '@hestia/webui-sdk';
import { API, STATUS, ms, retry, when } from './util';

const FILTERS = [{ id: '', label: 'Tutte' }, { id: 'ok', label: 'Riuscite' }, { id: 'failed', label: 'Fallite' }, { id: 'skipped', label: 'Saltate' }];
const PERIODS = [{ h: 24, label: 'Ultime 24 ore' }, { h: 24 * 7, label: 'Ultimi 7 giorni' }, { h: 24 * 30, label: 'Ultimi 30 giorni' }];
const TYPES: Record<string, string> = { job: 'job', task: 'attività', window: 'finestre', event: 'eventi' };

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
    if (!r.ok) { this.error = r.status === 0 ? 'Chronos non raggiungibile' : r.error || 'Chronos non raggiungibile'; return; }
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
          ${row.item_status === 'failed' ? html`<hxk-badge tone="danger" title="Ha superato i tentativi: l'agenda non lo riprova da sola">fermo</hxk-badge>` : nothing}</div>
        <div class="small muted tnum">${when(row.at)} · ${row.owner}${row.duration_ms !== null && row.duration_ms !== undefined ? ` · ${ms(row.duration_ms)}` : ''}
          ${row.manual ? html` · a mano${row.by && row.by !== 'user' ? ` (${row.by})` : ''}` : row.by && row.by !== 'agenda' ? html` · ${row.by}` : nothing}</div>
        ${row.status === 'failed' && row.detail ? html`<div class="det">${row.detail}</div>` : nothing}
        ${this.open === id ? html`<div class="small muted">Chiave <code>${row.key}</code>${row.occurrence && !row.manual ? html` · occorrenza ${when(row.occurrence)}` : nothing}
          ${row.status === 'ok' && row.detail ? html` · risposta <code>${row.detail}</code>` : nothing}</div>` : nothing}
      </div>
      <div class="row">
        ${row.can_run && row.status === 'failed' ? html`<hxk-button size="sm" icon="refresh" ?loading=${this.busy === id} @click=${() => this.run(row)}>Riprova</hxk-button>` : nothing}
        <hxk-button size="sm" variant="ghost" @click=${() => (this.open = this.open === id ? '' : id)}>${this.open === id ? 'Meno' : 'Dettagli'}</hxk-button>
      </div>
    </div>`;
  }

  private renderOwners(owners: any[]) {
    if (!owners?.length) return nothing;
    return html`<hxk-card heading="Regole per modulo" subtitle="Cosa ogni modulo ha registrato nell'agenda dell'assistente">
      <div class="own">${owners.map(o => html`<div class="o">
        <b>${o.owner}</b>
        <div class="small muted">${o.rules} regole · ${Object.entries(o.types || {}).map(([t, n]) => `${n} ${TYPES[t] || t}`).join(', ')}</div>
        <div class="row wrap">
          ${o.active ? html`<hxk-badge tone="success">${o.active} attive</hxk-badge>` : nothing}
          ${o.paused ? html`<hxk-badge tone="warning">${o.paused} in pausa</hxk-badge>` : nothing}
          ${o.failed ? html`<hxk-badge tone="danger">${o.failed} ferme</hxk-badge>` : nothing}
          ${o.user_modified ? html`<hxk-badge tone="info" title="Cambiate da te: il modulo non le sovrascrive">${o.user_modified} cambiate da te</hxk-badge>` : nothing}
        </div></div>`)}</div>
    </hxk-card>`;
  }

  render() {
    if (this.error) return html`<div class="page"><h1>Esecuzioni</h1><hxk-state kind="offline" text=${this.error}></hxk-state></div>`;
    const d = this.data;
    const s = d?.summary;
    return html`<div class="page">
      <div class="head"><h1>Esecuzioni</h1><span class="sub">I job dell'agenda dell'assistente: com'è andata ogni volta</span></div>
      ${s ? html`<hxk-stat .items=${[
        { label: 'Riusciti', value: s.ok, tone: 'success' },
        { label: 'Falliti', value: s.failed, tone: s.failed ? 'danger' : 'neutral', delta: s.failed_items ? `${s.failed_items} fermi` : '' },
        { label: 'Saltati', value: s.skipped },
        { label: 'Durata media', value: s.avg_ms === null ? '–' : ms(s.avg_ms) },
      ]}></hxk-stat>` : nothing}
      <div class="row wrap">
        <div class="chips grow">${FILTERS.map(f => html`<button class="chip" aria-pressed=${this.status === f.id} @click=${() => this.set('status', f.id)}>${f.label}</button>`)}</div>
        <select aria-label="Periodo" @change=${(e: any) => this.set('hours', Number(e.target.value))}>
          ${PERIODS.map(p => html`<option value=${p.h} ?selected=${this.hours === p.h}>${p.label}</option>`)}</select>
        ${d?.owners?.length ? html`<select aria-label="Modulo" @change=${(e: any) => this.set('owner', e.target.value)}>
          <option value="">Tutti i moduli</option>${d.owners.map((o: any) => html`<option value=${o.owner} ?selected=${this.owner === o.owner}>${o.owner}</option>`)}</select>` : nothing}
      </div>
      ${!d ? html`<hxk-state kind="loading"></hxk-state>`
        : d.runs.length ? html`<div class="card">${d.runs.map((r: any) => this.renderRow(r))}</div>`
        : html`<hxk-state kind="empty" text="Nessuna esecuzione in questo periodo"></hxk-state>`}
      ${d ? this.renderOwners(d.owners) : nothing}
      <p class="small muted">Ogni job tiene le sue ultime 50 esecuzioni. Il calendario dell'assistente è in Agenda.</p>
    </div>`;
  }
}
