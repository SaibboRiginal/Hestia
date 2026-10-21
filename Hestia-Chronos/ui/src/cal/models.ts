/** Assistant agenda (Chronos /api/agenda/*) types and labels used by the calendar page. Ported from the WebUI calendar. */

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
  runs?: { occurrence: string; ok: boolean; detail: string; at: string; by?: string; duration_ms?: number | null }[];
  attempts: number;
  /** Linked parent item key: cancelling it cancels this one; this one failing marks it. */
  parent?: string | null;
}

/** Result of the run of one occurrence (Chronos per-occurrence run log). */
export interface OccurrenceRun { ok: boolean; detail?: string | null; at?: string | null; duration_ms?: number | null;
  /** A flexible job fired away from its nominal time: when and why (recap dossier §3.8). */
  flex?: { from: string; at: string; reason: string } | null; }

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
  created_by?: string;
  run?: OccurrenceRun | null;
}

/** How the visibility policy classifies an item (see calendar.prefs.ts). */
export type EventClass = 'manual' | 'frequent' | 'rare' | 'oneoff';

/** View model: one occurrence + its rule, ready to draw. */
export interface CalEvent {
  id: string;               // key|occurrence
  occ: AgendaOccurrence;
  item?: AgendaItem;
  start: Date;
  end: Date | null;         // null = instant (job/task/event without duration)
  color: string;
  source: string;           // layer id ('hestia' now; external calendars later)
  cls?: EventClass;
  /** Past failures of the same rule collapsed into this one (dedupe), e.g. 3 → "fallito ×3". */
  failedCount?: number;
  /** Summary chip of a frequent rule on one day: every occurrence it stands for. */
  group?: CalEvent[];
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

/** What a module lets the user create (registered by the module, served by Chronos /api/agenda/templates). */
export interface TemplateField { type?: string; label?: string; description?: string; enum?: string[]; default?: unknown; format?: string; in?: string; }
export interface AgendaTemplate {
  id: string;
  owner: string;
  label: string;
  description?: string;
  icon?: string;
  type: AgendaType;
  types: AgendaType[];
  fields: Record<string, TemplateField>;
  required: string[];
  title?: string;
  duration_minutes?: number;
  recurrence?: string;
}

/** Fixed colours per owner (same as the old WebUI page); others hash into the 8 calendar tokens. */
const FIXED_COLORS: Record<string, number> = { user: 1, hephaestus: 2, athena: 4, scout: 3, chronos: 6, metis: 5, argus: 7 };
export function colorFor(owner: string): string {
  const fixed = FIXED_COLORS[owner];
  if (fixed) return `var(--cal-${fixed})`;
  let h = 0;
  for (const c of owner) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return `var(--cal-${(h % 8) + 1})`;
}

/** Plain-language meaning of a window, by module (fallback: generic). */
export const WINDOW_TEXT: Record<string, string> = {
  athena: 'Athena può lavorare (consolidare memoria, analisi) solo in questo intervallo, di solito quando sei inattivo. Fuori dalla finestra non parte.',
  metis: 'Metis può addestrare i modelli solo in questo intervallo, per non rallentare il PC mentre lo usi.',
  hephaestus: 'Forge può usare il motore indicato (es. Claude Pro) solo in questo intervallo.',
};

export interface MoveRequest { ev: CalEvent; start: Date; end: Date | null; }
export interface SelectRequest { ev: CalEvent; rect: DOMRect; }

export function dur(ms: number): string {
  return ms < 1000 ? `${ms} ms` : ms < 60_000 ? `${(ms / 1000).toFixed(1).replace('.', ',')} s` : `${Math.round(ms / 60_000)} min`;
}

/** Bubbling + composed custom event (views → page). */
export function fire(el: EventTarget, name: string, detail?: unknown): void {
  el.dispatchEvent(new CustomEvent(name, { detail, bubbles: true, composed: true }));
}
