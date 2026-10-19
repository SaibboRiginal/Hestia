/**
 * State of the Sviluppo page: task list, selected task (detail, transcript, side panels) and live polling (no
 * streaming: the task + transcript are polled every 4 s while the engine works, the list every 15 s).
 * Port of the WebUI forge.store; `onChange` re-renders the page and its child elements (`rev`).
 */
import type { HestiaHost } from '@hestia/webui-sdk';
import { ACTIVE, CLOSED, ForgeApi, ForgeStatus, ForgeTask, TaskFiles, TaskLogs, TaskTests, TaskWorkdoc, TranscriptEvent,
         USER_SOURCES, errText } from './models';

export type SidePanel = 'overview' | 'files' | 'diff' | 'dossier' | 'tests' | 'logs' | 'branch';
export type Filter = 'all' | 'open' | 'modules' | 'done' | 'failed';

export class ForgeStore {
  readonly api: ForgeApi;
  tasks: ForgeTask[] = [];
  status: ForgeStatus | null = null;
  budget: any = null;
  loading = false;
  error = '';
  filter: Filter = 'all';
  search = '';

  selectedId: string | null = null;
  task: ForgeTask | null = null;
  transcript: TranscriptEvent[] = [];
  transcriptLive = false;
  files: TaskFiles | null = null;
  workdoc: TaskWorkdoc | null = null;
  tests: TaskTests | null = null;
  logs: TaskLogs | null = null;
  panel: SidePanel = 'overview';
  busy = false;

  private listTimer: ReturnType<typeof setInterval> | null = null;
  private liveTimer: ReturnType<typeof setTimeout> | null = null;
  private seq = 0;
  private tick = 0;

  constructor(private host: HestiaHost, private onChange: () => void, private onSelected: (id: string | null) => void) {
    this.api = new ForgeApi(host);
  }
  private changed() { this.onChange(); }

  get active() { return !!this.task && ACTIVE.includes(this.task.state); }
  get visible(): ForgeTask[] {
    const q = this.search.trim().toLowerCase();
    const f = this.filter;
    return this.tasks.filter(t => {
      if (q && !`${t.request} ${t.id} ${t.workdoc ?? ''} ${(t.services ?? []).join(' ')}`.toLowerCase().includes(q)) return false;
      if (f === 'open') return !CLOSED.includes(t.state);
      if (f === 'modules') return !USER_SOURCES.includes(t.source || 'user');
      if (f === 'done') return ['merged', 'deployed'].includes(t.state);
      if (f === 'failed') return ['failed', 'rolled_back', 'no_changes'].includes(t.state);
      return true;
    });
  }
  get counts() {
    const open = this.tasks.filter(t => ['proposed', 'scheduled', 'awaiting_review', ...ACTIVE].includes(t.state));
    return { open: open.length, review: this.tasks.filter(t => t.state === 'awaiting_review' || t.state === 'proposed').length };
  }

  // ── lifecycle ──────────────────────────────────────────────────────────
  start() {
    this.loadList();
    this.loadStatus();
    this.stopList();
    this.listTimer = setInterval(() => { if (!document.hidden) this.loadList(true); }, 15000);
  }
  stop() { this.stopList(); this.stopLive(); this.seq++; }
  private stopList() { if (this.listTimer) clearInterval(this.listTimer); this.listTimer = null; }
  private stopLive() { if (this.liveTimer) clearTimeout(this.liveTimer); this.liveTimer = null; }

  async loadStatus() {
    try { this.status = await this.api.status(); } catch { this.status = null; }
    try { this.budget = await this.api.budget(); } catch { this.budget = null; }
    this.changed();
  }

  async loadList(quiet = false) {
    if (!quiet) { this.loading = true; this.changed(); }
    try {
      this.tasks = await this.api.tasks();
      this.error = '';
    } catch (e) {
      this.error = errText(e, 'Hephaestus non raggiungibile');
    } finally {
      this.loading = false;
      this.changed();
    }
  }

  // ── selection ──────────────────────────────────────────────────────────
  async select(id: string | null) {
    this.stopLive();
    const seq = ++this.seq;
    this.selectedId = id;
    this.task = id ? this.tasks.find(t => t.id === id || t.id.startsWith(id)) ?? null : null;
    this.transcript = []; this.transcriptLive = false;
    this.files = null; this.workdoc = null; this.tests = null; this.logs = null;
    this.changed();
    if (!id) return;
    try {
      const task = await this.api.task(id);
      if (seq !== this.seq) return;
      this.task = task;
      this.selectedId = task.id;
      if (task.id !== id) this.onSelected(task.id);   // short id in the link → full id
      this.changed();
      await Promise.all([this.pullTranscript(seq, true), this.loadPanel(this.panel, seq)]);
    } catch (e) {
      if (seq === this.seq) this.host.toast(errText(e, 'Task non trovato'), 'danger');
    }
    this.scheduleLive(seq);
  }

  setPanel(p: SidePanel) {
    this.panel = p;
    this.changed();
    this.loadPanel(p, this.seq);
  }

  private async loadPanel(p: SidePanel, seq: number, force = false) {
    const id = this.selectedId;
    if (!id) return;
    try {
      if ((p === 'files' || p === 'diff' || p === 'overview') && (force || !this.files)) {
        const f = await this.api.files(id);
        if (seq === this.seq) this.files = f;
      }
      if (p === 'dossier' && (force || !this.workdoc)) {
        const w = await this.api.workdoc(id);
        if (seq === this.seq) this.workdoc = w;
      }
      if (p === 'tests' && (force || !this.tests)) {
        const t = await this.api.tests(id);
        if (seq === this.seq) this.tests = t;
      }
      if (p === 'logs' && (force || !this.logs)) {
        const l = await this.api.logs(id);
        if (seq === this.seq) this.logs = l;
      }
    } catch (e) {
      if (seq === this.seq) this.host.toast(errText(e, 'Caricamento non riuscito'), 'danger');
    }
    if (seq === this.seq) this.changed();
  }

  /** Append-only: stored events + the live stream normalized in order, small pages until we have everything. */
  private async pullTranscript(seq: number, reset = false) {
    const id = this.selectedId;
    if (!id) return;
    let have = reset ? [] : this.transcript;
    let page = await this.api.transcript(id, have.length, 300);
    let changed = reset;
    for (let n = 0; ; n++) {
      if (seq !== this.seq) return;
      if (page.events.length) { have = [...have.slice(0, page.offset), ...page.events]; changed = true; }
      if (have.length >= page.total || !page.events.length || n >= 30) break;
      page = await this.api.transcript(id, have.length, 300);
    }
    if (changed) this.transcript = have;
    this.transcriptLive = page.live;
    this.changed();
  }

  /** While the task works: task + transcript every 4 s, the open panel every ~12 s or when the state changes. */
  private scheduleLive(seq: number) {
    if (seq !== this.seq || (!this.active && !this.transcriptLive)) return;
    this.liveTimer = setTimeout(async () => {
      if (seq !== this.seq) return;
      if (!document.hidden) {
        try {
          const id = this.selectedId!;
          const task = await this.api.task(id);
          if (seq !== this.seq) return;
          const was = this.task?.state;
          this.task = task;
          await this.pullTranscript(seq);
          if (was !== task.state) {
            this.loadList(true);
            this.files = null; this.tests = null; this.logs = null; this.workdoc = null;
            await this.loadPanel(this.panel, seq, true);
          } else if (++this.tick % 3 === 0) await this.loadPanel(this.panel, seq, true);
        } catch { /* keep polling */ }
      }
      this.scheduleLive(seq);
    }, 4000);
  }

  async refresh() {
    const id = this.selectedId;
    this.loadStatus();
    await this.loadList(true);
    if (id) await this.select(id);
  }

  // ── actions ────────────────────────────────────────────────────────────
  private async run<T>(fn: () => Promise<T>, fail: string): Promise<T | null> {
    this.busy = true; this.changed();
    try { return await fn(); }
    catch (e) { this.host.toast(errText(e, fail), 'danger'); return null; }
    finally { this.busy = false; this.changed(); }
  }

  /** Manual brake: paused = nothing starts on its own; resuming restarts nothing held. */
  async setPaused(paused: boolean) {
    const r = await this.run(() => this.api.pause(paused), 'Impostazione non salvata');
    if (!r) return;
    if (this.status) this.status = { ...this.status, paused: r.paused };
    const held = r.held?.length ? ` ${r.held.length} task trattenuti restano da avviare a mano.` : '';
    this.host.toast(r.paused ? 'Sviluppo in pausa: niente parte da solo' : `Sviluppo ripreso.${held}`, 'success');
    await this.loadList(true);
  }

  async act(verb: 'approve' | 'reject' | 'rollback' | 'retry', body: { reason?: string; now?: boolean; engine?: string } = {}) {
    const t = this.task;
    if (!t) return;
    const r = await this.run(() => this.api.act(t.id, verb, body), 'Azione non riuscita');
    if (!r) return;
    const labels = { approve: 'Approvato', reject: 'Rifiutato', rollback: 'Rollback avviato', retry: 'Nuovo tentativo avviato' };
    this.host.toast(labels[verb], 'success');
    await this.loadList(true);
    const next = verb === 'retry' ? r.task.id : t.id;
    if (next !== t.id) this.onSelected(next);
    await this.select(next);
  }

  async submit(body: { request: string; services?: string[]; engine?: string; workdoc?: string; parent_task?: string }) {
    const r = await this.run(() => this.api.submit(body), 'Invio non riuscito');
    if (!r) return false;
    this.host.toast('Sviluppo avviato', 'success');
    await this.loadList(true);
    this.onSelected(r.task.id);
    await this.select(r.task.id);
    return true;
  }

  async addNote(text: string) {
    const t = this.task;
    if (!t) return false;
    const r = await this.run(() => this.api.note(t.id, text), 'Nota non salvata');
    if (!r) return false;
    this.host.toast('Nota aggiunta: il motore la usa quando il task parte o viene riprovato', 'success');
    try { const task = await this.api.task(t.id); if (this.selectedId === task.id) { this.task = task; this.changed(); } } catch { /* next poll */ }
    return true;
  }
}
