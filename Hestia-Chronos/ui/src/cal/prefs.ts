/**
 * Calendar view preferences, per user on this device: the SDK key-value store (`host.store('agenda')`, IndexedDB),
 * localStorage when IndexedDB is not available. The first load also picks up the old WebUI page's
 * `hestia_calendar_prefs` (same origin), so nothing is lost when the page moves into the plugin.
 *
 * Focused view (visibility policy):
 *  - manual items (created by you)           → always
 *  - the focused day (picked / day view)     → everything
 *  - frequent module rules (≥ frequentPerDay) → next `frequentDays` days
 *  - rare module rules                        → next `rareCount` occurrences or `rareDays` days, whichever ends first
 *  - one-off module items                     → always (future); past only when failed
 *  - past module items                        → only failed runs, last `pastDays` days, one per rule ("×N")
 */
import type { HestiaHost } from '@hestia/webui-sdk';
import type { AgendaType, CalView } from './models';

export type WindowsMode = 'lane' | 'band' | 'hidden';
export type FrequentMode = 'compact' | 'full' | 'hidden';

export interface CalendarPrefs {
  windowsMode: WindowsMode;
  frequentMode: FrequentMode;
  frequentPerDay: number;
  focused: boolean;
  frequentDays: number;
  rareCount: number;
  rareDays: number;
  pastDays: number;
  scrollHour: number;
  /** Working hours (Mon–Fri): outside them the time grid is shaded. workEnd <= workStart = off. */
  workStart: number;
  workEnd: number;
}

export const DEFAULT_PREFS: CalendarPrefs = {
  windowsMode: 'lane', frequentMode: 'compact', frequentPerDay: 3,
  focused: true, frequentDays: 7, rareCount: 3, rareDays: 7, pastDays: 7, scrollHour: 7,
  workStart: 9, workEnd: 18,
};

/** Everything the page remembers. */
export interface SavedPrefs {
  view?: CalView; hiddenOwners?: string[]; hiddenTypes?: AgendaType[]; showSkipped?: boolean; showDone?: boolean;
  vp?: Partial<CalendarPrefs>; sideW?: number;
}

const KEY = 'prefs';
const LEGACY = 'hestia_calendar_prefs';     // old WebUI calendar page (localStorage)
const LOCAL = 'hestia.chronos.agenda.prefs';

export async function loadPrefs(host: HestiaHost): Promise<SavedPrefs> {
  try {
    const v = await host.store('agenda').get<SavedPrefs>(KEY);
    if (v) return v;
  } catch { /* no IndexedDB → localStorage */ }
  for (const k of [LOCAL, LEGACY]) {
    try { const raw = localStorage.getItem(k); if (raw) return JSON.parse(raw); } catch { /* private mode */ }
  }
  return {};
}

export async function savePrefs(host: HestiaHost, p: SavedPrefs): Promise<void> {
  try { await host.store('agenda').set(KEY, p); return; } catch { /* fall back */ }
  try { localStorage.setItem(LOCAL, JSON.stringify(p)); } catch { /* private mode */ }
}

/** Occurrences per day implied by an RRULE (null = cannot tell → count the loaded occurrences). */
export function perDayFromRRule(rule: string | null | undefined): number | null {
  if (!rule) return 0;
  const parts = Object.fromEntries(rule.replace(/^RRULE:/i, '').split(';').map(p => p.split('=') as [string, string]));
  const interval = Math.max(1, Number(parts['INTERVAL'] || 1));
  const count = (k: string) => (parts[k] ? parts[k].split(',').length : 1);
  switch ((parts['FREQ'] || '').toUpperCase()) {
    case 'SECONDLY': return 86400 / interval;
    case 'MINUTELY': return 1440 / interval;
    case 'HOURLY': return 24 / interval;
    case 'DAILY': return (count('BYHOUR') * count('BYMINUTE')) / interval;
    case 'WEEKLY': return (count('BYDAY') * count('BYHOUR')) / (7 * interval);
    default: return null;
  }
}
