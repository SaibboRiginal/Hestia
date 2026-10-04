/**
 * Calendar view preferences (per browser). Spec: docs/work/2026-10-04-calendar-skills-forge-ui/SPEC.md §A2–A6.
 *
 * Focused view (visibility policy):
 *  - manual items (created by you)           → always
 *  - the focused day (picked / day view)     → everything
 *  - frequent module rules (≥ frequentPerDay) → next `frequentDays` days
 *  - rare module rules                        → next `rareCount` occurrences or `rareDays` days, whichever ends first
 *  - one-off module items                     → always (future); past only when failed
 *  - past module items                        → only failed runs, last `pastDays` days, one per rule ("×N")
 */
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
