/** Types of the Sviluppo page (Hephaestus Forge + repo browser). Spec: docs/work/2026-10-04-calendar-skills-forge-ui/SPEC.md §C. */

export type ForgeState =
  | 'new' | 'proposed' | 'scheduled' | 'queued' | 'running' | 'awaiting_review' | 'approved' | 'merging'
  | 'merged' | 'deployed' | 'failed' | 'rejected' | 'rolled_back' | 'no_changes';

export interface ForgeTask {
  id: string;
  state: ForgeState;
  request: string;
  services?: string[];
  engine?: string;
  engine_requested?: string;
  source?: string;
  requested_by?: string;
  summary?: string;
  diff_stat?: string;
  workdoc?: string;
  deploy_plan?: { restart: string[]; rebuild: string[]; restart_self: boolean };
  deploy?: { ok: boolean; output_tail: string };
  changed_files?: string[];
  touched_services?: string[];
  tests?: { ok: boolean | null; output_tail?: string; tail?: string };
  merge_sha?: string;
  commit_sha?: string;
  base_sha?: string;
  base_branch?: string;
  branch?: string;
  error?: string | null;
  created_at: string;
  updated_at?: string;
  cost_usd?: number | null;
  turns?: number;
  engine_ms?: number;
  parent_task?: string | null;
  start_policy?: string;
  history?: ForgeEvent[];
}

export interface ForgeEvent { ts: string; state: string; note: string; }

export type TranscriptKind = 'user' | 'text' | 'thinking' | 'tool_use' | 'tool_result' | 'system' | 'result' | 'error';

export interface TranscriptEvent {
  i: number;
  ts: string;
  kind: TranscriptKind;
  text?: string;
  tool?: string;
  id?: string;
  input?: Record<string, unknown>;
  is_error?: boolean;
  meta?: Record<string, any>;
}

export interface TranscriptPage { total: number; offset: number; live: boolean; events: TranscriptEvent[]; state?: string; }

export interface FileStat {
  path: string;
  old_path?: string;
  added: number | null;
  deleted: number | null;
  binary: boolean;
  status?: string;   // A M D R C ?
}

export interface TaskFiles {
  live: boolean;
  base?: string;
  head?: string;
  files: FileStat[];
  diff: string;
  truncated?: boolean;
  totals?: { files: number; added: number; deleted: number };
  error?: string;
}

export interface WorkDoc { path: string; name: string; group: 'dossier' | 'changed'; content: string; }
export interface TaskWorkdoc { workdoc: string | null; ref: string; docs: WorkDoc[]; }
export interface TaskTests { ok: boolean | null; ran: boolean; output: string; summary: Record<string, any>; }
export interface TaskLogs { engine: string; deploy: string; error?: string | null; hint: string; }

export interface ForgeStatus {
  enabled: boolean;
  repo_ok: boolean;
  base_branch: string | null;
  engine_default: string;
  engines: Record<string, { available: boolean; detail: string }>;
  queue: string[];
}

// ── repo ─────────────────────────────────────────────────────────────────
export interface Branch {
  name: string; sha: string; date: string; author: string; subject: string; upstream: string | null;
  current: boolean; base: boolean; forge_task: string | null; ahead: number; behind: number;
}
export interface Commit {
  sha: string; short: string; parents: string[]; author: string; email: string; date: string; subject: string; refs: string[];
}
export interface CommitDetail extends Commit {
  committer: string; committed: string; body: string; files: FileStat[]; diff: string; truncated: boolean;
}
export interface TreeEntry { name: string; path: string; type: 'blob' | 'tree' | 'commit'; sha: string; size: number | null; secret: boolean; }
export interface RepoFile { ref: string; path: string; size: number; binary: boolean; content: string; truncated: boolean; }
export interface Compare { base: string; head: string; ahead: number; behind: number; commits: Commit[]; files: FileStat[]; diff: string; truncated: boolean; }
export interface Tag { name: string; sha: string; date: string; subject: string; }
export interface Dossier {
  name: string; path: string; title: string | null; version: string | null; status: string | null; source: string | null;
  progress: { done: number; total: number } | null;
}

// ── labels ───────────────────────────────────────────────────────────────
export const ACTIVE: ForgeState[] = ['queued', 'running', 'approved', 'merging'];

export const STATE_META: Record<string, { label: string; tone: 'neutral' | 'accent' | 'success' | 'danger' | 'warning' | 'info'; icon: string }> = {
  new: { label: 'nuovo', tone: 'neutral', icon: 'plus' },
  proposed: { label: 'da approvare', tone: 'warning', icon: 'clock' },
  scheduled: { label: 'programmato', tone: 'info', icon: 'moon' },
  queued: { label: 'in coda', tone: 'info', icon: 'clock' },
  running: { label: 'in lavorazione', tone: 'accent', icon: 'terminal' },
  awaiting_review: { label: 'diff da rivedere', tone: 'warning', icon: 'search' },
  approved: { label: 'merge in corso', tone: 'accent', icon: 'branch' },
  merging: { label: 'merge in corso', tone: 'accent', icon: 'branch' },
  merged: { label: 'applicato', tone: 'success', icon: 'check' },
  deployed: { label: 'in produzione', tone: 'success', icon: 'zap' },
  failed: { label: 'fallito', tone: 'danger', icon: 'alert' },
  rejected: { label: 'rifiutato', tone: 'neutral', icon: 'x' },
  rolled_back: { label: 'annullato (rollback)', tone: 'neutral', icon: 'undo' },
  no_changes: { label: 'nessuna modifica', tone: 'neutral', icon: 'minus' },
};

export const ENGINE_LABEL: Record<string, string> = {
  '': 'Predefinito', auto: 'Predefinito', local: 'Locale (Ollama)', cloud: 'Cloud', claude: 'Claude Code',
};

export const FILE_STATUS: Record<string, { label: string; tone: string }> = {
  A: { label: 'aggiunto', tone: 'success' }, M: { label: 'modificato', tone: 'info' }, D: { label: 'eliminato', tone: 'danger' },
  R: { label: 'rinominato', tone: 'warning' }, C: { label: 'copiato', tone: 'warning' }, '?': { label: 'nuovo', tone: 'success' },
};
