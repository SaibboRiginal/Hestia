/**
 * <metis-improvement> — "Miglioramento": where Hestia does worse according to your grades (weak domains,
 * labels, examples), the datasets built from them and the LoRA training jobs (planned in the agenda window,
 * running, finished). Building a dataset or starting a training stays a chat / agenda action.
 * Training dataset (docs/work/2026-10-30-dataset-allenamento): saved turns and «Da rivedere», the nightly
 * corrections that wait for you (Accetta / Scarta / Correggi with your own answer) and «Esporta», the JSONL zip
 * to download, with names and contacts hidden (default) or in clear: the owner picks at each export.
 * SPEC docs/work/2026-10-18-moduli-core-e-mcp-esterno §A2. Every path is under the api_prefix /api/metis/.
 */
import { HestiaElement, html, css, nothing, locale, tr } from '@hestia/webui-sdk';

const API = '/api/metis';

const JOB: Record<string, { label: string; tone: string }> = {
  scheduled: { label: tr('planned'), tone: 'info' },
  running: { label: tr('running'), tone: 'accent' },
  finished: { label: tr('finished'), tone: 'success' },
  no_training_script: { label: tr('training script missing'), tone: 'warning' },
  schedule_failed: { label: tr('agenda unreachable'), tone: 'danger' },
};

function when(iso?: string | null): string {
  if (!iso) return '–';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '–';
  return d.toLocaleString(locale(), { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false });
}

const pct = (x: number) => `${Math.round((Number(x) || 0) * 100)}%`;
const pairs = (o: Record<string, number> | undefined) => Object.entries(o || {}).sort((a, b) => b[1] - a[1]);

export class MetisImprovement extends HestiaElement {
  static properties = { ...HestiaElement.properties, insights: { state: true }, insightsError: { state: true },
                        jobs: { state: true }, datasets: { state: true }, error: { state: true }, loaded: { state: true },
                        traces: { state: true }, review: { state: true }, editing: { state: true }, busy: { state: true },
                        exports: { state: true } };
  declare insights: any; declare insightsError: string; declare jobs: any; declare datasets: any[];
  declare error: string; declare loaded: boolean; declare traces: any; declare review: any;
  declare editing: string; declare busy: string; declare exports: any[] | null;
  private draft = '';
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
    .was { color: var(--text-3); text-decoration: line-through; }
    .row { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 8px; }
    textarea { width: 100%; min-height: 70px; box-sizing: border-box; margin-top: 6px; font: inherit; }
  `];
  constructor() {
    super(); this.insights = null; this.insightsError = ''; this.jobs = null; this.datasets = []; this.error = ''; this.loaded = false;
    this.traces = null; this.review = null; this.editing = ''; this.busy = ''; this.exports = null;
  }

  connectedCallback() { super.connectedCallback(); this.load(); this.onHost('refresh', () => this.load()); }

  private async load() {
    const [j, i, d, t, r, x] = await Promise.all([
      this.host.api('GET', `${API}/lora/jobs`),
      this.host.api('GET', `${API}/insights`, { query: { limit: 500 } }),
      this.host.api('GET', `${API}/dataset/status`),
      this.host.api('GET', `${API}/traces/status`),
      this.host.api('GET', `${API}/review/pending`, { query: { limit: 10 } }),
      this.host.api('GET', `${API}/export`, { query: { limit: 5 } }),
    ]);
    this.traces = t.ok ? t.data : null;
    this.exports = x.ok ? x.data?.items || [] : null;
    this.review = r.ok ? r.data : null;
    if (!j.ok && !i.ok) { this.error = j.status === 0 || !j.error ? tr('Metis not reachable') : j.error; return; }
    this.error = '';
    this.jobs = j.ok ? j.data : null;
    this.insights = i.ok ? i.data : null;
    this.insightsError = i.ok ? '' : i.error || tr('Ratings not available');
    this.datasets = d.ok ? d.data?.datasets || [] : [];
    this.loaded = true;
  }

  private renderInsights() {
    const x = this.insights;
    if (!x) return html`<hxk-card heading=${tr("Where it goes wrong")}><hxk-state kind="error" text=${this.insightsError}></hxk-state></hxk-card>`;
    const weak = x.weak_domains || [];
    return html`<hxk-card heading=${tr("Where it goes wrong")} subtitle=${tr("From your ratings of the answers (feedback)")}>
      <hxk-stat .items=${[
        { label: tr('Ratings'), value: x.total_feedback ?? 0 },
        { label: tr('Negatives'), value: x.bad_feedback ?? 0, tone: x.bad_feedback ? 'warning' : 'neutral' },
        { label: tr('Negative quota'), value: pct(x.bad_ratio), tone: x.bad_ratio > 0.25 ? 'danger' : 'neutral' },
      ]}></hxk-stat>
      ${weak.length ? weak.map((w: any) => html`<div class="item">
          <div class="top"><b class="grow">${w.domain}</b><hxk-badge tone="warning">${w.bad} ${tr("negatives")}</hxk-badge></div>
          <div class="tags">${pairs(w.labels).map(([k, v]) => html`<hxk-badge>${k} · ${v}</hxk-badge>`)}</div>
          ${(w.samples || []).map((s: any) => html`<div class="sample">
            ${s.user ? html`<div><span class="muted">Tu:</span> ${s.user}</div>` : nothing}
            ${s.assistant ? html`<div><span class="muted">Hestia:</span> ${s.assistant}</div>` : nothing}
            ${s.note ? html`<div class="muted">${tr("Note:")} ${s.note}</div>` : nothing}</div>`)}
        </div>`)
        : html`<hxk-state kind="empty" text=${tr("No weak point: no negative rating.")}></hxk-state>`}
      <p class="note">${tr("Athena uses these weak points to propose improvements (Forge).")}</p>
    </hxk-card>`;
  }

  private async decide(id: string, decision: string, answer = '') {
    this.busy = id;
    const r = await this.host.api('POST', `${API}/review/${encodeURIComponent(id)}`, { body: { decision, answer } });
    this.busy = '';
    if (!r.ok) { this.host.toast(r.error || tr('Not saved'), 'danger'); return; }
    this.editing = ''; this.draft = '';
    this.host.toast(decision === 'reject' ? tr('Discarded') : tr('f::Saved'), 'info');
    this.load();
  }

  private async exportNow(clear: boolean) {
    this.busy = clear ? 'export-clear' : 'export';
    const r = await this.host.api('POST', `${API}/export`, { body: { in_chiaro: clear } });
    this.busy = '';
    if (!r.ok) { this.host.toast(r.error || tr('Export failed'), 'danger'); return; }
    await this.download(r.data.id);
    this.load();
  }

  private async download(id: string) {
    const r = await this.host.api('GET', `${API}/export/${encodeURIComponent(id)}/b64`);
    if (!r.ok) { this.host.toast(tr('I can\'t download it now'), 'warning'); return; }
    const bytes = Uint8Array.from(atob(r.data.data_b64), c => c.charCodeAt(0));
    const url = URL.createObjectURL(new Blob([bytes], { type: r.data.mime }));
    const a = document.createElement('a');
    a.href = url; a.download = r.data.name; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  }

  private renderExport() {
    if (!this.traces) return nothing;
    const list = this.exports || [];
    return html`<hxk-card heading=${tr("Export")} subtitle=${tr("JSONL files (sft, dpo, eval) to train a model wherever you want")}>
      <div class="row">
        <hxk-button variant="primary" icon="download" ?loading=${this.busy === 'export'}
          @click=${() => this.exportNow(false)}>${tr("Download masked")}</hxk-button>
        <hxk-button variant="ghost" icon="download" ?loading=${this.busy === 'export-clear'}
          @click=${() => this.exportNow(true)}>${tr("Download in clear")}</hxk-button></div>
      <p class="note">${tr("Masked: names of people, emails, phones, IBANs and addresses become <PERSONA_1>… In clear: the real data, don't share the file. The turns reviewed and kept or corrected are included.")}</p>
      ${list.map((e: any) => html`<div class="item">
        <div class="top"><div class="grow"><b>${when(e.created_at)}</b>
          <span class="small muted"> · ${e.sft ?? 0} ${tr("examples ·")} ${e.eval ?? 0} ${tr("trial ·")} ${e.dpo ?? 0} ${tr("pairs")}</span></div>
          <hxk-badge tone=${e.masked ? 'info' : 'warning'}>${e.masked ? tr('masked') : tr('in plain text')}</hxk-badge>
          <hxk-button size="sm" variant="ghost" icon="download" @click=${() => this.download(e.id)}>${tr("Download")}</hxk-button></div>
      </div>`)}
    </hxk-card>`;
  }

  private renderTraces() {
    const t = this.traces;
    if (!t) return html`<hxk-card heading=${tr("Training dataset")}><hxk-state kind="error" text=${tr("alt::Archive not reachable")}></hxk-state></hxk-card>`;
    return html`<hxk-card heading=${tr("Training dataset")} subtitle=${tr("Your exchanges with the assistant, saved only here")}>
      <hxk-stat .items=${[
        { label: tr('Saved exchanges'), value: t.traces ?? 0 },
        { label: tr('Last 7 days'), value: t.traces_7d ?? 0 },
        { label: tr('Signals'), value: t.signals ?? 0 },
      ]}></hxk-stat>
      <p class="note">${tr("Last")} ${when(t.last_at)} · ${tr("kept")} ${t.keep_days} ${tr("days. A conversation excluded from history («Don't use for training») or deleted does not stay here.")}</p>
    </hxk-card>`;
  }

  private renderReview() {
    const r = this.review;
    if (!r) return nothing;
    const items = r.items || [];
    return html`<hxk-card heading=${tr("To review")} subtitle=${tr("Night corrections the reviewer is not sure about")}>
      ${items.length ? items.map((x: any) => html`<div class="item">
        <div class="top"><div class="grow small muted">${when(x.at)}${x.reasons?.length ? tr(' · rules {0}', x.reasons.join(', ')) : ''}</div>
          <hxk-badge tone=${x.needs_owner ? 'warning' : 'info'}>${x.needs_owner ? tr('needs you') : pct(x.confidence)}</hxk-badge></div>
        <div class="sample"><div><span class="muted">Tu:</span> ${x.user}</div>
          <div class=${x.fixed ? 'was' : ''}><span class="muted">Hestia:</span> ${x.answer}</div>
          ${x.fixed ? html`<div><span class="muted">${tr("Fixed:")}</span> ${x.fixed}</div>` : nothing}
          ${x.remove?.length ? html`<div class="muted">${tr("To remove:")} ${x.remove.join(', ')}</div>` : nothing}</div>
        ${this.editing === x.trace_id ? html`<textarea placeholder=${tr("The right answer")} .value=${this.draft}
            @input=${(e: Event) => { this.draft = (e.target as HTMLTextAreaElement).value; }}></textarea>
          <div class="row"><hxk-button variant="primary" ?loading=${this.busy === x.trace_id}
              @click=${() => this.decide(x.trace_id, 'edit', this.draft)}>${tr("Save")}</hxk-button>
            <hxk-button variant="ghost" @click=${() => { this.editing = ''; }}>${tr("Cancel")}</hxk-button></div>`
        : html`<div class="row">
          ${x.needs_owner ? nothing : html`<hxk-button variant="primary" icon="check" ?loading=${this.busy === x.trace_id}
            @click=${() => this.decide(x.trace_id, 'accept')}>${tr("Accept")}</hxk-button>`}
          <hxk-button variant="ghost" icon="edit" @click=${() => { this.editing = x.trace_id; this.draft = x.fixed || x.answer || ''; }}>${tr("I'll fix it")}</hxk-button>
          <hxk-button variant="ghost" icon="x" @click=${() => this.decide(x.trace_id, 'reject')}>${tr("Discard")}</hxk-button></div>`}
      </div>`) : html`<hxk-state kind="empty" text=${tr("Nothing to review.")}></hxk-state>`}
    </hxk-card>`;
  }

  private renderDatasets() {
    if (!this.datasets.length) return nothing;
    return html`<hxk-card heading=${tr("Dataset")} subtitle=${tr("Good examples collected for training (until Metis restarts)")}>
      ${this.datasets.map(d => html`<div class="item">
        <div class="top"><b class="grow">${d.name}</b><span class="small muted">${when(d.created_at)}</span></div>
        <div class="small muted">${d.total_kept ?? 0} ${tr("examples kept out of")} ${d.total_fetched ?? 0}
          · ${d.skipped_duplicate ?? 0} ${tr("duplicates ·")} ${d.skipped_no_payload ?? 0} ${tr("no text")}</div>
        <div class="tags">${pairs(d.domains).map(([k, v]) => html`<hxk-badge>${k} · ${v}</hxk-badge>`)}</div>
      </div>`)}
    </hxk-card>`;
  }

  private renderJobs() {
    const j = this.jobs;
    if (!j) return html`<hxk-card heading=${tr("LoRA training")}><hxk-state kind="error" text=${tr("Training list not available")}></hxk-state></hxk-card>`;
    const jobs = j.jobs || [];
    return html`<hxk-card heading=${tr("LoRA training")} subtitle=${tr("The ones not asked by you start in the agenda's night window")}>
      ${jobs.length ? jobs.map((x: any) => {
        const st = JOB[x.status] || { label: x.status || '?', tone: 'neutral' };
        return html`<div class="item">
          <div class="top"><div class="grow"><b>${x.adapter_name || x.dataset_name || x.job_id}</b></div><hxk-badge tone=${st.tone}>${st.label}</hxk-badge></div>
          <div class="small muted">${"dataset"} ${x.dataset_name || '–'}${x.base_model ? ` · base ${x.base_model}` : ''}
            ${tr("· asked by")} ${x.requested_by || '–'}${x.status === 'scheduled' && x.start_at ? tr(' · starts {0}', when(x.start_at)) : ''}
            · ${tr('updated {0}', when(x.updated_at))}</div>
        </div>`;
      }) : html`<hxk-state kind="empty" text=${tr("No training yet.")}></hxk-state>`}
      <p class="note">${tr("Move or cancel a scheduled training: from Hestia's agenda (window «")}${j.window || 'metis.training'}»).</p>
    </hxk-card>`;
  }

  render() {
    if (this.error) return html`<div class="page"><hxk-state kind="offline" text=${this.error}></hxk-state></div>`;
    if (!this.loaded) return html`<div class="page"><hxk-state kind="loading"></hxk-state></div>`;
    return html`<div class="page">
      <div class="head"><h1>${tr("Improvement")}</h1><span class="sub">${tr("How Hestia learns from your ratings")}</span><span class="grow"></span>
        <hxk-button variant="ghost" icon="refresh" @click=${() => this.load()}>${tr("Refresh")}</hxk-button></div>
      ${this.renderTraces()}${this.renderReview()}${this.renderExport()}${this.renderInsights()}${this.renderDatasets()}${this.renderJobs()}
    </div>`;
  }
}
