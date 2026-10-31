/**
 * <hephaestus-repairs> — "Riparazioni": the remediation tasks of Hephaestus (runbook, consent, dry-run,
 * outcome, whether it can be undone, notes). Read only: approving or undoing a repair keeps its consent path
 * (chat / Telegram tools). SPEC docs/work/2026-10-18-moduli-core-e-mcp-esterno §A2.
 */
import { HestiaElement, html, css, nothing } from '@hestia/webui-sdk';
import { API, STATE, CONSENT, when, short } from './util';

const FILTERS = [
  { value: '', label: 'Tutte' }, { value: 'pending_approval', label: 'Da approvare' }, { value: 'failed', label: 'Fallite' },
  { value: 'succeeded', label: 'Riuscite' }, { value: 'rolled_back', label: 'Annullate' }, { value: 'escalated', label: 'Passate a Forge' },
];
const UNDO: Record<string, string> = {
  restored: 'dati ripristinati', cancelled: 'fermata prima di cambiare qualcosa',
  nothing_to_undo: 'niente da ripristinare', failed: 'ripristino non riuscito, si può riprovare',
};

export class HephaestusRepairs extends HestiaElement {
  static properties = { ...HestiaElement.properties, tasks: { state: true }, runbooks: { state: true }, info: { state: true },
                        error: { state: true }, filter: { state: true }, open: { state: true } };
  declare tasks: any[] | null; declare runbooks: Record<string, any>; declare info: any; declare error: string;
  declare filter: string; declare open: string;
  static styles = [...HestiaElement.styles, css`
    .head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    h1 { font-size: 20px; margin: 0; } .sub { color: var(--text-3); font-size: 13px; }
    .t { padding: 12px 0; border-top: 1px solid var(--border); cursor: pointer; }
    .t:first-child { border-top: 0; }
    .top { display: flex; gap: 8px; align-items: flex-start; }
    .meta { display: flex; flex-wrap: wrap; gap: 4px 10px; margin-top: 2px; }
    .det { display: flex; flex-direction: column; gap: 10px; margin-top: 10px; cursor: default; }
    .kv { display: grid; grid-template-columns: max-content 1fr; gap: 4px 12px; font-size: 13px; }
    .kv span:nth-child(odd) { color: var(--text-3); }
    ol { margin: 0; padding-left: 20px; font-size: 13px; } li { margin: 2px 0; }
    .notes { font-size: 13px; display: flex; flex-direction: column; gap: 2px; }
    pre { white-space: pre-wrap; word-break: break-word; background: var(--surface-2); border-radius: var(--radius-sm);
      padding: 8px 10px; font-size: 12px; margin: 0; max-height: 220px; overflow: auto; }
    .note { font-size: 12px; color: var(--text-3); }
    .filter { min-width: 180px; }
    code { font-size: 12px; word-break: break-all; }
  `];
  constructor() { super(); this.tasks = null; this.runbooks = {}; this.info = null; this.error = ''; this.filter = ''; this.open = ''; }

  connectedCallback() { super.connectedCallback(); this.load(); this.onHost('refresh', () => this.load()); }

  private async load() {
    const [t, r, s] = await Promise.all([
      this.host.api('GET', `${API}/tasks`, { query: { limit: 200 } }),
      this.host.api('GET', `${API}/runbooks`),
      this.host.api('GET', `${API}/status`),
    ]);
    if (!t.ok) { this.error = t.status === 0 || !t.error ? 'Hephaestus non raggiungibile' : t.error; return; }
    this.error = '';
    this.tasks = t.data?.tasks || [];
    this.runbooks = Object.fromEntries((r.ok ? r.data?.runbooks || [] : []).map((b: any) => [b.runbook_id, b]));
    this.info = s.ok ? s.data : null;
  }

  private stats() {
    const n = (st: string) => (this.tasks || []).filter(t => t.state === st).length;
    return [
      { label: 'Da approvare', value: n('pending_approval'), tone: n('pending_approval') ? 'warning' : 'neutral' },
      { label: 'Riuscite', value: n('succeeded'), tone: 'success' },
      { label: 'Fallite', value: n('failed'), tone: n('failed') ? 'danger' : 'neutral' },
      { label: 'Annullate', value: n('rolled_back') },
    ];
  }

  private renderDetail(t: any) {
    const rb = this.runbooks[t.runbook_id];
    const res = t.execution_result;
    return html`<div class="det" @click=${(e: Event) => e.stopPropagation()}>
      <div class="kv">
        <span>Runbook</span><span>${rb ? html`<b>${rb.title}</b> · ${rb.summary}` : t.runbook_id || '–'}</span>
        <span>Consenso richiesto</span><span>${rb ? CONSENT[rb.consent_tier] || rb.consent_tier : '–'}</span>
        <span>Prova (dry-run)</span><span>${t.dry_run ? 'sì, nessuna modifica reale' : 'no, esecuzione reale'}</span>
        <span>Ambiente</span><span>${t.environment || '–'}</span>
        <span>Gravità</span><span>${t.severity || '–'}</span>
        <span>Origine</span><span>${t.source || '–'}${t.auto_approve ? ' · auto-approvazione richiesta' : ''}</span>
        <span>Tentativi</span><span>${t.attempts ?? 1}</span>
        <span>Si può annullare</span><span>${t.undoable ? 'sì, i dati cambiati vengono ripristinati' : 'no, non ha cambiato dati da ripristinare'}</span>
        ${t.rollback_result ? html`<span>Annullamento</span><span>${UNDO[t.rollback_result.status] || t.rollback_result.status}</span>` : nothing}
        <span>Branch</span><span><code>${t.branch || '–'}</code></span>
        ${t.forge_task_id ? html`<span>Forge</span><span>passata allo sviluppo: <a href=${this.host.link('sviluppo', { task: t.forge_task_id })} @click=${(e: Event) => { e.preventDefault(); this.host.navigate('sviluppo', { task: t.forge_task_id }); }}>task <code>${short(t.forge_task_id)}</code> in Sviluppo</a></span>` : nothing}
        <span>Id</span><span><code>${t.task_id}</code></span>
      </div>
      ${rb?.steps?.length ? html`<div><div class="small muted">Passi del runbook</div><ol>${rb.steps.map((s: any) => html`<li>${s.title}
        <span class="small muted">· ${s.read_only ? 'sola lettura' : 'modifica'}${s.rollback_checkpoint ? ` · punto di ritorno ${s.rollback_checkpoint}` : ''}</span></li>`)}</ol></div>` : nothing}
      ${(t.notifications || []).length ? html`<div><div class="small muted">Cronologia</div><div class="notes">
        ${t.notifications.map((n: any) => html`<div><span class="muted">${when(n.ts)}</span> · ${n.note}</div>`)}</div></div>` : nothing}
      ${res ? html`<div><div class="small muted">Esito</div><pre>${JSON.stringify(res, null, 2).slice(0, 4000)}</pre></div>` : nothing}
      ${t.state === 'pending_approval' ? html`<p class="note">Per approvarla scrivi a Hestia «approva la riparazione ${t.task_id}» (chat o Telegram).</p>`
        : t.state === 'succeeded' && t.undoable ? html`<p class="note">Per annullarla scrivi a Hestia «annulla la riparazione ${t.task_id}».</p>` : nothing}
    </div>`;
  }

  render() {
    if (this.error) return html`<div class="page"><hxk-state kind="offline" text=${this.error}></hxk-state></div>`;
    if (!this.tasks) return html`<div class="page"><hxk-state kind="loading"></hxk-state></div>`;
    const list = this.tasks.filter(t => !this.filter || t.state === this.filter);
    return html`<div class="page">
      <div class="head"><h1>Riparazioni</h1><span class="sub">Interventi automatici sui servizi, con runbook e consenso</span>
        <span class="grow"></span><hxk-button variant="ghost" icon="refresh" @click=${() => this.load()}>Aggiorna</hxk-button></div>
      <hxk-stat .items=${this.stats()}></hxk-stat>
      ${this.info ? html`<div class="note">Modalità: ${this.info.mode === 'policy_gated_execution' ? 'esecuzione con regole di consenso' : this.info.mode}
        · ${this.info.runbook_count} runbook · in produzione ${this.info.production_execution_allowed ? 'consentita' : 'mai senza di te'}</div>` : nothing}
      <div class="filter"><hxk-field label="Mostra" type="enum" .options=${FILTERS} .value=${this.filter}
        @change=${(e: any) => (this.filter = e.detail || '')}></hxk-field></div>
      ${list.length ? html`<div class="card">${list.map(t => {
        const st = STATE[t.state] || { label: t.state, tone: 'neutral' };
        const rb = this.runbooks[t.runbook_id];
        return html`<div class="t" @click=${() => (this.open = this.open === t.task_id ? '' : t.task_id)}>
          <div class="top"><div class="grow"><b>${t.service}</b> · ${t.issue}</div><hxk-badge tone=${st.tone}>${st.label}</hxk-badge></div>
          <div class="meta small muted"><span>${rb?.title || t.runbook_id}</span><span>${t.dry_run ? 'prova' : 'reale'}</span>
            <span>${when(t.updated_at || t.created_at)}</span>${(t.attempts || 1) > 1 ? html`<span>${t.attempts} tentativi</span>` : nothing}</div>
          ${this.open === t.task_id ? this.renderDetail(t) : nothing}
        </div>`;
      })}</div>`
        : html`<hxk-state kind="empty" text=${this.filter ? 'Nessuna riparazione in questo stato.' : 'Nessuna riparazione: i servizi non ne hanno avuto bisogno.'}></hxk-state>`}
    </div>`;
  }
}
