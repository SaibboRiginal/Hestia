/**
 * Types, labels and formatters of the Sviluppo page (ported from the WebUI's built-in features/forge, SPEC
 * docs/work/2026-10-18-moduli-core-e-mcp-esterno §A4). Every call goes to /api/hephaestus/forge|repo/* directly.
 */
import type { HestiaHost } from '@hestia/webui-sdk';
import { API } from '../util';

export const REPO = `${API}/repo`;

export type ForgeState =
  | 'new' | 'proposed' | 'scheduled' | 'queued' | 'running' | 'awaiting_review' | 'approved' | 'merging'
  | 'merged' | 'deployed' | 'failed' | 'rejected' | 'rolled_back' | 'no_changes';

export interface ForgeEvent { ts: string; state: string; note: string; }
export interface ForgeNote { ts: string; by: string; text: string; }

export interface ForgeTask {
  id: string; state: ForgeState; request: string; services?: string[]; engine?: string; engine_requested?: string;
  source?: string; requested_by?: string; summary?: string; diff_stat?: string; workdoc?: string;
  deploy_plan?: { restart: string[]; rebuild: string[]; restart_self: boolean };
  changed_files?: string[]; touched_services?: string[];
  tests?: { ok: boolean | null; output_tail?: string; tail?: string };
  merge_sha?: string; commit_sha?: string; base_sha?: string; base_branch?: string; branch?: string;
  error?: string | null; created_at: string; updated_at?: string; cost_usd?: number | null; turns?: number;
  engine_ms?: number; parent_task?: string | null; history?: ForgeEvent[]; notes?: ForgeNote[];
  external?: { branch: string; summary?: string; by?: string; at?: string };
}

export type TranscriptKind = 'user' | 'text' | 'thinking' | 'tool_use' | 'tool_result' | 'system' | 'result' | 'error';
export interface TranscriptEvent {
  i: number; ts: string; kind: TranscriptKind; text?: string; tool?: string; id?: string;
  input?: Record<string, unknown>; is_error?: boolean; meta?: Record<string, any>;
}
export interface TranscriptPage { total: number; offset: number; live: boolean; events: TranscriptEvent[]; state?: string; }

export interface FileStat { path: string; old_path?: string; added: number | null; deleted: number | null; binary: boolean; status?: string; }
export interface TaskFiles {
  live: boolean; base?: string; head?: string; files: FileStat[]; diff: string; truncated?: boolean;
  totals?: { files: number; added: number; deleted: number }; error?: string;
}
export interface WorkDoc { path: string; name: string; group: 'dossier' | 'changed'; content: string; }
export interface TaskWorkdoc { workdoc: string | null; ref: string; docs: WorkDoc[]; }
export interface TaskTests { ok: boolean | null; ran: boolean; output: string; summary: Record<string, any>; }
export interface TaskLogs { engine: string; deploy: string; error?: string | null; hint: string; }

export interface ForgeStatus {
  enabled: boolean; paused?: boolean; repo_ok: boolean; base_branch: string | null; engine_default: string;
  engines: Record<string, { available: boolean; detail: string }>; queue: string[];
}

export interface Branch {
  name: string; sha: string; date: string; author: string; subject: string; upstream: string | null;
  current: boolean; base: boolean; forge_task: string | null; ahead: number; behind: number;
}
export interface Commit { sha: string; short: string; parents: string[]; author: string; email: string; date: string; subject: string; refs: string[]; }
export interface CommitDetail extends Commit { committer: string; committed: string; body: string; files: FileStat[]; diff: string; truncated: boolean; }
export interface TreeEntry { name: string; path: string; type: 'blob' | 'tree' | 'commit'; sha: string; size: number | null; secret: boolean; }
export interface RepoFile { ref: string; path: string; size: number; binary: boolean; content: string; truncated: boolean; }
export interface Compare { base: string; head: string; ahead: number; behind: number; commits: Commit[]; files: FileStat[]; diff: string; truncated: boolean; }
export interface Tag { name: string; sha: string; date: string; subject: string; }
export interface Dossier {
  name: string; path: string; title: string | null; version: string | null; status: string | null; source: string | null;
  progress: { done: number; total: number } | null;
}

// ── labels ───────────────────────────────────────────────────────────────
export const ACTIVE: string[] = ['queued', 'running', 'approved', 'merging'];
export const CLOSED: string[] = ['merged', 'deployed', 'failed', 'rejected', 'rolled_back', 'no_changes'];

export const STATE_META: Record<string, { label: string; tone: string }> = {
  new: { label: 'nuovo', tone: 'neutral' },
  proposed: { label: 'da approvare', tone: 'warning' },
  scheduled: { label: 'programmato', tone: 'info' },
  queued: { label: 'in coda', tone: 'info' },
  running: { label: 'in lavorazione', tone: 'accent' },
  awaiting_review: { label: 'diff da rivedere', tone: 'warning' },
  approved: { label: 'merge in corso', tone: 'accent' },
  merging: { label: 'merge in corso', tone: 'accent' },
  merged: { label: 'applicato', tone: 'success' },
  deployed: { label: 'in produzione', tone: 'success' },
  failed: { label: 'fallito', tone: 'danger' },
  rejected: { label: 'rifiutato', tone: 'neutral' },
  rolled_back: { label: 'annullato (rollback)', tone: 'neutral' },
  no_changes: { label: 'nessuna modifica', tone: 'neutral' },
};
export const meta = (state?: string) => STATE_META[state ?? 'new'] ?? { label: state ?? '', tone: 'neutral' };

export const ENGINES = ['', 'local', 'cloud', 'claude'];
export const ENGINE_LABEL: Record<string, string> = {
  '': 'Predefinito', auto: 'Predefinito', local: 'Locale (Ollama)', cloud: 'Cloud', claude: 'Claude Code',
};
export const engineLabel = (e: string) => ENGINE_LABEL[e] ?? e;
export const engineOf = (t: ForgeTask) => ENGINE_LABEL[t.engine || t.engine_requested || ''] ?? t.engine ?? '—';

/** Who asked for a task (Forge ``source``): you, or a module that proposed it on its own. */
export const USER_SOURCES = ['user', 'telegram', 'ui', 'oracle'];
const SOURCE_LABEL: Record<string, string> = {
  user: 'Tu', telegram: 'Tu (Telegram)', ui: 'Tu (WebUI)', oracle: 'Tu (chat)', external: 'AI esterna',
  athena: 'Athena', argus: 'Argus', 'hephaestus.remediation': 'Riparazioni', metis: 'Metis',
};
export const sourceLabel = (source?: string) => SOURCE_LABEL[source || 'user'] ?? (source || 'Tu');
export const byModule = (t: ForgeTask) => !USER_SOURCES.includes(t.source || 'user');

export const FILE_STATUS: Record<string, string> = {
  A: 'aggiunto', M: 'modificato', D: 'eliminato', R: 'rinominato', C: 'copiato', '?': 'nuovo',
};

// ── formatters (24h, Italian) ────────────────────────────────────────────
export function shortDate(iso?: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '';
  const p = (n: number) => String(n).padStart(2, '0');
  return `${p(d.getDate())}/${p(d.getMonth() + 1)}/${d.getFullYear()} ${p(d.getHours())}:${p(d.getMinutes())}`;
}
export function ago(iso?: string | null): string {
  if (!iso) return '';
  const t = new Date(iso).getTime();
  if (isNaN(t)) return '';
  const s = Math.round((Date.now() - t) / 1000);
  if (s < 60) return 'adesso';
  if (s < 3600) return `${Math.floor(s / 60)} min fa`;
  if (s < 86400) return `${Math.floor(s / 3600)} h fa`;
  if (s < 86400 * 7) return `${Math.floor(s / 86400)} g fa`;
  return shortDate(iso);
}
export function duration(ms?: number | null): string {
  if (!ms) return '';
  const s = Math.round(ms / 1000);
  return s < 60 ? `${s} s` : s < 3600 ? `${Math.floor(s / 60)} min ${s % 60} s` : `${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min`;
}
export const fileSize = (n: number) => n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(1)} MB`;

// ── api ──────────────────────────────────────────────────────────────────
export class ApiError extends Error { constructor(message: string, public status: number) { super(message); } }

/** host.api that throws an Italian message (status 0 = Hephaestus offline). */
export async function call<T = any>(host: HestiaHost, method: 'GET' | 'POST', path: string,
                                    opts: { query?: Record<string, any>; body?: unknown } = {}): Promise<T> {
  const r = await host.api<T>(method, path, opts);
  if (!r.ok) {
    const offline = r.status === 0 || r.error === 'offline' || r.error === 'unreachable';
    throw new ApiError(offline ? 'Hephaestus non raggiungibile' : (r.error || `Errore ${r.status}`), r.status);
  }
  return r.data;
}
export const errText = (e: unknown, fallback: string) => (e instanceof Error && e.message) ? e.message : fallback;

/** Forge API as the old WebUI controller exposed it; actions are stamped by=user, new tasks source=ui (as before). */
export class ForgeApi {
  constructor(private host: HestiaHost) {}
  private get<T>(path: string, query: Record<string, any> = {}) { return call<T>(this.host, 'GET', path, { query }); }
  private post<T>(path: string, body: Record<string, any>) { return call<T>(this.host, 'POST', path, { body }); }
  private t(id: string) { return `${API}/forge/tasks/${encodeURIComponent(id)}`; }

  status() { return this.get<ForgeStatus>(`${API}/forge/status`); }
  budget() { return this.get<any>(`${API}/forge/claude-budget`); }
  async tasks(limit = 150) { return (await this.get<{ tasks: ForgeTask[] }>(`${API}/forge/tasks`, { limit }))?.tasks ?? []; }
  async task(id: string) { return (await this.get<{ task: ForgeTask }>(this.t(id))).task; }
  transcript(id: string, offset = 0, limit = 300) { return this.get<TranscriptPage>(`${this.t(id)}/transcript`, { offset, limit }); }
  files(id: string) { return this.get<TaskFiles>(`${this.t(id)}/files`, { diff: true }); }
  workdoc(id: string) { return this.get<TaskWorkdoc>(`${this.t(id)}/workdoc`); }
  tests(id: string) { return this.get<TaskTests>(`${this.t(id)}/tests`); }
  logs(id: string) { return this.get<TaskLogs>(`${this.t(id)}/logs`); }
  exportMd(ids: string[]) { return this.get<{ markdown: string; filename: string; count: number; missing: string[] }>(`${API}/forge/tasks/export`, { ids: ids.join(',') }); }

  submit(body: { request: string; services?: string[]; engine?: string; workdoc?: string; parent_task?: string }) {
    return this.post<{ task: ForgeTask }>(`${API}/forge/tasks`, { ...body, source: 'ui', requested_by: 'user' });
  }
  pause(paused: boolean) { return this.post<{ paused: boolean; held?: string[] }>(`${API}/forge/pause`, { paused, by: 'user' }); }
  act(id: string, verb: 'approve' | 'reject' | 'rollback' | 'retry', body: { reason?: string; now?: boolean; engine?: string } = {}) {
    return this.post<{ task: ForgeTask }>(`${this.t(id)}/${verb}`, { ...body, by: 'user' });
  }
  note(id: string, text: string) { return this.post<{ notes: number }>(`${this.t(id)}/notes`, { text, by: 'user' }); }

  // ── repository (read only) ─────────────────────────────────────────────
  branches() { return this.get<{ base: string; current: string; branches: Branch[] }>(`${REPO}/branches`); }
  async tags() { return (await this.get<{ tags: Tag[] }>(`${REPO}/tags`))?.tags ?? []; }
  log(q: { ref?: string; path?: string; limit?: number; skip?: number; all?: boolean }) {
    return this.get<{ commits: Commit[]; has_more: boolean }>(`${REPO}/log`, q);
  }
  commit(sha: string) { return this.get<CommitDetail>(`${REPO}/commits/${encodeURIComponent(sha)}`); }
  compare(base: string, head: string) { return this.get<Compare>(`${REPO}/compare`, { base, head }); }
  tree(ref: string, path: string) { return this.get<{ entries: TreeEntry[] }>(`${REPO}/tree`, { ref, path }); }
  file(ref: string, path: string) { return this.get<RepoFile>(`${REPO}/file`, { ref, path }); }
  async dossiers() { return (await this.get<{ dossiers: Dossier[] }>(`${REPO}/dossiers`))?.dossiers ?? []; }
}

/** Clipboard with a fallback for non-secure contexts (http on the LAN). */
export async function copyText(text: string): Promise<boolean> {
  try { await navigator.clipboard.writeText(text); return true; } catch { /* fall back */ }
  try {
    const ta = document.createElement('textarea');
    ta.value = text; ta.setAttribute('readonly', ''); ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta); ta.select();
    const ok = document.execCommand('copy');
    ta.remove();
    return ok;
  } catch { return false; }
}

export function downloadText(name: string, text: string, mime = 'text/markdown') {
  const url = URL.createObjectURL(new Blob([text], { type: `${mime};charset=utf-8` }));
  const a = document.createElement('a');
  a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

/** Width kept per browser (task list / side panel), like the old <hx-resize>. */
export function savedWidth(key: string, def: number): number {
  try { const v = Number(localStorage.getItem(`hestia.hephaestus.${key}`)); return v > 0 ? v : def; } catch { return def; }
}
export function saveWidth(key: string, v: number) {
  try { localStorage.setItem(`hestia.hephaestus.${key}`, String(Math.round(v))); } catch { /* private mode */ }
}
