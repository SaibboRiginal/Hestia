/** Shared helpers of the Hermes plugin (labels in Italian, dates in it-IT). */
import { css } from '@hestia/webui-sdk';

export const API = '/api/ui';

export function when(iso?: string | null): string {
  if (!iso) return '–';
  const d = new Date(iso);
  const today = new Date();
  const sameDay = d.toDateString() === today.toDateString();
  return sameDay
    ? d.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' })
    : d.toLocaleString('it-IT', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}

/** Local midnight as ISO (what "oggi" means for the user). */
export function todayStart(): string {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  return d.toISOString();
}

export const CLIENT_STATE: Record<string, { text: string; tone: string }> = {
  delivered: { text: 'consegnata', tone: 'success' },
  skipped: { text: 'solo elenco', tone: 'neutral' },
  failed: { text: 'fallita', tone: 'danger' },
  dead: { text: 'abbandonata', tone: 'danger' },
};

export const LEVEL_TONE: Record<string, string> = {
  info: 'info', success: 'success', warning: 'warning', error: 'danger', critical: 'danger',
};

export const hermesStyles = css`
  .pill { display: inline-flex; align-items: center; gap: 4px; font-size: 11px; padding: 1px 8px; border-radius: 99px;
    background: var(--surface-2); color: var(--text-2); white-space: nowrap; }
  .tnum { font-variant-numeric: tabular-nums; }
`;
