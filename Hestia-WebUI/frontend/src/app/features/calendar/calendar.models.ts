/** Assistant agenda (Chronos /api/agenda*) types used by the calendar module. */

export type AgendaType = 'event' | 'task' | 'job' | 'window';
export type AgendaStatus = 'confirmed' | 'paused' | 'cancelled' | 'completed' | 'failed';

export interface AgendaAction {
  service: string;
  path: string;
  method?: string;
  body?: unknown;
  query?: Record<string, string>;
  timeout_seconds?: number;
}

export interface AgendaItem {
  id: number;
  key: string;
  type: AgendaType;
  owner: string;
  title: string;
  description?: string | null;
  start_at: string;
  end_at?: string | null;
  recurrence?: string | null;
  tz: string;
  status: AgendaStatus;
  action?: AgendaAction | null;
  params: Record<string, unknown>;
  skips: string[];
  overrides?: Record<string, { start: string; end?: string | null }>;
  user_modified: boolean;
  created_by: string;
  last_fired?: string | null;
  last_result?: { ok: boolean; detail: string; at: string; by?: string } | null;
  attempts: number;
}

export interface AgendaOccurrence {
  item_id: number;
  key: string;
  type: AgendaType;
  owner: string;
  title: string;
  start: string;
  end: string | null;
  occurrence: string;
  skipped: boolean;
  moved?: boolean;
  status?: AgendaStatus;
  recurring?: boolean;
}

/** View model: one occurrence + its rule, ready to draw. */
export interface CalEvent {
  id: string;               // key|occurrence
  occ: AgendaOccurrence;
  item?: AgendaItem;
  start: Date;
  end: Date | null;         // null = instant (job/task/event without duration)
  color: string;
  source: string;           // layer id ('hestia' now; external calendars later)
}

/**
 * Calendar layers. Today only the AI agenda; external calendars (Google/Microsoft)
 * will be added as separate sources with kind 'external' and their own style.
 */
export interface CalendarSource {
  id: string;
  label: string;
  kind: 'ai' | 'external';
  enabled: boolean;
}

export type CalView = 'month' | 'week' | 'day' | 'list';

export const TYPE_META: Record<AgendaType, { label: string; icon: string; hint: string }> = {
  event: { label: 'Evento', icon: 'event', hint: 'Informativo: qualcosa che un modulo ha pianificato' },
  task: { label: 'Task', icon: 'task', hint: 'Azione una tantum eseguita all\'orario indicato' },
  job: { label: 'Job ricorrente', icon: 'repeat', hint: 'Azione ripetuta secondo la regola' },
  window: { label: 'Finestra', icon: 'window', hint: 'Periodo in cui un modulo può lavorare' },
};

export const STATUS_META: Record<AgendaStatus, { label: string; tone: 'neutral' | 'success' | 'warning' | 'danger' | 'info' }> = {
  confirmed: { label: 'Attivo', tone: 'success' },
  paused: { label: 'In pausa', tone: 'warning' },
  cancelled: { label: 'Annullato', tone: 'neutral' },
  completed: { label: 'Completato', tone: 'info' },
  failed: { label: 'Fallito', tone: 'danger' },
};

/** Friendly names for module owners (fallback: capitalized owner). */
export const OWNER_LABELS: Record<string, string> = {
  user: 'Tu', hephaestus: 'Hephaestus (Forge)', athena: 'Athena', scout: 'Scout', chronos: 'Chronos',
  metis: 'Metis', argus: 'Argus', oracle: 'Oracle', hermes: 'Hermes',
};

export function ownerLabel(owner: string): string {
  return OWNER_LABELS[owner] ?? owner.charAt(0).toUpperCase() + owner.slice(1);
}
