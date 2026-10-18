/**
 * Hercules offline data layer (SPEC §8.0): one local mirror of the module's records in IndexedDB
 * (`hestia.hercules.data`) plus an outbox of idempotent ops. The live workout reads and writes only here, so it
 * works in the gym without network; `sync()` sends the outbox to POST /api/hercules/sync and pulls what changed.
 *
 * Every element shares one instance (`local(host)`); `onChange` re-renders them after a sync or a local write.
 */
import type { HestiaHost, KeyValueStore } from '@hestia/webui-sdk';

export const API = '/api/hercules';

export interface Row { kind: string; id: string; data: any; updated_at: string; deleted?: boolean; seq?: number }
export interface Op { op_id: string; kind: string; id: string; action: 'upsert' | 'delete'; fields: any; updated_at: string; device_id: string }
export interface ClientSettings {
  units: string; rest_default: number; bar_weight: number; plates: number[]; increments: Record<string, number>;
  e1rm_formula: string; week_start: string; warmup: Array<{ pct: number; reps: number }>;
}

const DEFAULTS: ClientSettings = {
  units: 'kg', rest_default: 90, bar_weight: 20, plates: [25, 20, 15, 10, 5, 2.5, 1.25],
  increments: { barbell: 2.5, dumbbell: 2, machine: 5, cable: 2.5 }, e1rm_formula: 'epley', week_start: 'monday',
  warmup: [{ pct: 40, reps: 8 }, { pct: 60, reps: 5 }, { pct: 80, reps: 3 }],
};

export function uuid(): string {
  if (typeof crypto !== 'undefined' && typeof (crypto as any).randomUUID === 'function') return crypto.randomUUID();   // http on LAN: not a secure context
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
    const r = (Math.random() * 16) | 0;
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });
}

export const nowIso = () => new Date().toISOString();

export class Local {
  host: HestiaHost;
  private kv: KeyValueStore;
  rows = new Map<string, Row>();
  outbox: Op[] = [];
  cursor = 0;
  suggestions: Record<string, any> = {};
  settings: ClientSettings = { ...DEFAULTS };
  device = '';
  lastSync = '';
  syncing = false;
  ready: Promise<void>;
  private listeners = new Set<() => void>();
  private persistTimer: any = null;
  private syncTimer: any = null;

  constructor(host: HestiaHost) {
    this.host = host;
    this.kv = host.store('data');
    this.ready = this.load();
    host.on('online', () => this.sync());
    host.on('visible', () => this.sync());
  }

  private async load(): Promise<void> {
    try {
      const st = await this.kv.get<any>('state');
      if (st) {
        for (const r of st.rows || []) this.rows.set(`${r.kind}:${r.id}`, r);
        this.cursor = st.cursor || 0;
        this.suggestions = st.suggestions || {};
        this.settings = { ...DEFAULTS, ...(st.settings || {}) };
        this.lastSync = st.lastSync || '';
      }
      this.outbox = (await this.kv.get<Op[]>('outbox')) || [];
      this.device = (await this.kv.get<string>('device')) || '';
      if (!this.device) { this.device = 'webui-' + uuid().slice(0, 8); await this.kv.set('device', this.device); }
    } catch { /* private mode / no IndexedDB: memory only */ }
    if (this.host.online) await this.sync();
  }

  onChange(cb: () => void): () => void { this.listeners.add(cb); return () => this.listeners.delete(cb); }
  private emit() { this.listeners.forEach(cb => { try { cb(); } catch { /* element gone */ } }); }

  private persist() {
    clearTimeout(this.persistTimer);
    this.persistTimer = setTimeout(async () => {
      try {
        await this.kv.set('state', { rows: [...this.rows.values()], cursor: this.cursor, suggestions: this.suggestions,
                                     settings: this.settings, lastSync: this.lastSync });
      } catch { /* quota: keep memory */ }
    }, 300);
  }
  private async persistOutbox() { try { await this.kv.set('outbox', this.outbox); } catch { /* memory only */ } }

  // ── reading ─────────────────────────────────────────────────────────────
  get loaded(): boolean { return this.rows.size > 0; }
  get pending(): number { return this.outbox.length; }

  get(kind: string, id: string): any | null {
    const r = this.rows.get(`${kind}:${id}`);
    return r && !r.deleted ? { ...r.data, id: r.id } : null;
  }
  list(kind: string): any[] {
    const out: any[] = [];
    for (const r of this.rows.values()) if (r.kind === kind && !r.deleted) out.push({ ...r.data, id: r.id });
    return out;
  }
  exercises(): Map<string, any> { return new Map(this.list('exercise').map(e => [e.id, e])); }
  templates(): any[] { return this.list('template').filter(t => !t.archived).sort((a, b) => (a.position || 0) - (b.position || 0) || a.name.localeCompare(b.name)); }
  activeSession(): any | null {
    const act = this.list('session').filter(s => s.status === 'active').sort((a, b) => (a.started_at || '').localeCompare(b.started_at || ''));
    return act.length ? act[act.length - 1] : null;
  }
  setsOf(sessionId: string): any[] {
    return this.list('set').filter(s => s.session_id === sessionId).sort((a, b) => (a.position || 0) - (b.position || 0) || (a.completed_at || '').localeCompare(b.completed_at || ''));
  }
  doneSessions(): any[] {
    return this.list('session').filter(s => s.status === 'done').sort((a, b) => (a.started_at || '').localeCompare(b.started_at || ''));
  }
  /** Working sets of the last done session that had this exercise (for "last time"). */
  lastTime(exerciseId: string, exceptSession?: string): { date: string; sets: any[] } | null {
    const done = this.doneSessions().reverse();
    const sets = this.list('set').filter(s => s.exercise_id === exerciseId && s.type !== 'warmup' && s.completed !== false);
    for (const sess of done) {
      if (sess.id === exceptSession) continue;
      const mine = sets.filter(s => s.session_id === sess.id).sort((a, b) => (a.position || 0) - (b.position || 0));
      if (mine.length) return { date: sess.started_at, sets: mine };
    }
    return null;
  }

  // ── writing (local first, then outbox) ──────────────────────────────────
  put(kind: string, id: string, data: any): any {
    const updated_at = nowIso();
    const { id: _drop, ...fields } = data;
    this.rows.set(`${kind}:${id}`, { kind, id, data: fields, updated_at, deleted: false, seq: this.rows.get(`${kind}:${id}`)?.seq });
    this.queue({ op_id: uuid(), kind, id, action: 'upsert', fields, updated_at, device_id: this.device });
    return { ...fields, id };
  }
  remove(kind: string, id: string): void {
    const r = this.rows.get(`${kind}:${id}`);
    if (!r) return;
    const updated_at = nowIso();
    this.rows.set(`${kind}:${id}`, { ...r, deleted: true, updated_at });
    this.queue({ op_id: uuid(), kind, id, action: 'delete', fields: r.data, updated_at, device_id: this.device });
  }
  private queue(op: Op) {
    this.outbox = this.outbox.filter(o => !(o.kind === op.kind && o.id === op.id));   // last op per record wins
    this.outbox.push(op);
    this.persistOutbox();
    this.persist();
    this.emit();
    clearTimeout(this.syncTimer);
    this.syncTimer = setTimeout(() => this.sync(), 1200);
  }

  // ── sync ────────────────────────────────────────────────────────────────
  private merge(r: Row) {
    const key = `${r.kind}:${r.id}`;
    const old = this.rows.get(key);
    if (old && old.updated_at && r.updated_at && old.updated_at > r.updated_at && this.outbox.some(o => o.kind === r.kind && o.id === r.id)) return;
    this.rows.set(key, r);
  }

  async sync(): Promise<boolean> {
    if (this.syncing || !this.host.online) return false;
    this.syncing = true;
    try {
      if (!this.cursor) {
        const b = await this.host.api('GET', `${API}/bootstrap`);
        if (!b.ok) return false;
        const keep = new Map(this.outbox.map(o => [`${o.kind}:${o.id}`, this.rows.get(`${o.kind}:${o.id}`)]));
        this.rows.clear();
        for (const r of b.data.rows || []) this.rows.set(`${r.kind}:${r.id}`, r);
        for (const [k, r] of keep) if (r) this.rows.set(k, r);
        this.cursor = b.data.cursor || 0;
        this.suggestions = b.data.suggestions || {};
        this.settings = { ...DEFAULTS, ...(b.data.settings || {}) };
      }
      const ops = this.outbox.slice(0, 500);
      const r = await this.host.api('POST', `${API}/sync`, { body: { device_id: this.device, cursor: this.cursor, ops } });
      if (!r.ok) return false;
      const done = new Set<string>([...(r.data.applied || []), ...(r.data.rejected || []).map((x: any) => x.op_id)]);
      this.outbox = this.outbox.filter(o => !done.has(o.op_id));
      for (const x of r.data.rejected || []) {
        this.host.toast(`Non salvato: ${x.error}`, 'warning');
        const keyed = `${x.kind}:${x.id}`;
        if (this.rows.get(keyed) && !this.rows.get(keyed)!.seq) this.rows.delete(keyed);
      }
      for (const row of r.data.changes || []) this.merge(row);
      for (const row of r.data.stale || []) this.rows.set(`${row.kind}:${row.id}`, row);
      this.cursor = r.data.cursor || this.cursor;
      if (r.data.suggestions) this.suggestions = r.data.suggestions;
      this.lastSync = nowIso();
      await this.persistOutbox();
      this.persist();
      this.emit();
      if (this.outbox.length && ops.length === 500) setTimeout(() => this.sync(), 100);
      return true;
    } catch {
      return false;
    } finally {
      this.syncing = false;
    }
  }

  /** GET from the module, remembering the last answer so the page still shows it offline. */
  async cached<T = any>(path: string, query?: Record<string, any>): Promise<{ data: T | null; fresh: boolean }> {
    const key = 'cache:' + path + (query ? '?' + new URLSearchParams(query as any).toString() : '');
    if (this.host.online) {
      const r = await this.host.api<T>('GET', path, { query });
      if (r.ok) { try { await this.kv.set(key, r.data); } catch { /* quota */ } return { data: r.data, fresh: true }; }
    }
    try { return { data: (await this.kv.get<T>(key)) ?? null, fresh: false }; } catch { return { data: null, fresh: false }; }
  }

  /** Forget the mirror and download everything again (Impostazioni → "Riscarica"). */
  async reset(): Promise<void> {
    this.cursor = 0;
    await this.sync();
  }
}

let _local: Local | null = null;
export function local(host: HestiaHost): Local {
  if (!_local) _local = new Local(host);          // one mirror per page load, shared by every Hercules element
  return _local;
}
