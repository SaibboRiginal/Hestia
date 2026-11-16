import { locale, tr } from '@hestia/webui-sdk';
/** Shared helpers of the Hephaestus plugin. Every path stays under the manifest api_prefix /api/hephaestus/. */
export const API = '/api/hephaestus';
export const FORGE = `${API}/forge`;

/** Remediation task states → Italian label + tone. */
export const STATE: Record<string, { label: string; tone: string }> = {
  pending_approval: { label: tr('to approve'), tone: 'warning' },
  running: { label: tr('running'), tone: 'info' },
  succeeded: { label: tr('f::succeeded'), tone: 'success' },
  failed: { label: tr('f::failed'), tone: 'danger' },
  rolled_back: { label: tr('f::undone'), tone: 'neutral' },
  escalated: { label: tr('handed to Forge'), tone: 'accent' },
};

export const CONSENT: Record<string, string> = {
  none: tr('f::none'), low: tr('low (read only)'), medium: tr('medium'), high: tr('high (needs your ok)'),
};

/** Claude budget phases (Forge claude_budget). */
export const PHASE: Record<string, { label: string; tone: string }> = {
  night: { label: tr('night window'), tone: 'success' },
  final: { label: tr('last hours'), tone: 'accent' },
  closed: { label: tr('f::closed'), tone: 'neutral' },
  exhausted: { label: tr('quota used up'), tone: 'danger' },
};

export function when(iso?: string | null): string {
  if (!iso) return '–';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '–';
  return d.toLocaleString(locale(), { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false });
}

export const short = (id?: string | null) => String(id || '').slice(0, 8);
