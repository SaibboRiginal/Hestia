/**
 * <hephaestus-task-panel> — context panel of a task: Panoramica · File · Diff · Dossier · Test · Log · Ramo.
 * Port of the WebUI forge/task-panel.component. Emits 'open-repo' (detail = RepoNav) for commit/compare/branches.
 */
import { LitElement, css, html, nothing, kitStyles, tokens } from '@hestia/webui-sdk';
import { icon } from './icons';
import { ENGINE_LABEL, FILE_STATUS, duration, meta, shortDate } from './models';
import type { ForgeStore, SidePanel } from './store';

const TABS: { id: SidePanel; label: string; icon: string }[] = [
  { id: 'overview', label: 'Panoramica', icon: 'info' }, { id: 'files', label: 'File', icon: 'file' },
  { id: 'diff', label: 'Diff', icon: 'diff' }, { id: 'dossier', label: 'Dossier', icon: 'list' },
  { id: 'tests', label: 'Test', icon: 'flask' }, { id: 'logs', label: 'Log', icon: 'terminal' },
  { id: 'branch', label: 'Ramo', icon: 'branch' },
];

export class HephaestusTaskPanel extends LitElement {
  static properties = { store: { attribute: false }, rev: { type: Number }, onlyPath: { state: true }, doc: { state: true }, note: { state: true } };
  declare store: ForgeStore; declare rev: number; declare onlyPath: string | null; declare doc: string | null; declare note: string;
  private forId: string | null = null;
  constructor() { super(); this.rev = 0; this.onlyPath = null; this.doc = null; this.note = ''; }

  static styles = [tokens, kitStyles, css`
    :host { display: flex; flex-direction: column; min-height: 0; flex: 1; background: var(--bg-subtle); }
    button { font: inherit; background: none; border: 0; color: inherit; cursor: pointer; padding: 0; text-align: left; }
    .tabs { display: flex; flex-wrap: wrap; gap: 2px; padding: 8px 10px; border-bottom: 1px solid var(--border); flex-shrink: 0; }
    .tabs button { display: inline-flex; align-items: center; gap: 5px; height: 28px; padding: 0 9px; border-radius: var(--radius-md); font-size: 12.5px; color: var(--text-2); white-space: nowrap; }
    .tabs button:hover { background: var(--surface-2); color: var(--text); }
    .tabs button.on { background: var(--surface); color: var(--text); font-weight: 500; box-shadow: var(--shadow-1); }
    .tabs i { font-style: normal; font-size: 11px; background: var(--surface-3); border-radius: var(--radius-full); padding: 0 6px; }
    .body { flex: 1; overflow: auto; padding: 14px 16px 24px; font-size: 13px; }
    .kv { display: grid; grid-template-columns: 90px 1fr; gap: 7px 10px; margin: 0; }
    .kv dt { color: var(--text-3); } .kv dd { min-width: 0; word-wrap: break-word; margin: 0; }
    .mono { font-family: var(--font-mono); font-size: 12px; }
    .lnk { color: var(--accent); } .lnk:hover { text-decoration: underline; }
    .a { color: var(--success); font-weight: 600; } .d { color: var(--danger); font-weight: 600; }
    h4 { font-size: 12px; text-transform: uppercase; letter-spacing: .04em; color: var(--text-3); margin: 18px 0 8px; font-weight: 600; }
    .err { display: flex; gap: 6px; margin-top: 12px; padding: 8px 10px; background: var(--danger-soft); color: var(--danger); border-radius: var(--radius-md); white-space: pre-wrap; word-break: break-word; }
    .timeline { list-style: none; display: flex; flex-direction: column; gap: 10px; border-left: 2px solid var(--border); margin: 0 0 0 4px; padding-left: 14px; }
    .timeline li { position: relative; }
    .timeline .dot { position: absolute; left: -20px; top: 4px; width: 10px; height: 10px; border-radius: 50%; background: var(--text-3); border: 2px solid var(--bg-subtle); }
    .dot[data-tone=success] { background: var(--success); } .dot[data-tone=danger] { background: var(--danger); }
    .dot[data-tone=warning] { background: var(--warning); } .dot[data-tone=accent] { background: var(--accent); } .dot[data-tone=info] { background: var(--info); }
    .note { font-size: 12px; color: var(--text-2); font-family: var(--font-mono); word-break: break-word; }
    .notes { display: flex; flex-direction: column; gap: 8px; }
    .nt { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 7px 10px; white-space: pre-wrap; word-break: break-word; }
    .addnote { display: flex; flex-direction: column; gap: 6px; margin-top: 8px; }
    .addnote textarea { resize: vertical; min-height: 48px; width: 100%; }
    .frow { display: flex; align-items: center; gap: 8px; padding: 6px; width: 100%; border-radius: var(--radius-sm); }
    .frow:hover { background: var(--surface-2); }
    .frow .mono { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .st { font: 600 10.5px var(--font-mono); width: 18px; height: 18px; border-radius: 4px; display: grid; place-items: center; background: var(--info-soft); color: var(--info); flex-shrink: 0; }
    .st[data-st=A], .st[data-st='?'] { background: var(--success-soft); color: var(--success); }
    .st[data-st=D] { background: var(--danger-soft); color: var(--danger); }
    .st[data-st=R] { background: var(--warning-soft); color: var(--warning); }
    .cnt { font-size: 12px; white-space: nowrap; }
    .docnav { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 10px; }
    .docnav button { font-size: 12px; padding: 3px 9px; border-radius: var(--radius-full); background: var(--surface-2); color: var(--text-2); }
    .docnav button.on { background: var(--accent-soft); color: var(--accent); font-weight: 500; }
    .docpath { color: var(--text-3); margin-bottom: 10px; }
    .tsum { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; }
    .failed { margin: 0 0 10px 18px; color: var(--danger); }
    .log { font-family: var(--font-mono); font-size: 11.5px; line-height: 1.5; white-space: pre-wrap; word-break: break-word; background: var(--surface);
           border: 1px solid var(--border); border-radius: var(--radius-md); padding: 10px 12px; max-height: 60vh; overflow: auto; margin: 0; }
    .err-log { color: var(--danger); }
    .row-btns { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 14px; }
    p.small { color: var(--text-2); font-size: 12.5px; }
  `];

  private openRepo(detail: Record<string, string>) {
    this.dispatchEvent(new CustomEvent('open-repo', { detail, bubbles: true, composed: true }));
  }

  private overview() {
    const s = this.store, t = s.task!;
    const m = meta(t.state);
    const tot = s.files?.totals;
    const history = [...(t.history ?? [])].reverse();
    return html`
      <dl class="kv">
        <dt>Stato</dt><dd><hxk-badge tone=${m.tone}>${m.label}</hxk-badge></dd>
        <dt>Motore</dt><dd>${ENGINE_LABEL[t.engine ?? ''] ?? t.engine ?? '—'}${t.engine_requested && t.engine_requested !== 'auto' && t.engine_requested !== t.engine
          ? html`<span class="muted"> (richiesto ${t.engine_requested})</span>` : nothing}</dd>
        <dt>Origine</dt><dd>${t.requested_by || 'utente'} via ${t.source || 'hestia'}</dd>
        ${t.services?.length ? html`<dt>Servizi</dt><dd>${t.services.join(', ')}</dd>` : nothing}
        ${t.workdoc ? html`<dt>Dossier</dt><dd><button class="lnk mono" @click=${() => s.setPanel('dossier')}>${t.workdoc}</button></dd>` : nothing}
        ${t.parent_task ? html`<dt>Segue</dt><dd><button class="lnk mono" @click=${() => this.dispatchEvent(new CustomEvent('open-task', { detail: t.parent_task, bubbles: true, composed: true }))}>${t.parent_task.slice(0, 6)}</button></dd>` : nothing}
        ${t.turns ? html`<dt>Turni</dt><dd>${t.turns}</dd>` : nothing}
        ${t.cost_usd != null ? html`<dt>Costo</dt><dd>$${t.cost_usd.toFixed(3)}</dd>` : nothing}
        ${t.engine_ms ? html`<dt>Durata</dt><dd>${duration(t.engine_ms)}</dd>` : nothing}
        ${tot ? html`<dt>Modifiche</dt><dd><button class="lnk" @click=${() => s.setPanel('files')}>${tot.files} file</button> · <b class="a">+${tot.added}</b> <b class="d">−${tot.deleted}</b></dd>` : nothing}
        ${t.tests ? html`<dt>Test</dt><dd><button class="lnk" @click=${() => s.setPanel('tests')}>${t.tests.ok === true ? html`<hxk-icon name="check" size=${14} tone="success"></hxk-icon> passati` : t.tests.ok === false ? html`<hxk-icon name="x" size=${14} tone="danger"></hxk-icon> falliti` : html`<hxk-icon name="minus" size=${14} tone="muted"></hxk-icon> nessun test`}</button></dd>` : nothing}
        ${t.branch ? html`<dt>Ramo</dt><dd><button class="lnk mono" @click=${() => s.setPanel('branch')}>${t.branch}</button></dd>` : nothing}
        ${t.external?.branch ? html`<dt>Consegnato</dt><dd><span class="mono">${t.external.branch}</span> <span class="muted">da ${t.external.by || '?'}</span></dd>` : nothing}
        ${t.merge_sha ? html`<dt>Merge</dt><dd><button class="lnk mono" @click=${() => this.openRepo({ view: 'commit', sha: t.merge_sha! })}>${t.merge_sha.slice(0, 8)}</button></dd>` : nothing}
        <dt>Creato</dt><dd>${shortDate(t.created_at)}</dd>
      </dl>
      ${t.error ? html`<div class="err">${icon('alert', 14)} ${t.error}</div>` : nothing}
      ${t.deploy_plan ? html`<h4>Piano di deploy</h4><p class="small">
        ${t.deploy_plan.restart.length ? html`Riavvio: <b>${t.deploy_plan.restart.join(', ')}</b>. ` : nothing}
        ${t.deploy_plan.rebuild.length ? html`Da ricostruire a mano: <code>up-all.bat --build ${t.deploy_plan.rebuild.join(' ')}</code>. ` : nothing}
        ${t.deploy_plan.restart_self ? 'Hephaestus si riavvia da solo per ultimo. ' : nothing}
        ${!t.deploy_plan.restart.length && !t.deploy_plan.rebuild.length && !t.deploy_plan.restart_self ? 'Nessun servizio da riavviare.' : nothing}</p>` : nothing}
      <h4>Note</h4>
      ${(t.notes ?? []).length ? html`<div class="notes">${(t.notes ?? []).map(n => html`<div>
        <div class="small muted">${n.by} · ${shortDate(n.ts)}</div><div class="nt">${n.text}</div></div>`)}</div>` : html`<div class="small muted">Nessuna nota.</div>`}
      <div class="addnote">
        <textarea rows="2" placeholder="Aggiungi un'analisi o un'indicazione (la usa il motore quando parte o riprova)…"
          .value=${this.note} @input=${(e: any) => (this.note = e.target.value)}></textarea>
        <div><hxk-button size="sm" variant="ghost" icon="plus" ?disabled=${this.note.trim().length < 3} ?loading=${s.busy}
          @click=${async () => { if (await s.addNote(this.note.trim())) this.note = ''; }}>Aggiungi nota</hxk-button></div>
      </div>
      <h4>Cronologia</h4>
      <ol class="timeline">${history.map(h => html`<li><span class="dot" data-tone=${meta(h.state).tone}></span>
        <div><b>${meta(h.state).label}</b>&nbsp; <span class="muted">${shortDate(h.ts)}</span>
          ${h.note ? html`<div class="note">${h.note}</div>` : nothing}</div></li>`)}</ol>`;
  }

  private files() {
    const f = this.store.files;
    if (!f) return html`<hxk-state kind="loading"></hxk-state>`;
    return html`
      ${f.live ? html`<p class="small muted">Modifiche in corso nella cartella di lavoro del task (si aggiornano da sole).</p>` : nothing}
      ${f.files.length ? f.files.map(x => html`<button class="frow" @click=${() => { this.onlyPath = x.path; this.store.setPanel('diff'); }}>
          <span class="st" data-st=${x.status ?? 'M'} title=${FILE_STATUS[x.status ?? 'M'] ?? ''}>${x.status}</span>
          <span class="mono">${x.path}</span>
          <span class="cnt">${x.binary ? 'bin' : x.added !== null ? html`<b class="a">+${x.added}</b> <b class="d">−${x.deleted}</b>` : nothing}</span></button>`)
        : html`<hxk-state kind="empty" text="Nessun file modificato"></hxk-state>`}
      ${f.error ? html`<div class="err">${f.error}</div>` : nothing}`;
  }

  private dossier() {
    const w = this.store.workdoc;
    if (!w) return html`<hxk-state kind="loading"></hxk-state>`;
    if (!w.docs.length) return html`<hxk-state kind="empty" text="Questo task non ha (ancora) un dossier in docs/work."></hxk-state>`;
    const cur = w.docs.find(d => d.path === this.doc) ?? w.docs[0];
    return html`<div class="docnav">${w.docs.map(d => html`<button class=${d === cur ? 'on' : ''} title=${d.path}
        @click=${() => (this.doc = d.path)}>${d.group === 'changed' ? html`<hxk-icon name="edit" size=${12} tone="accent" title="modificato"></hxk-icon> ` : ''}${d.name}</button>`)}</div>
      <div class="docpath mono">${cur.path}</div><hephaestus-md .text=${cur.content}></hephaestus-md>`;
  }

  private tests() {
    const tt = this.store.tests;
    if (!tt) return html`<hxk-state kind="loading"></hxk-state>`;
    if (!tt.ran) return html`<hxk-state kind="empty" text="Test non ancora eseguiti: Forge li esegue dopo il lavoro del motore."></hxk-state>`;
    const keys = Object.keys(tt.summary || {}).filter(k => k !== 'failed_tests');
    const failed: string[] = tt.summary?.['failed_tests'] ?? [];
    return html`<div class="tsum"><hxk-badge tone=${tt.ok === true ? 'success' : tt.ok === false ? 'danger' : 'neutral'}>${tt.ok === true ? 'passati' : tt.ok === false ? 'falliti' : 'nessun test'}</hxk-badge>
        ${keys.map(k => html`<span class="small">${tt.summary[k]} ${k}</span>`)}</div>
      ${failed.length ? html`<ul class="failed">${failed.map(f => html`<li class="mono">${f}</li>`)}</ul>` : nothing}
      <pre class="log">${tt.output}</pre>`;
  }

  private logs() {
    const l = this.store.logs;
    if (!l) return html`<hxk-state kind="loading"></hxk-state>`;
    return html`${l.error ? html`<h4>Errore</h4><pre class="log err-log">${l.error}</pre>` : nothing}
      <h4>Motore</h4><pre class="log">${l.engine || '(vuoto)'}</pre>
      ${l.deploy ? html`<h4>Deploy</h4><pre class="log">${l.deploy}</pre>` : nothing}
      <p class="small muted">${l.hint}</p>`;
  }

  private branch() {
    const t = this.store.task!;
    return html`<dl class="kv">
        <dt>Ramo</dt><dd class="mono">${t.branch || '—'}</dd>
        <dt>Base</dt><dd class="mono">${t.base_branch || '—'}${t.base_sha ? ` @ ${t.base_sha.slice(0, 8)}` : ''}</dd>
        ${t.commit_sha ? html`<dt>Commit</dt><dd><button class="lnk mono" @click=${() => this.openRepo({ view: 'commit', sha: t.commit_sha! })}>${t.commit_sha.slice(0, 8)}</button></dd>` : nothing}
        ${t.merge_sha ? html`<dt>Merge</dt><dd><button class="lnk mono" @click=${() => this.openRepo({ view: 'commit', sha: t.merge_sha! })}>${t.merge_sha.slice(0, 8)}</button></dd>` : nothing}
      </dl>
      <div class="row-btns">
        ${t.branch && t.base_branch && !['rejected', 'no_changes'].includes(t.state) ? html`<hxk-button size="sm"
          @click=${() => this.openRepo({ view: 'compare', base: t.base_branch!, head: t.merge_sha || t.branch! })}>${icon('diff', 14)} Confronta nel repository</hxk-button>` : nothing}
        <hxk-button size="sm" variant="ghost" @click=${() => this.openRepo({ view: 'branches' })}>${icon('branch', 14)} Tutti i rami</hxk-button>
      </div>
      ${t.diff_stat ? html`<h4>Riepilogo</h4><pre class="log">${t.diff_stat}</pre>` : nothing}`;
  }

  render() {
    const s = this.store;
    if (!s?.task) return nothing;
    if (this.forId !== s.selectedId) { this.forId = s.selectedId; this.onlyPath = null; this.doc = null; this.note = ''; }
    const nFiles = s.files?.files?.length ?? 0;
    return html`
      <div class="tabs" role="tablist">${TABS.map(t => html`<button role="tab" class=${s.panel === t.id ? 'on' : ''} title=${t.label}
        @click=${() => s.setPanel(t.id)}>${icon(t.icon, 14)}<span>${t.label}</span>${t.id === 'files' && nFiles ? html`<i>${nFiles}</i>` : nothing}</button>`)}</div>
      <div class="body">${s.panel === 'overview' ? this.overview()
        : s.panel === 'files' ? this.files()
        : s.panel === 'diff' ? (s.files ? html`${this.onlyPath ? html`<button class="lnk" @click=${() => (this.onlyPath = null)}>← Tutti i file</button>` : nothing}
            <hephaestus-diff .diff=${s.files.diff} .only=${this.onlyPath} ?truncated=${!!s.files.truncated}></hephaestus-diff>` : html`<hxk-state kind="loading"></hxk-state>`)
        : s.panel === 'dossier' ? this.dossier()
        : s.panel === 'tests' ? this.tests()
        : s.panel === 'logs' ? this.logs()
        : this.branch()}</div>`;
  }
}
