/** Date helpers (local time, Monday-first weeks, Italian labels). No external libs. */

export const DAY_MS = 86_400_000;
const LOCALE = 'it-IT';

export function startOfDay(d: Date): Date { const x = new Date(d); x.setHours(0, 0, 0, 0); return x; }
export function addDays(d: Date, n: number): Date { const x = new Date(d); x.setDate(x.getDate() + n); return x; }
export function addMonths(d: Date, n: number): Date { const x = new Date(d); x.setDate(1); x.setMonth(x.getMonth() + n); return x; }
export function addMinutes(d: Date, n: number): Date { return new Date(d.getTime() + n * 60_000); }
export function startOfWeek(d: Date): Date { const x = startOfDay(d); const wd = (x.getDay() + 6) % 7; return addDays(x, -wd); }
export function startOfMonth(d: Date): Date { const x = startOfDay(d); x.setDate(1); return x; }
export function isSameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}
export function isToday(d: Date): boolean { return isSameDay(d, new Date()); }
export function minutesOfDay(d: Date): number { return d.getHours() * 60 + d.getMinutes(); }
export function dayKey(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/** 6×7 grid for a month view, starting Monday. */
export function monthGrid(anchor: Date): Date[] {
  const start = startOfWeek(startOfMonth(anchor));
  return Array.from({ length: 42 }, (_, i) => addDays(start, i));
}

export const fmt = {
  monthYear: (d: Date) => cap(d.toLocaleDateString(LOCALE, { month: 'long', year: 'numeric' })),
  dayLong: (d: Date) => cap(d.toLocaleDateString(LOCALE, { weekday: 'long', day: 'numeric', month: 'long' })),
  dayShort: (d: Date) => cap(d.toLocaleDateString(LOCALE, { weekday: 'short', day: 'numeric' })),
  weekdayShort: (d: Date) => cap(d.toLocaleDateString(LOCALE, { weekday: 'short' })),
  dayMonth: (d: Date) => d.toLocaleDateString(LOCALE, { day: 'numeric', month: 'short' }),
  time: (d: Date) => d.toLocaleTimeString(LOCALE, { hour: '2-digit', minute: '2-digit' }),
  dateTime: (d: Date) => `${d.toLocaleDateString(LOCALE, { weekday: 'short', day: 'numeric', month: 'short' })} ${fmt.time(d)}`,
  relative: (d: Date) => {
    const diff = Math.round((d.getTime() - Date.now()) / 60_000);
    const abs = Math.abs(diff);
    const s = abs < 60 ? `${abs} min` : abs < 1440 ? `${Math.round(abs / 60)} h` : `${Math.round(abs / 1440)} g`;
    return diff >= 0 ? `tra ${s}` : `${s} fa`;
  },
};

/** <input type="datetime-local"> value ↔ Date (local time). */
export function toLocalInput(d: Date): string {
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}
export function fromLocalInput(v: string): Date | null { if (!v) return null; const d = new Date(v); return isNaN(d.getTime()) ? null : d; }

export const WEEKDAYS = ['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU'] as const;
export const WEEKDAY_LABELS: Record<string, string> = { MO: 'Lun', TU: 'Mar', WE: 'Mer', TH: 'Gio', FR: 'Ven', SA: 'Sab', SU: 'Dom' };

function cap(s: string): string { return s.charAt(0).toUpperCase() + s.slice(1); }

/** Snap a Date to `step` minutes. */
export function snap(d: Date, step = 15): Date {
  const x = new Date(d);
  x.setMinutes(Math.round(x.getMinutes() / step) * step, 0, 0);
  return x;
}
