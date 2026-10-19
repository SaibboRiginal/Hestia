/**
 * <hephaestus-sviluppo> — "Sviluppo": Forge tasks and the Hestia repository, Codex / Claude Code style:
 * left = tasks, centre = the engine conversation (+ ask a change), right = File · Diff · Dossier · Test · Log · Ramo.
 * Ported from the WebUI built-in /forge page (SPEC docs/work/2026-10-18-moduli-core-e-mcp-esterno §A4); calls
 * /api/hephaestus/forge|repo/* directly, polls instead of streaming. «Copia per AI» (§B5): markdown of the chosen
 * tasks (GET forge/tasks/export, same views as the MCP tools forge_tasks / forge_task) to the clipboard or a .md.
 * Deep links: ?task=<id> (short ids too) · ?view=repo.
 */
import { HestiaElement, html, css, nothing } from '@hestia/webui-sdk';
import { icon } from './forge/icons';
import { ForgeStore, Filter } from './forge/store';
import type { RepoNav } from './forge/repo';
import {
  Dossier, ENGINES, ForgeApi, ForgeTask, ago, byModule, copyText, downloadText, engineLabel, engineOf, errText, meta,
  saveWidth, savedWidth, sourceLabel,
} from './forge/models';
import { PHASE, when } from './util';

const FILTERS: { id: Filter; label: string }[] = [
  { id: 'all', label: 'Tutti' }, { id: 'open', label: 'Aperti' }, { id: 'modules', label: 'Dai moduli' },
  { id: 'done', label: 'Applicati' }, { id: 'failed', label: 'Non riusciti' },
];

type Size = 'wide' | 'mid' | 'phone';

export class HephaestusSviluppo extends HestiaElement {
  static properties = {
    ...HestiaElement.properties,
    rev: { state: true }, mode: { state: true }, size: { state: true }, centerTab: { state: true }, repoNav: { state: true },
    newOpen: { state: true }, dossiers: { state: true }, followUp: { state: true }, startEngine: { state: true },
    followEngine: { state: true }, nReq: { state: true }, nEngine: { state: true }, nServices: { state: true },
    nWorkdoc: { state: true }, picking: { state: true }, picked: { state: true }, exporting: { state: true },
    listW: { state: true }, sideW: { state: true },
  };
  declare rev: number; declare mode: 'tasks' | 'repo'; declare size: Size; declare centerTab: 'chat' | 'details';
  declare repoNav: RepoNav | null; declare newOpen: boolean; declare dossiers: Dossier[]; declare followUp: string;
  declare startEngine: string; declare followEngine: string; declare nReq: string; declare nEngine: string;
  declare nServices: string; declare nWorkdoc: string; declare picking: boolean; declare picked: Set<string>;
  declare exporting: boolean; declare listW: number; declare sideW: number;

  private store!: ForgeStore;
  private ro: ResizeObserver | null = null;
  private stick = true;
  private lastLen = -1;
  private lastQueryTask: string | undefined = undefined;

  constructor() {
    super();
    this.rev = 0; this.mode = 'tasks'; this.size = 'wide'; this.centerTab = 'chat'; this.repoNav = null; this.newOpen = false;
    this.dossiers = []; this.followUp = ''; this.startEngine = ''; this.followEngine = ''; this.nReq = ''; this.nEngine = '';
    this.nServices = ''; this.nWorkdoc = ''; this.picking = false; this.picked = new Set(); this.exporting = false;
    this.listW = savedWidth('forge-list', 300); this.sideW = savedWidth('forge-side', 420);
  }

  static styles = [...HestiaElement.styles, css`
    :host { display: flex; flex-direction: column; flex: 1; min-height: 0; height: 100%; }
    button.plain { font: inherit; background: none; border: 0; color: inherit; cursor: pointer; padding: 0; text-align: left; }
    .phead { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding: 14px 18px 12px; border-bottom: 1px solid var(--border); }
    .ptitle { min-width: 0; flex: 1 1 220px; } .ptitle h1 { font-size: 22px; } .ptitle .sub { color: var(--text-3); font-size: 12.5px; }
    .seg { display: inline-flex; background: var(--surface-2); border-radius: var(--radius-md); padding: 2px; }
    .seg button { font: inherit; border: 0; background: none; cursor: pointer; display: inline-flex; align-items: center; gap: 5px; font-size: 12.5px;
      padding: 4px 10px; border-radius: calc(var(--radius-md) - 2px); color: var(--text-2); }
    .seg button.on { background: var(--surface); color: var(--text); box-shadow: var(--shadow-1); font-weight: 500; }
    .layout { flex: 1; min-height: 0; display: grid; }
    .layout[data-size=phone] { grid-template-columns: 1fr; }
    .layout[data-size=phone].has-sel .list { display: none; }
    .layout[data-size=phone]:not(.has-sel) .center-col { display: none; }
    .list { position: relative; border-right: 1px solid var(--border); display: flex; flex-direction: column; min-height: 0; background: var(--bg-subtle); }
    .grip { position: absolute; top: 0; bottom: 0; width: 6px; cursor: col-resize; z-index: 2; touch-action: none; }
    .grip:hover { background: var(--accent-soft); }
    .list > .grip { right: -3px; } .side > .grip { left: -3px; }
    .lhead { padding: 10px 10px 6px; display: flex; flex-direction: column; gap: 8px; }
    .search { position: relative; } .search .ic, .search hxk-icon { position: absolute; left: 10px; top: 50%; transform: translateY(-50%); color: var(--text-3); }
    .search input { padding-left: 32px; height: 34px; width: 100%; }
    .chips { display: flex; gap: 4px; flex-wrap: wrap; align-items: center; }
    .chips button { font: inherit; border: 0; cursor: pointer; font-size: 12px; padding: 3px 10px; border-radius: var(--radius-full); color: var(--text-2); background: var(--surface-2); display: inline-flex; gap: 5px; align-items: center; }
    .chips button.on { background: var(--accent-soft); color: var(--accent); font-weight: 500; }
    .chips i { font-style: normal; font-size: 10.5px; background: var(--accent); color: var(--accent-contrast); border-radius: var(--radius-full); padding: 0 5px; }
    .paused { display: flex; gap: 8px; margin: 0 10px 6px; padding: 8px 10px; border-radius: var(--radius-md); background: var(--warning-soft); font-size: 12.5px; color: var(--text-2); line-height: 1.4; }
    .paused b { color: var(--text); margin-right: 4px; }
    .pickbar { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin: 0 10px 6px; padding: 6px 8px; border-radius: var(--radius-md); background: var(--accent-soft); font-size: 12.5px; }
    .rows { flex: 1; overflow: auto; padding: 4px 6px 16px; display: flex; flex-direction: column; gap: 1px; }
    .lerr { display: flex; gap: 6px; font-size: 12.5px; color: var(--danger); padding: 8px; }
    .trow { display: flex; gap: 10px; padding: 9px 10px; border-radius: var(--radius-md); width: 100%; align-items: flex-start; }
    .trow:hover { background: var(--surface-2); }
    .trow.on { background: var(--surface); box-shadow: var(--shadow-1); }
    .trow input[type=checkbox] { margin-top: 3px; accent-color: var(--accent); width: 16px; height: 16px; flex-shrink: 0; }
    .sdot { width: 8px; height: 8px; border-radius: 50%; background: var(--text-3); flex-shrink: 0; margin-top: 6px; }
    .sdot[data-tone=success] { background: var(--success); } .sdot[data-tone=danger] { background: var(--danger); }
    .sdot[data-tone=warning] { background: var(--warning); } .sdot[data-tone=accent] { background: var(--accent); } .sdot[data-tone=info] { background: var(--info); }
    .sdot.pulse { animation: pulse 1.4s infinite; } @keyframes pulse { 50% { opacity: .35; } }
    .tmain { min-width: 0; flex: 1; }
    .treq { font-size: 13.5px; color: var(--text); display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; line-height: 1.35; }
    .tmeta { font-size: 11.5px; color: var(--text-3); margin-top: 3px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .tmeta .by { color: var(--accent); }
    .center-col { display: flex; flex-direction: column; min-height: 0; min-width: 0; }
    .thead { display: flex; align-items: flex-start; gap: 10px; padding: 12px 18px 10px; border-bottom: 1px solid var(--border); }
    .ttitle { font-size: 15px; font-weight: 600; line-height: 1.35; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
    .tsub { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-3); margin-top: 4px; min-width: 0; flex-wrap: wrap; }
    .mono { font-family: var(--font-mono); font-size: 11.5px; }
    .acts { display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; flex-shrink: 0; align-items: center; }
    .eng-pick { font-size: 12.5px; height: 30px; width: auto; max-width: 170px; padding: 2px 8px; }
    .ctabs { padding: 8px 18px 0; }
    .chat { flex: 1; overflow: auto; padding: 16px 22px 20px; }
    .summary { display: flex; gap: 10px; padding: 10px 12px; margin-bottom: 14px; border-radius: var(--radius-md); background: var(--accent-soft); font-size: 13.5px; }
    .summary b { display: block; margin-bottom: 3px; }
    .pre-wrap { white-space: pre-wrap; word-break: break-word; }
    .composer { border-top: 1px solid var(--border); padding: 10px 18px 12px; display: flex; flex-direction: column; gap: 8px; background: var(--surface); }
    .composer textarea { resize: vertical; min-height: 52px; width: 100%; }
    .crow { display: flex; align-items: center; gap: 10px; }
    .crow select { font-size: 12.5px; max-width: 180px; width: auto; }
    .hint { font-size: 11.5px; color: var(--text-3); }
    .placeholder { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; padding: 20px; overflow: auto; text-align: center; }
    .placeholder p { max-width: 460px; color: var(--text-3); font-size: 13px; margin: 0; }
    .engines { display: flex; flex-direction: column; gap: 6px; width: min(460px, 100%); font-size: 13px; border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 12px 14px; text-align: left; }
    .eng { display: flex; align-items: center; gap: 8px; min-width: 0; } .eng .sdot { margin-top: 0; }
    .side { position: relative; border-left: 1px solid var(--border); min-height: 0; display: flex; flex-direction: column; }
    dialog { border: 1px solid var(--border); border-radius: var(--radius-lg); background: var(--surface); color: var(--text); padding: 0;
      width: min(560px, calc(100vw - 24px)); max-height: calc(100vh - 32px); box-shadow: var(--shadow-3, 0 10px 40px rgba(0,0,0,.3)); }
    dialog::backdrop { background: var(--overlay, rgba(0,0,0,.4)); }
    .dlg { display: flex; flex-direction: column; gap: 14px; padding: 18px 20px; }
    .dlg header { display: flex; align-items: center; gap: 8px; } .dlg header h2 { flex: 1; }
    .dlg footer { display: flex; justify-content: flex-end; gap: 8px; }
    .two { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
    .fld { display: flex; flex-direction: column; gap: 4px; } .fld label { font-size: 12px; color: var(--text-2); font-weight: 500; }
    .fld .h { font-size: 12px; color: var(--text-3); }
    .fld textarea, .fld input, .fld select { width: 100%; }
    @media (max-width: 860px) {
      .phead { padding: 10px 12px; }
      .thead { padding: 10px 12px; flex-wrap: wrap; } .acts { flex-basis: 100%; justify-content: flex-start; }
      .chat { padding: 12px 12px 16px; } .composer { padding: 8px 12px 10px; } .ctabs { padding: 8px 12px 0; }
      .two { grid-template-columns: 1fr; } .hint { display: none; } .hide-phone { display: none; }
    }
  `];

  connectedCallback() {
    super.connectedCallback();
    this.store = new ForgeStore(this.host, () => { this.rev++; }, id => this.syncUrl(id));
    this.store.start();
    this.onHost('refresh', () => this.store.refresh());
    this.onHost('visible', () => this.store.loadList(true));
    this.ro = new ResizeObserver(() => this.measure());
    this.ro.observe(this);
    this.measure();
    this.applyQuery();
  }
  disconnectedCallback() {
    super.disconnectedCallback();
    this.store?.stop();
    this.ro?.disconnect(); this.ro = null;
  }

  willUpdate(changed: Map<string, unknown>) {
    if (changed.has('ctx') && this.store) this.applyQuery();
  }

  /** ?task / ?view of the link (old /forge links redirect here with the same query). */
  private applyQuery() {
    const q = this.ctx?.query ?? {};
    const view = q['view'] === 'repo' ? 'repo' : 'tasks';
    if (view !== this.mode) this.mode = view;
    const task = q['task'] || undefined;
    if (task === this.lastQueryTask) return;
    this.lastQueryTask = task;
    if (task && task !== this.store.selectedId) this.select(task, false);
    else if (!task && this.store.selectedId && this.size === 'phone') this.select(null, false);
  }

  private syncUrl(id: string | null, view = this.mode) {
    const params: Record<string, string> = {};
    if (id) params['task'] = id;
    if (view === 'repo') params['view'] = 'repo';
    this.lastQueryTask = id || undefined;
    this.host.navigate('sviluppo', params);
  }

  private measure() {
    const w = this.getBoundingClientRect().width || window.innerWidth;
    const size: Size = (this.ctx?.phone && w < 760) || w < 640 ? 'phone' : w >= 1060 ? 'wide' : 'mid';
    if (size !== this.size) this.size = size;
  }

  updated() {
    const chat = this.renderRoot.querySelector('.chat') as HTMLElement | null;
    const len = this.store?.transcript.length ?? 0;
    if (chat && this.stick && len !== this.lastLen) requestAnimationFrame(() => { chat.scrollTop = chat.scrollHeight; });
    this.lastLen = len;
  }

  // ── navigation ─────────────────────────────────────────────────────────
  private select(id: string | null, push = true) {
    this.stick = true; this.lastLen = -1;
    this.centerTab = 'chat';
    this.startEngine = '';
    this.store.select(id);
    if (push) this.syncUrl(id, 'tasks');
  }
  private setMode(m: 'tasks' | 'repo') {
    this.mode = m;
    this.syncUrl(m === 'tasks' ? this.store.selectedId : null, m);
  }
  private openRepo(nav: RepoNav) { this.repoNav = { ...nav }; this.setMode('repo'); }
  private openTask(id: string) { this.mode = 'tasks'; this.select(id); }

  private grip(e: PointerEvent, which: 'list' | 'side') {
    e.preventDefault();
    const start = e.clientX, w0 = which === 'list' ? this.listW : this.sideW;
    const el = e.currentTarget as HTMLElement;
    el.setPointerCapture(e.pointerId);
    const move = (ev: PointerEvent) => {
      const dx = ev.clientX - start;
      if (which === 'list') this.listW = Math.min(520, Math.max(220, w0 + dx));
      else this.sideW = Math.min(1000, Math.max(320, w0 - dx));
    };
    const up = () => {
      el.removeEventListener('pointermove', move); el.removeEventListener('pointerup', up);
      saveWidth(which === 'list' ? 'forge-list' : 'forge-side', which === 'list' ? this.listW : this.sideW);
    };
    el.addEventListener('pointermove', move); el.addEventListener('pointerup', up);
  }

  // ── actions ────────────────────────────────────────────────────────────
  private askHestia() {
    const t = this.store.task;
    this.host.assistant(t ? {
      label: `Sviluppo · ${t.request.slice(0, 60)}`,
      hints: { pagina: 'forge', task: t.id, stato: t.state, workdoc: t.workdoc || '', servizi: (t.services ?? []).join(','), richiesta: t.request.slice(0, 300) },
      suggestions: ['Spiegami cosa ha cambiato questo task', 'Perché è fallito e cosa propongo?', 'Crea uno sviluppo di seguito che…'],
    } : {
      label: 'Sviluppo', hints: { pagina: 'forge' },
      suggestions: ['Aggiungi a Hestia un comando che…', 'Correggi questo problema: …', 'Cosa sta sviluppando Forge adesso?'],
    });
  }

  private async togglePause(paused: boolean) {
    if (paused || await this.host.confirm('Riprendere lo sviluppo?', 'I moduli tornano ad avviare task da soli secondo i permessi. I task trattenuti durante la pausa restano da avviare a mano.', { label: 'Riprendi' })) {
      await this.store.setPaused(paused);
    }
  }
  private async approve(t: ForgeTask) {
    const tests = t.tests?.ok === false ? ' Attenzione: i test sono falliti.' : '';
    if (await this.host.confirm('Applicare la modifica?', `Forge fa il merge del ramo e, se configurato, riavvia i servizi.${tests}`, { label: 'Approva e applica' })) {
      this.store.act('approve');
    }
  }
  private start(now = false) {
    const engine = this.startEngine || undefined;
    this.startEngine = '';
    this.store.act('approve', { ...(now ? { now: true } : {}), ...(engine ? { engine } : {}) });
  }
  private async reject() {
    if (await this.host.confirm('Rifiutare il task?', 'Il ramo viene eliminato e la modifica scartata.', { label: 'Rifiuta', danger: true })) this.store.act('reject');
  }
  private async rollback() {
    if (await this.host.confirm('Annullare la modifica?', 'Forge crea un commit di revert del merge e riavvia i servizi coinvolti.', { label: 'Rollback', danger: true })) this.store.act('rollback');
  }
  private async sendFollowUp(t: ForgeTask) {
    const text = this.followUp.trim();
    if (text.length < 8) return;
    if (await this.store.submit({ request: text, parent_task: t.id, engine: this.followEngine || undefined })) this.followUp = '';
  }
  private composerKey(e: KeyboardEvent) {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); const t = this.store.task; if (t) this.sendFollowUp(t); }
  }

  private async openNew() {
    this.newOpen = true;
    await this.updateComplete;
    (this.renderRoot.querySelector('dialog.new') as HTMLDialogElement | null)?.showModal();
    try { this.dossiers = await new ForgeApi(this.host).dossiers(); } catch { this.dossiers = []; }
  }
  private closeNew() {
    (this.renderRoot.querySelector('dialog.new') as HTMLDialogElement | null)?.close();
    this.newOpen = false;
  }
  private async submitNew() {
    const services = this.nServices.split(',').map(s => s.trim().toLowerCase()).filter(Boolean);
    const ok = await this.store.submit({ request: this.nReq.trim(), engine: this.nEngine || undefined, services, workdoc: this.nWorkdoc || undefined });
    if (ok) { this.closeNew(); this.nReq = ''; this.nServices = ''; this.nWorkdoc = ''; this.mode = 'tasks'; }
  }

  // ── Copia per AI (§B5) ────────────────────────────────────────────────
  private togglePick(id: string) {
    const s = new Set(this.picked);
    if (s.has(id)) s.delete(id); else s.add(id);
    this.picked = s;
  }
  private async exportAi(ids: string[], download = false) {
    if (!ids.length) return;
    this.exporting = true;
    try {
      const r = await this.store.api.exportMd(ids);
      const n = r.count === 1 ? '1 task' : `${r.count} task`;
      if (download) { downloadText(r.filename, r.markdown); this.host.toast(`Scaricato ${r.filename} (${n})`, 'success'); }
      else if (await copyText(r.markdown)) {
        this.host.toast(`Copiato per AI: ${n}. Incollalo nella chat dell'altra AI.`, 'success',
          { label: 'Scarica .md', run: () => downloadText(r.filename, r.markdown) });
      } else { downloadText(r.filename, r.markdown); this.host.toast(`Appunti non disponibili: scaricato ${r.filename}`, 'info'); }
      if (r.missing?.length) this.host.toast(`Non trovati: ${r.missing.join(', ')}`, 'warning');
    } catch (e) {
      this.host.toast(errText(e, 'Esportazione non riuscita'), 'danger');
    } finally {
      this.exporting = false;
    }
  }

  // ── render ─────────────────────────────────────────────────────────────
  private header() {
    const s = this.store, st = s.status, c = s.counts;
    const sub = c.review ? `${c.review} da rivedere · Forge sviluppa Hestia su rami separati` : 'Forge sviluppa Hestia su rami separati: niente cambia finché non approvi';
    return html`<div class="phead">
      <div class="ptitle"><h1>Sviluppo</h1><div class="sub">${sub}</div></div>
      <div class="seg" role="tablist">
        <button class=${this.mode === 'tasks' ? 'on' : ''} @click=${() => this.setMode('tasks')}>${icon('terminal', 14)} Task</button>
        <button class=${this.mode === 'repo' ? 'on' : ''} @click=${() => this.setMode('repo')}>${icon('branch', 14)} Repository</button>
      </div>
      ${st ? html`<hxk-button variant=${st.paused ? 'primary' : 'ghost'} icon=${st.paused ? 'play' : 'pause'} ?loading=${s.busy}
        title=${st.paused ? 'Riprendi lo sviluppo automatico' : 'Metti in pausa: nessun task parte da solo'}
        @click=${() => this.togglePause(!st.paused)}>${st.paused ? 'Riprendi' : 'Pausa'}</hxk-button>` : nothing}
      <hxk-button variant="ghost" icon="refresh" title="Aggiorna" @click=${() => this.store.refresh()}></hxk-button>
      ${this.mode === 'tasks' ? html`<hxk-button variant=${this.picking ? 'primary' : 'ghost'} title="Scegli dei task e copiali per un'altra AI (markdown)"
        @click=${() => { this.picking = !this.picking; this.picked = new Set(); }}>${icon('copy', 15)} <span class="hide-phone">Copia per AI</span></hxk-button>` : nothing}
      <hxk-button variant="ghost" icon="sparkle" title="Descrivi a Hestia cosa serve: propone o crea lo sviluppo" @click=${() => this.askHestia()}><span class="hide-phone">Chiedi a Hestia</span></hxk-button>
      <hxk-button variant="primary" icon="plus" @click=${() => this.openNew()}>Nuovo sviluppo</hxk-button>
    </div>`;
  }

  private list() {
    const s = this.store;
    const visible = s.visible;
    return html`<aside class="list">
      ${this.size !== 'phone' ? html`<div class="grip" @pointerdown=${(e: PointerEvent) => this.grip(e, 'list')}></div>` : nothing}
      <div class="lhead">
        <div class="search">${icon('search', 15)}<input placeholder="Cerca task…" .value=${s.search}
          @input=${(e: any) => { s.search = e.target.value; this.rev++; }}></div>
        <div class="chips">${FILTERS.map(f => html`<button class=${s.filter === f.id ? 'on' : ''} @click=${() => { s.filter = f.id; this.rev++; }}>${f.label}
          ${f.id === 'open' && s.counts.open ? html`<i>${s.counts.open}</i>` : nothing}</button>`)}</div>
      </div>
      ${s.status?.paused ? html`<div class="paused">${icon('pause', 14)}<div><b>Sviluppo in pausa</b> Nessun task parte da solo: quelli proposti restano qui finché premi Avvia.</div></div>` : nothing}
      ${this.picking ? html`<div class="pickbar">
        <span class="grow">${this.picked.size ? `${this.picked.size} scelti` : 'Scegli i task da copiare'}</span>
        <button class="plain" @click=${() => { this.picked = new Set(visible.map(t => t.id)); }}>Tutti</button>
        <hxk-button size="sm" variant="primary" ?disabled=${!this.picked.size} ?loading=${this.exporting} @click=${() => this.exportAi([...this.picked])}>${icon('copy', 14)} Copia</hxk-button>
        <hxk-button size="sm" variant="ghost" ?disabled=${!this.picked.size || this.exporting} title="Scarica come file .md" @click=${() => this.exportAi([...this.picked], true)}>${icon('download', 14)}</hxk-button>
        <hxk-button size="sm" variant="ghost" icon="x" title="Annulla" @click=${() => { this.picking = false; this.picked = new Set(); }}></hxk-button>
      </div>` : nothing}
      <div class="rows">
        ${s.loading && !s.tasks.length ? html`<hxk-state kind="loading"></hxk-state>` : nothing}
        ${s.error && !s.tasks.length ? html`<hxk-state kind="offline" text=${s.error} @retry=${() => s.loadList()}></hxk-state>`
          : s.error ? html`<div class="lerr">${icon('alert', 14)} ${s.error}</div>` : nothing}
        ${visible.map(t => {
          const m = meta(t.state);
          return html`<button class="plain trow ${s.selectedId === t.id ? 'on' : ''}"
              @click=${() => this.picking ? this.togglePick(t.id) : this.select(t.id)}>
            ${this.picking ? html`<input type="checkbox" .checked=${this.picked.has(t.id)} tabindex="-1" @click=${(e: Event) => e.preventDefault()}>`
              : html`<span class="sdot ${['running', 'merging', 'approved'].includes(t.state) ? 'pulse' : ''}" data-tone=${m.tone}></span>`}
            <div class="tmain"><div class="treq">${t.request}</div>
              <div class="tmeta">${m.label} · <span class=${byModule(t) ? 'by' : ''}>${sourceLabel(t.source)}</span> · ${engineOf(t)} · ${ago(t.created_at)}${t.parent_task ? html` · <span title="Segue un task precedente">↳</span>` : nothing}</div>
            </div></button>`;
        })}
        ${!visible.length && !s.loading && !s.error ? html`<hxk-state kind="empty"
          text=${s.tasks.length ? 'Nessun task con questo filtro.' : 'Nessun task. Chiedi a Forge di sviluppare qualcosa: lavora su un ramo separato e niente cambia finché non approvi.'}></hxk-state>` : nothing}
      </div>
    </aside>`;
  }

  private engineSelect(value: string, set: (v: string) => void, emptyLabel = 'Predefinito', cls = '') {
    return html`<select class=${cls} title="Chi lo sviluppa" @change=${(e: any) => set(e.target.value)}>
      ${ENGINES.map(e => html`<option value=${e} ?selected=${e === value}>${e ? engineLabel(e) : emptyLabel}</option>`)}</select>`;
  }

  private actions(t: ForgeTask) {
    const s = this.store;
    const pick = () => this.engineSelect(this.startEngine, v => (this.startEngine = v), 'Motore proposto', 'eng-pick');
    const rej = html`<hxk-button size="sm" variant="ghost" icon="x" @click=${() => this.reject()}>Rifiuta</hxk-button>`;
    return html`<div class="acts">
      ${t.state === 'proposed' ? html`${pick()}<hxk-button size="sm" variant="primary" icon="play" ?loading=${s.busy} @click=${() => this.start()}>Avvia</hxk-button>${rej}` : nothing}
      ${t.state === 'scheduled' ? html`${pick()}<hxk-button size="sm" variant="primary" icon="play" ?loading=${s.busy} title="Non aspettare la finestra Claude" @click=${() => this.start(true)}>Avvia ora</hxk-button>${rej}` : nothing}
      ${t.state === 'awaiting_review' ? html`<hxk-button size="sm" variant="primary" icon="check" ?loading=${s.busy} @click=${() => this.approve(t)}>Approva e applica</hxk-button>${rej}` : nothing}
      ${t.state === 'merged' || t.state === 'deployed' ? html`<hxk-button size="sm" variant="ghost" icon="undo" @click=${() => this.rollback()}>Rollback</hxk-button>` : nothing}
      ${['failed', 'no_changes', 'rejected', 'rolled_back'].includes(t.state) ? html`<hxk-button size="sm" icon="refresh" ?loading=${s.busy} @click=${() => s.act('retry')}>Riprova</hxk-button>` : nothing}
      <hxk-button size="sm" variant="ghost" ?loading=${this.exporting} title="Copia questo task per un'altra AI (markdown)" @click=${() => this.exportAi([t.id])}>${icon('copy', 14)}</hxk-button>
    </div>`;
  }

  private panel() {
    return html`<hephaestus-task-panel .store=${this.store} .rev=${this.rev}
      @open-repo=${(e: CustomEvent) => this.openRepo(e.detail)} @open-task=${(e: CustomEvent) => this.openTask(e.detail)}></hephaestus-task-panel>`;
  }

  private center() {
    const s = this.store, t = s.task;
    if (!t) return this.placeholder();
    const m = meta(t.state);
    const working = s.active || s.transcriptLive;
    return html`
      <div class="thead">
        ${this.size === 'phone' ? html`<hxk-button variant="ghost" size="sm" title="Indietro" @click=${() => this.select(null)}>${icon('arrow-left', 15)}</hxk-button>` : nothing}
        <div class="grow">
          <div class="ttitle" title=${t.request}>${t.request}</div>
          <div class="tsub"><hxk-badge tone=${m.tone}>${m.label}</hxk-badge><span class="mono">${t.id.slice(0, 6)}</span> · ${engineOf(t)}
            · <span title=${t.requested_by || ''}>${byModule(t) ? 'proposto da ' + sourceLabel(t.source) : 'chiesto da te'}</span>
            ${t.workdoc ? html` · <span class="mono truncate">${t.workdoc}</span>` : nothing}</div>
        </div>
        ${this.actions(t)}
      </div>
      ${this.size !== 'wide' ? html`<div class="ctabs"><div class="seg">
        <button class=${this.centerTab === 'chat' ? 'on' : ''} @click=${() => { this.centerTab = 'chat'; this.lastLen = -1; }}>${icon('chat', 14)} Conversazione</button>
        <button class=${this.centerTab === 'details' ? 'on' : ''} @click=${() => (this.centerTab = 'details')}>${icon('info', 14)} Dettagli</button></div></div>` : nothing}
      ${this.size === 'wide' || this.centerTab === 'chat' ? html`
        <div class="chat" @scroll=${(e: Event) => { const el = e.currentTarget as HTMLElement; this.stick = el.scrollHeight - el.scrollTop - el.clientHeight < 80; }}>
          ${t.summary && !s.active ? html`<div class="summary">${icon('sparkle', 15)}<div><b>Riepilogo del motore</b><div class="pre-wrap">${t.summary}</div></div></div>` : nothing}
          <hephaestus-transcript .events=${s.transcript} ?working=${working}></hephaestus-transcript>
        </div>
        <div class="composer">
          <textarea rows="2" .value=${this.followUp} @input=${(e: any) => (this.followUp = e.target.value)} @keydown=${(e: KeyboardEvent) => this.composerKey(e)}
            placeholder="Chiedi una modifica a questo lavoro… (nuovo task che continua lo stesso dossier)"></textarea>
          <div class="crow">${this.engineSelect(this.followEngine, v => (this.followEngine = v))}
            <span class="hint">Ctrl+Invio per inviare</span><span class="grow"></span>
            <hxk-button size="sm" variant="primary" ?disabled=${this.followUp.trim().length < 8} ?loading=${s.busy} @click=${() => this.sendFollowUp(t)}>${icon('send', 14)} Invia</hxk-button>
          </div>
        </div>` : this.panel()}`;
  }

  private placeholder() {
    const st = this.store.status, b = this.store.budget;
    const ph = b ? PHASE[b.phase] || { label: b.phase, tone: 'neutral' } : null;
    return html`<div class="placeholder">
      ${icon('terminal', 26)}<h3>Seleziona un task</h3>
      <p>Qui vedi la conversazione completa del motore (ragionamento, comandi, file letti e modificati), il diff, il dossier, i test e i log.</p>
      ${st ? html`<div class="engines">
        ${Object.entries(st.engines ?? {}).map(([name, e]) => html`<div class="eng"><span class="sdot" data-tone=${e.available ? 'success' : 'neutral'}></span>
          <b>${engineLabel(name)}</b>${name === st.engine_default ? html`<hxk-badge tone="accent">predefinito</hxk-badge>` : nothing}
          <span class="muted small truncate" title=${e.detail}>${e.detail}</span></div>`)}
        <div class="eng muted small">Repository: ${st.repo_ok ? (st.base_branch || 'ok') : 'non montato'} · in coda: ${(st.queue ?? []).length}</div>
        ${ph ? html`<div class="eng small"><span class="muted">Budget Claude:</span> <hxk-badge tone=${ph.tone}>${ph.label}</hxk-badge>
          <span class="muted truncate">${b.reason || ''}${b.next_reset ? ` · reset ${when(b.next_reset)}` : ''}</span></div>` : nothing}
      </div>` : nothing}
    </div>`;
  }

  private newDialog() {
    return html`<dialog class="new" @close=${() => (this.newOpen = false)} @cancel=${() => (this.newOpen = false)}>
      ${this.newOpen ? html`<div class="dlg">
        <header><h2>Nuovo sviluppo</h2><hxk-button variant="ghost" size="sm" icon="x" title="Chiudi" @click=${() => this.closeNew()}></hxk-button></header>
        <div class="fld"><label>Cosa vuoi che Forge sviluppi o corregga? *</label>
          <textarea rows="5" .value=${this.nReq} @input=${(e: any) => (this.nReq = e.target.value)} placeholder="Es. Nel calendario aggiungi l'export ICS dell'agenda…"></textarea>
          <div class="h">Più dettagli dai, migliore il risultato. Forge lavora su un ramo separato: niente cambia finché non approvi.</div></div>
        <div class="two">
          <div class="fld"><label>Motore</label>${this.engineSelect(this.nEngine, v => (this.nEngine = v))}</div>
          <div class="fld"><label>Servizi coinvolti</label><input .value=${this.nServices} placeholder="chronos, webui" @input=${(e: any) => (this.nServices = e.target.value)}>
            <div class="h">Facoltativo, separati da virgola</div></div>
        </div>
        <div class="fld"><label>Continua un dossier</label>
          <select @change=${(e: any) => (this.nWorkdoc = e.target.value)}>
            <option value="" ?selected=${!this.nWorkdoc}>Nuovo dossier</option>
            ${this.dossiers.map(d => html`<option value=${d.name} ?selected=${d.name === this.nWorkdoc}>${d.name}${d.progress ? ` · ${d.progress.done}/${d.progress.total}` : ''}</option>`)}
          </select><div class="h">Facoltativo: Forge riprende SPEC e PROGRESS di un lavoro esistente</div></div>
        <footer><hxk-button variant="ghost" @click=${() => this.closeNew()}>Annulla</hxk-button>
          <hxk-button variant="primary" ?disabled=${this.nReq.trim().length < 8} ?loading=${this.store.busy} @click=${() => this.submitNew()}>${icon('send', 14)} Avvia sviluppo</hxk-button></footer>
      </div>` : nothing}
    </dialog>`;
  }

  render() {
    const s = this.store;
    if (!s) return nothing;
    const cols = this.size === 'wide' && s.task ? `${this.listW}px minmax(0, 1fr) ${this.sideW}px`
      : this.size === 'wide' ? `${this.listW}px minmax(0, 1fr)`
      : this.size === 'mid' ? `${this.listW}px minmax(0, 1fr)` : '1fr';
    return html`${this.header()}
      ${this.mode === 'repo'
        ? html`<hephaestus-repo .host=${this.host} .nav=${this.repoNav} @open-task=${(e: CustomEvent) => this.openTask(e.detail)}></hephaestus-repo>`
        : html`<div class="layout ${s.selectedId ? 'has-sel' : ''}" data-size=${this.size} style="grid-template-columns:${cols}">
            ${this.list()}
            <section class="center-col">${this.center()}</section>
            ${this.size === 'wide' && s.task ? html`<aside class="side"><div class="grip" @pointerdown=${(e: PointerEvent) => this.grip(e, 'side')}></div>${this.panel()}</aside>` : nothing}
          </div>`}
      ${this.newDialog()}`;
  }
}
