import { Injectable, computed, inject, signal } from '@angular/core';
import { ToastService } from '../../ui';
import { ForgeApi } from './forge.api';
import {
  ACTIVE, ForgeStatus, ForgeTask, TaskFiles, TaskLogs, TaskTests, TaskWorkdoc, TranscriptEvent,
} from './forge.models';

export type SidePanel = 'overview' | 'files' | 'diff' | 'dossier' | 'tests' | 'logs' | 'branch';

/** State of the Sviluppo page: task list, selected task (detail, transcript, side panels), live polling. */
@Injectable({ providedIn: 'root' })
export class ForgeStore {
  private api = inject(ForgeApi);
  private toast = inject(ToastService);

  readonly tasks = signal<ForgeTask[]>([]);
  readonly status = signal<ForgeStatus | null>(null);
  readonly loading = signal(false);
  readonly error = signal('');
  readonly filter = signal<'all' | 'open' | 'done' | 'failed'>('all');
  readonly search = signal('');

  readonly selectedId = signal<string | null>(null);
  readonly task = signal<ForgeTask | null>(null);
  readonly transcript = signal<TranscriptEvent[]>([]);
  readonly transcriptLive = signal(false);
  readonly files = signal<TaskFiles | null>(null);
  readonly workdoc = signal<TaskWorkdoc | null>(null);
  readonly tests = signal<TaskTests | null>(null);
  readonly logs = signal<TaskLogs | null>(null);
  readonly panel = signal<SidePanel>('overview');
  readonly busy = signal(false);

  readonly active = computed(() => { const t = this.task(); return !!t && ACTIVE.includes(t.state); });
  readonly visible = computed(() => {
    const q = this.search().trim().toLowerCase();
    const f = this.filter();
    return this.tasks().filter(t => {
      if (q && !`${t.request} ${t.id} ${t.workdoc ?? ''} ${(t.services ?? []).join(' ')}`.toLowerCase().includes(q)) return false;
      if (f === 'open') return !['merged', 'deployed', 'failed', 'rejected', 'rolled_back', 'no_changes'].includes(t.state);
      if (f === 'done') return ['merged', 'deployed'].includes(t.state);
      if (f === 'failed') return ['failed', 'rolled_back', 'no_changes'].includes(t.state);
      return true;
    });
  });
  readonly counts = computed(() => {
    const open = this.tasks().filter(t => ['proposed', 'scheduled', 'awaiting_review', ...ACTIVE].includes(t.state));
    return { open: open.length, review: this.tasks().filter(t => t.state === 'awaiting_review' || t.state === 'proposed').length };
  });

  private listTimer: ReturnType<typeof setInterval> | null = null;
  private liveTimer: ReturnType<typeof setTimeout> | null = null;
  private seq = 0;
  private tick = 0;

  // ── lifecycle ──────────────────────────────────────────────────────────
  start() {
    this.loadList();
    this.api.status().then(s => this.status.set(s)).catch(() => this.status.set(null));
    this.stopList();
    this.listTimer = setInterval(() => { if (!document.hidden) this.loadList(true); }, 15000);
  }
  stop() { this.stopList(); this.stopLive(); }
  private stopList() { if (this.listTimer) clearInterval(this.listTimer); this.listTimer = null; }
  private stopLive() { if (this.liveTimer) clearTimeout(this.liveTimer); this.liveTimer = null; }

  async loadList(quiet = false) {
    if (!quiet) this.loading.set(true);
    try {
      this.tasks.set(await this.api.tasks());
      this.error.set('');
    } catch (e: any) {
      this.error.set(e?.error?.detail || e?.message || 'Hephaestus non raggiungibile');
    } finally {
      this.loading.set(false);
    }
  }

  // ── selection ──────────────────────────────────────────────────────────
  async select(id: string | null) {
    this.stopLive();
    const seq = ++this.seq;
    this.selectedId.set(id);
    this.task.set(id ? this.tasks().find(t => t.id === id || t.id.startsWith(id)) ?? null : null);
    this.transcript.set([]); this.files.set(null); this.workdoc.set(null); this.tests.set(null); this.logs.set(null);
    if (!id) return;
    try {
      const task = await this.api.task(id);
      if (seq !== this.seq) return;
      this.task.set(task);
      this.selectedId.set(task.id);
      await Promise.all([this.pullTranscript(seq, true), this.loadPanel(this.panel(), seq)]);
    } catch (e: any) {
      if (seq === this.seq) this.toast.error(e?.error?.detail || 'Task non trovato');
    }
    this.scheduleLive(seq);
  }

  setPanel(p: SidePanel) {
    this.panel.set(p);
    this.loadPanel(p, this.seq);
  }

  private async loadPanel(p: SidePanel, seq: number, force = false) {
    const id = this.selectedId();
    if (!id) return;
    try {
      if ((p === 'files' || p === 'diff' || p === 'overview') && (force || !this.files())) {
        const f = await this.api.files(id, true);
        if (seq === this.seq) this.files.set(f);
      }
      if (p === 'dossier' && (force || !this.workdoc())) {
        const w = await this.api.workdoc(id);
        if (seq === this.seq) this.workdoc.set(w);
      }
      if (p === 'tests' && (force || !this.tests())) {
        const t = await this.api.tests(id);
        if (seq === this.seq) this.tests.set(t);
      }
      if (p === 'logs' && (force || !this.logs())) {
        const l = await this.api.logs(id);
        if (seq === this.seq) this.logs.set(l);
      }
    } catch (e: any) {
      if (seq === this.seq) this.toast.error(e?.error?.detail || 'Caricamento non riuscito');
    }
  }

  private async pullTranscript(seq: number, reset = false) {
    const id = this.selectedId();
    if (!id) return;
    let have = reset ? [] : this.transcript();
    // Append-only: stored events + the live Claude stream normalized in order, so indexes stay stable.
    // Small pages (events carry up to 20 KB of tool output each) until we have everything.
    let page = await this.api.transcript(id, have.length, 300);
    let changed = reset;
    for (let n = 0; ; n++) {
      if (seq !== this.seq) return;
      if (page.events.length) { have = [...have.slice(0, page.offset), ...page.events]; changed = true; }
      if (have.length >= page.total || !page.events.length || n >= 30) break;
      page = await this.api.transcript(id, have.length, 300);
    }
    if (changed) this.transcript.set(have);
    this.transcriptLive.set(page.live);
  }

  /** While the task works: task + transcript every 4 s, changed files every ~12 s. */
  private scheduleLive(seq: number) {
    if (!this.active() && !this.transcriptLive()) return;
    this.liveTimer = setTimeout(async () => {
      if (seq !== this.seq) return;
      if (!document.hidden) {
        try {
          const id = this.selectedId()!;
          const task = await this.api.task(id);
          if (seq !== this.seq) return;
          const was = this.task()?.state;
          this.task.set(task);
          await this.pullTranscript(seq);
          if (++this.tick % 3 === 0 || was !== task.state) await this.loadPanel(this.panel(), seq, true);
          if (was !== task.state) {
            this.loadList(true);
            this.files.set(null); this.tests.set(null); this.logs.set(null); this.workdoc.set(null);
            await this.loadPanel(this.panel(), seq, true);
          }
        } catch { /* keep polling */ }
      }
      this.scheduleLive(seq);
    }, 4000);
  }

  async refresh() {
    const id = this.selectedId();
    await this.loadList(true);
    if (id) await this.select(id);
  }

  // ── actions ────────────────────────────────────────────────────────────
  async act(verb: 'approve' | 'reject' | 'rollback' | 'retry', body: { reason?: string; now?: boolean } = {}) {
    const t = this.task();
    if (!t) return;
    this.busy.set(true);
    try {
      const r = await this.api.act(t.id, verb, body);
      const labels = { approve: 'Approvato', reject: 'Rifiutato', rollback: 'Rollback avviato', retry: 'Nuovo tentativo avviato' };
      this.toast.success(labels[verb]);
      await this.loadList(true);
      await this.select(verb === 'retry' ? r.task.id : t.id);
    } catch (e: any) {
      this.toast.error(e?.error?.detail || 'Azione non riuscita');
    } finally {
      this.busy.set(false);
    }
  }

  async submit(body: { request: string; services?: string[]; engine?: string; workdoc?: string; parent_task?: string }) {
    this.busy.set(true);
    try {
      const r = await this.api.submit(body);
      this.toast.success('Sviluppo avviato');
      await this.loadList(true);
      await this.select(r.task.id);
      return true;
    } catch (e: any) {
      this.toast.error(e?.error?.detail || 'Invio non riuscito');
      return false;
    } finally {
      this.busy.set(false);
    }
  }
}
