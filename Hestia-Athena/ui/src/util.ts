import { tr } from '@hestia/webui-sdk';
/** Labels and helpers shared by the Athena page and widget. */
export const API = '/api/athena';

export const KINDS: Record<string, string> = {
  advisory: 'consiglio', remediation: 'riparazione', notification: 'avviso', maintenance: 'manutenzione',
  improvement: 'miglioramento', setting: 'impostazione', observation: 'osservazione',
};

export const OUTCOMES: Record<string, { label: string; tone: string }> = {
  emitted: { label: tr('inviata a te'), tone: 'success' },
  collecting: { label: 'raccolgo prove', tone: 'neutral' },
  forge: { label: tr('passata a Forge'), tone: 'success' },
  forge_skipped: { label: tr('Forge: saltata (limite o già proposta)'), tone: 'warning' },
  setting_proposed: { label: tr('proposta di impostazione'), tone: 'success' },
  setting_skipped: { label: 'impostazione: saltata', tone: 'warning' },
  observed: { label: tr('nel recap della sera'), tone: 'success' },
  failed: { label: tr('invio non riuscito'), tone: 'danger' },
  discarded: { label: 'scartata', tone: 'neutral' },
};

/** Gate factors in display order (weights come from the API). */
export const FACTORS: Array<{ key: string; label: string; inverse?: boolean }> = [
  { key: 'urgency', label: tr('Urgenza') },
  { key: 'usefulness', label: tr('Utilità') },
  { key: 'novelty', label: tr('Novità') },
  { key: 'confidence', label: tr('Sicurezza') },
  { key: 'interruption_cost', label: tr('Disturbo'), inverse: true },
];

export function when(iso?: string | number | null): string {
  if (!iso) return '–';
  const d = typeof iso === 'number' ? new Date(iso * 1000) : new Date(iso);
  const today = new Date().toDateString() === d.toDateString();
  return today ? `oggi ${d.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' })}`
    : d.toLocaleString('it-IT', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}

export function ago(iso?: string | null): string {
  if (!iso) return '';
  const s = Math.max(0, (Date.now() - Date.parse(iso)) / 1000);
  if (s < 60) return 'adesso';
  if (s < 3600) return `${Math.floor(s / 60)} min fa`;
  if (s < 86400) return `${Math.floor(s / 3600)} h fa`;
  return tr("{0} giorni fa", Math.floor(s / 86400));
}

/** «12 nov» from an ISO day. */
export function day(iso?: string | null): string {
  if (!iso) return '–';
  return new Date(`${iso}T12:00:00`).toLocaleDateString('it-IT', { day: 'numeric', month: 'short' });
}

/** «3 ore fa» / «2 giorni fa» from seconds. */
export function hours(seconds: number): string {
  const s = Math.max(0, Number(seconds) || 0);
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))} min fa`;
  if (s < 172800) return tr("{0} ore fa", Math.round(s / 3600));
  return tr("{0} giorni fa", Math.round(s / 86400));
}

export function secs(ms?: number): string {
  const v = Number(ms || 0);
  return v < 1000 ? `${v} ms` : `${(v / 1000).toFixed(1).replace('.', ',')} s`;
}

export const pct = (v: number) => `${Math.round(Math.max(0, Math.min(1, Number(v) || 0)) * 100)}%`;

/** Life areas in user words (never module names). */
export const AREAS: Record<string, string> = {
  fitness: tr('Allenamento'), selfcare: tr('Cura di sé'), finance: tr('Spese'), wardrobe: tr('Guardaroba'), real_estate: tr('Case'),
  cognition: 'Hestia',
};
export const area = (d?: string) => (d && AREAS[d]) || d || '';

export const SEVERITY: Record<string, { label: string; tone: string; icon: string }> = {
  alta: { label: 'importante', tone: 'danger', icon: 'alert' },
  attenzione: { label: tr('da guardare'), tone: 'warning', icon: 'eye' },
  info: { label: 'informazione', tone: 'neutral', icon: 'info' },
};

/** «Allenamenti → Routine rispettate % (stessa settimana): salgono insieme, r +0,72 su 9 settimane». */
export function linkText(l: any): string {
  const when = l.lag ? tr('la settimana dopo') : tr('stessa settimana');
  const dir = l.r > 0 ? 'salgono insieme' : 'uno sale, l\'altro scende';
  return tr("{0} → {1} ({2}): {3}, r {4}{5} su {6} settimane", l.a_label, l.b_label, when, dir, l.r > 0 ? '+' : '', Number(l.r).toFixed(2).replace('.', ','), l.weeks);
}
