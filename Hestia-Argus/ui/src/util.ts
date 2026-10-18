import { css } from '@hestia/webui-sdk';

export const API = '/api/argus';

export const STATUS: Record<string, [string, string]> = {
  up: ['success', 'ok'], degraded: ['warning', 'degradato'], down: ['danger', 'giù'],
};

export function statusOf(s?: string | null): [string, string] {
  return (s && STATUS[s]) || ['neutral', s || 'nessun dato'];
}

/** epoch seconds → "12 s fa" / "5 min fa" / date. */
export function ago(epoch?: number | null): string {
  if (!epoch) return '–';
  const s = Math.max(0, Math.round(Date.now() / 1000 - epoch));
  if (s < 60) return `${s} s fa`;
  if (s < 3600) return `${Math.round(s / 60)} min fa`;
  if (s < 86400) return `${Math.round(s / 3600)} h fa`;
  return when(epoch);
}

export function when(epoch?: number | null): string {
  if (!epoch) return '–';
  return new Date(epoch * 1000).toLocaleString('it-IT', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}

export function duration(sec?: number | null): string {
  if (sec == null) return '–';
  if (sec < 60) return `${Math.round(sec)} s`;
  if (sec < 3600) return `${Math.round(sec / 60)} min`;
  const h = Math.floor(sec / 3600), m = Math.round((sec % 3600) / 60);
  return m ? `${h} h ${m} min` : `${h} h`;
}

export const stripStyles = css`
  .strip { display: flex; gap: 1px; height: 14px; border-radius: var(--radius-xs, 3px); overflow: hidden; }
  .strip span { flex: 1; min-width: 1px; background: var(--surface-3); }
  .strip .u { background: var(--success); } .strip .w { background: var(--warning); } .strip .d { background: var(--danger); }
  .tnum { font-variant-numeric: tabular-nums; }
`;
