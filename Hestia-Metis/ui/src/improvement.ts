/**
 * <metis-improvement> — "Miglioramento": where Hestia does worse according to your grades (weak domains,
 * labels, examples), the datasets built from them and the LoRA training jobs (planned in the agenda window,
 * running, finished). Read only: building a dataset or starting a training stays a chat / agenda action.
 * SPEC docs/work/2026-10-18-moduli-core-e-mcp-esterno §A2. Every path is under the api_prefix /api/metis/.
 */
import { HestiaElement, html, css, nothing } from '@hestia/webui-sdk';

const API = '/api/metis';

const JOB: Record<string, { label: string; tone: string }> = {
  scheduled: { label: 'pianificato', tone: 'info' },
  running: { label: 'in corso', tone: 'accent' },
  finished: { label: 'finito', tone: 'success' },
  no_training_script: { label: 'script di training assente', tone: 'warning' },
  schedule_failed: { label: 'agenda non raggiungibile', tone: 'danger' },
};

function when(iso?: string | null): string {
  if (!iso) return '–';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '–';
  return d.toLocaleString('it-IT', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false });
}

const pct = (x: number) => `${Math.round((Number(x) || 0) * 100)}%`;
const pairs = (o: Record<string, number> | undefined) => Object.entries(o || {}).sort((a, b) => b[1] - a[1]);

export class MetisImprovement extends HestiaElement {
  static properties = { ...HestiaElement.properties, insights: { state: true }, insightsError: { state: true },
                        jobs: { state: true }, datasets: { state: true }, error: { state: true }, loaded: { state: true } };
  declare insights: any; declare insightsError: string; declare jobs: any; declare datasets: any[];
  declare error: string; declare loaded: boolean;
  static styles = [...HestiaElement.styles, css`
    .head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    h1 { font-size: 20px; margin: 0; } h2 { font-size: 15px; margin: 0 0 8px; }
    .sub { color: var(--text-3); font-size: 13px; }
    .item { padding: 10px 0; border-top: 1px solid var(--border); }
    .item:first-of-type { border-top: 0; }
    .top { display: flex; gap: 8px; align-items: flex-start; }
    .tags { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px; }
    .sample { font-size: 13px; margin-top: 6px; padding-left: 10px; border-left: 2px solid var(--border); }
    .sample div { overflow-wrap: anywhere; }
    .note { font-size: 12px; color: var(--text-3); }
  `];
  constructor() {
    super(); this.insights = null; this.insightsError = ''; this.jobs = null; this.datasets = []; this.error = ''; this.loaded = false;
  }

  connectedCallback() { super.connectedCallback(); this.load(); this.onHost('refresh', () => this.load()); }

  private async load() {
    const [j, i, d] = await Promise.all([
      this.host.api('GET', `${API}/lora/jobs`),
      this.host.api('GET', `${API}/insights`, { query: { limit: 500 } }),
      this.host.api('GET', `${API}/dataset/status`),
    ]);
    if (!j.ok && !i.ok) { this.error = j.status === 0 || !j.error ? 'Metis non raggiungibile' : j.error; return; }
    this.error = '';
    this.jobs = j.ok ? j.data : null;
    this.insights = i.ok ? i.data : null;
    this.insightsError = i.ok ? '' : i.error || 'Voti non disponibili';
    this.datasets = d.ok ? d.data?.datasets || [] : [];
    this.loaded = true;
  }

  private renderInsights() {
    const x = this.insights;
    if (!x) return html`<hxk-card heading="Dove sbaglia"><hxk-state kind="error" text=${this.insightsError}></hxk-state></hxk-card>`;
    const weak = x.weak_domains || [];
    return html`<hxk-card heading="Dove sbaglia" subtitle="Dai tuoi voti alle risposte (feedback)">
      <hxk-stat .items=${[
        { label: 'Voti', value: x.total_feedback ?? 0 },
        { label: 'Negativi', value: x.bad_feedback ?? 0, tone: x.bad_feedback ? 'warning' : 'neutral' },
        { label: 'Quota negativa', value: pct(x.bad_ratio), tone: x.bad_ratio > 0.25 ? 'danger' : 'neutral' },
      ]}></hxk-stat>
      ${weak.length ? weak.map((w: any) => html`<div class="item">
          <div class="top"><b class="grow">${w.domain}</b><hxk-badge tone="warning">${w.bad} negativi</hxk-badge></div>
          <div class="tags">${pairs(w.labels).map(([k, v]) => html`<hxk-badge>${k} · ${v}</hxk-badge>`)}</div>
          ${(w.samples || []).map((s: any) => html`<div class="sample">
            ${s.user ? html`<div><span class="muted">Tu:</span> ${s.user}</div>` : nothing}
            ${s.assistant ? html`<div><span class="muted">Hestia:</span> ${s.assistant}</div>` : nothing}
            ${s.note ? html`<div class="muted">Nota: ${s.note}</div>` : nothing}</div>`)}
        </div>`)
        : html`<hxk-state kind="empty" text="Nessun punto debole: nessun voto negativo."></hxk-state>`}
      <p class="note">Athena usa questi punti deboli per proporre miglioramenti (Forge).</p>
    </hxk-card>`;
  }

  private renderDatasets() {
    if (!this.datasets.length) return nothing;
    return html`<hxk-card heading="Dataset" subtitle="Esempi buoni raccolti per il training (fino al riavvio di Metis)">
      ${this.datasets.map(d => html`<div class="item">
        <div class="top"><b class="grow">${d.name}</b><span class="small muted">${when(d.created_at)}</span></div>
        <div class="small muted">${d.total_kept ?? 0} esempi tenuti su ${d.total_fetched ?? 0}
          · ${d.skipped_duplicate ?? 0} doppioni · ${d.skipped_no_payload ?? 0} senza testo</div>
        <div class="tags">${pairs(d.domains).map(([k, v]) => html`<hxk-badge>${k} · ${v}</hxk-badge>`)}</div>
      </div>`)}
    </hxk-card>`;
  }

  private renderJobs() {
    const j = this.jobs;
    if (!j) return html`<hxk-card heading="Training LoRA"><hxk-state kind="error" text="Elenco training non disponibile"></hxk-state></hxk-card>`;
    const jobs = j.jobs || [];
    return html`<hxk-card heading="Training LoRA" subtitle="Quelli non chiesti da te partono nella finestra notturna dell'agenda">
      ${jobs.length ? jobs.map((x: any) => {
        const st = JOB[x.status] || { label: x.status || '?', tone: 'neutral' };
        return html`<div class="item">
          <div class="top"><div class="grow"><b>${x.adapter_name || x.dataset_name || x.job_id}</b></div><hxk-badge tone=${st.tone}>${st.label}</hxk-badge></div>
          <div class="small muted">dataset ${x.dataset_name || '–'}${x.base_model ? ` · base ${x.base_model}` : ''}
            · chiesto da ${x.requested_by || '–'}${x.status === 'scheduled' && x.start_at ? ` · parte ${when(x.start_at)}` : ''}
            · aggiornato ${when(x.updated_at)}</div>
        </div>`;
      }) : html`<hxk-state kind="empty" text="Nessun training ancora."></hxk-state>`}
      <p class="note">Spostare o annullare un training pianificato: dall'agenda di Hestia (finestra «${j.window || 'metis.training'}»).</p>
    </hxk-card>`;
  }

  render() {
    if (this.error) return html`<div class="page"><hxk-state kind="offline" text=${this.error}></hxk-state></div>`;
    if (!this.loaded) return html`<div class="page"><hxk-state kind="loading"></hxk-state></div>`;
    return html`<div class="page">
      <div class="head"><h1>Miglioramento</h1><span class="sub">Come Hestia impara dai tuoi voti</span><span class="grow"></span>
        <hxk-button variant="ghost" icon="refresh" @click=${() => this.load()}>Aggiorna</hxk-button></div>
      ${this.renderInsights()}${this.renderDatasets()}${this.renderJobs()}
    </div>`;
  }
}
