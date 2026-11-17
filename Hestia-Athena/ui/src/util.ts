import { assistantName, locale, tr } from '@hestia/webui-sdk';
/** Labels and helpers shared by the Athena page and widget. */
export const API = '/api/athena';

export const KINDS: Record<string, string> = {
  advisory: tr('advice'), remediation: tr('repair'), notification: tr('notice'), maintenance: tr('maintenance'),
  improvement: tr('improvement'), setting: tr('setting'), observation: tr('observation'),
};

export const OUTCOMES: Record<string, { label: string; tone: string }> = {
  emitted: { label: tr('sent to you'), tone: 'success' },
  collecting: { label: tr('collecting evidence'), tone: 'neutral' },
  forge: { label: tr('handed to Forge'), tone: 'success' },
  forge_skipped: { label: tr('Forge: skipped (limit or already proposed)'), tone: 'warning' },
  setting_proposed: { label: tr('setting proposal'), tone: 'success' },
  setting_skipped: { label: tr('setting: skipped'), tone: 'warning' },
  observed: { label: tr('in the evening recap'), tone: 'success' },
  failed: { label: tr('sending failed'), tone: 'danger' },
  discarded: { label: tr('f::discarded'), tone: 'neutral' },
};

/** Gate factors in display order (weights come from the API). */
export const FACTORS: Array<{ key: string; label: string; inverse?: boolean }> = [
  { key: 'urgency', label: tr('Urgency') },
  { key: 'usefulness', label: tr('Utilities') },
  { key: 'novelty', label: tr('News') },
  { key: 'confidence', label: tr('Confidence') },
  { key: 'interruption_cost', label: tr('Trouble'), inverse: true },
];

export function when(iso?: string | number | null): string {
  if (!iso) return '–';
  const d = typeof iso === 'number' ? new Date(iso * 1000) : new Date(iso);
  const today = new Date().toDateString() === d.toDateString();
  return today ? tr('today {0}', d.toLocaleTimeString(locale(), { hour: '2-digit', minute: '2-digit' }))
    : d.toLocaleString(locale(), { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}

export function ago(iso?: string | null): string {
  if (!iso) return '';
  const s = Math.max(0, (Date.now() - Date.parse(iso)) / 1000);
  if (s < 60) return tr('just now');
  if (s < 3600) return `${Math.floor(s / 60)} min fa`;
  if (s < 86400) return `${Math.floor(s / 3600)} h fa`;
  return tr("{0} days ago", Math.floor(s / 86400));
}

/** «12 nov» from an ISO day. */
export function day(iso?: string | null): string {
  if (!iso) return '–';
  return new Date(`${iso}T12:00:00`).toLocaleDateString(locale(), { day: 'numeric', month: 'short' });
}

/** «3 ore fa» / «2 giorni fa» from seconds. */
export function hours(seconds: number): string {
  const s = Math.max(0, Number(seconds) || 0);
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))} min fa`;
  if (s < 172800) return tr("{0} hours ago", Math.round(s / 3600));
  return tr("{0} days ago", Math.round(s / 86400));
}

export function secs(ms?: number): string {
  const v = Number(ms || 0);
  return v < 1000 ? `${v} ms` : `${(v / 1000).toFixed(1).replace('.', ',')} s`;
}

export const pct = (v: number) => `${Math.round(Math.max(0, Math.min(1, Number(v) || 0)) * 100)}%`;

/** Life areas in user words (never module names). */
export const AREAS: Record<string, string> = {
  fitness: tr('Training'), selfcare: tr('Self care'), finance: tr('Expenses'), wardrobe: tr('Wardrobe'), real_estate: tr('Houses'),
  cognition: assistantName(),
};
export const area = (d?: string) => (d && AREAS[d]) || d || '';

export const SEVERITY: Record<string, { label: string; tone: string; icon: string }> = {
  alta: { label: tr('important'), tone: 'danger', icon: 'alert' },
  attenzione: { label: tr('to watch'), tone: 'warning', icon: 'eye' },
  info: { label: tr('information'), tone: 'neutral', icon: 'info' },
};

/** «Allenamenti → Routine rispettate % (stessa settimana): salgono insieme, r +0,72 su 9 settimane». */
export function linkText(l: any): string {
  const when = l.lag ? tr('the week after') : tr('same week');
  const dir = l.r > 0 ? tr('they rise together') : tr('one rises, the other falls');
  return tr("{0} → {1} ({2}): {3}, r {4}{5} over {6} weeks", l.a_label, l.b_label, when, dir, l.r > 0 ? '+' : '', Number(l.r).toFixed(2).replace('.', ','), l.weeks);
}
