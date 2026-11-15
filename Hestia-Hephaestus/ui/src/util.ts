import { tr } from '@hestia/webui-sdk';
/** Shared helpers of the Hephaestus plugin. Every path stays under the manifest api_prefix /api/hephaestus/. */
export const API = '/api/hephaestus';
export const FORGE = `${API}/forge`;

/** Remediation task states → Italian label + tone. */
export const STATE: Record<string, { label: string; tone: string }> = {
  pending_approval: { label: tr('da approvare'), tone: 'warning' },
  running: { label: tr('in corso'), tone: 'info' },
  succeeded: { label: 'riuscita', tone: 'success' },
  failed: { label: 'fallita', tone: 'danger' },
  rolled_back: { label: 'annullata', tone: 'neutral' },
  escalated: { label: tr('passata a Forge'), tone: 'accent' },
};

export const CONSENT: Record<string, string> = {
  none: 'nessuno', low: 'basso (sola lettura)', medium: 'medio', high: tr('alto (serve il tuo ok)'),
};

/** Claude budget phases (Forge claude_budget). */
export const PHASE: Record<string, { label: string; tone: string }> = {
  night: { label: 'finestra notturna', tone: 'success' },
  final: { label: tr('ultime ore'), tone: 'accent' },
  closed: { label: 'chiusa', tone: 'neutral' },
  exhausted: { label: 'quota esaurita', tone: 'danger' },
};

export function when(iso?: string | null): string {
  if (!iso) return '–';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '–';
  return d.toLocaleString('it-IT', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false });
}

export const short = (id?: string | null) => String(id || '').slice(0, 8);
