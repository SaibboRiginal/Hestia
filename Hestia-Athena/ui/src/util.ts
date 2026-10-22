/** Labels and helpers shared by the Athena page and widget. */
export const API = '/api/athena';

export const KINDS: Record<string, string> = {
  advisory: 'consiglio', remediation: 'riparazione', notification: 'avviso', maintenance: 'manutenzione',
  improvement: 'miglioramento', setting: 'impostazione', observation: 'osservazione',
};

export const OUTCOMES: Record<string, { label: string; tone: string }> = {
  emitted: { label: 'inviata a te', tone: 'success' },
  forge: { label: 'passata a Forge', tone: 'success' },
  forge_skipped: { label: 'Forge: saltata (limite o già proposta)', tone: 'warning' },
  setting_proposed: { label: 'proposta di impostazione', tone: 'success' },
  setting_skipped: { label: 'impostazione: saltata', tone: 'warning' },
  observed: { label: 'nel recap della sera', tone: 'success' },
  failed: { label: 'invio non riuscito', tone: 'danger' },
  discarded: { label: 'scartata', tone: 'neutral' },
};

/** Gate factors in display order (weights come from the API). */
export const FACTORS: Array<{ key: string; label: string; inverse?: boolean }> = [
  { key: 'urgency', label: 'Urgenza' },
  { key: 'usefulness', label: 'Utilità' },
  { key: 'novelty', label: 'Novità' },
  { key: 'confidence', label: 'Sicurezza' },
  { key: 'interruption_cost', label: 'Disturbo', inverse: true },
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
  return `${Math.floor(s / 86400)} giorni fa`;
}

export function secs(ms?: number): string {
  const v = Number(ms || 0);
  return v < 1000 ? `${v} ms` : `${(v / 1000).toFixed(1).replace('.', ',')} s`;
}

export const pct = (v: number) => `${Math.round(Math.max(0, Math.min(1, Number(v) || 0)) * 100)}%`;

/** Life areas in user words (never module names). */
export const AREAS: Record<string, string> = {
  fitness: 'Allenamento', selfcare: 'Cura di sé', finance: 'Spese', wardrobe: 'Guardaroba', real_estate: 'Case',
  cognition: 'Hestia',
};
export const area = (d?: string) => (d && AREAS[d]) || d || '';

export const SEVERITY: Record<string, { label: string; tone: string; icon: string }> = {
  alta: { label: 'importante', tone: 'danger', icon: 'alert' },
  attenzione: { label: 'da guardare', tone: 'warning', icon: 'eye' },
  info: { label: 'informazione', tone: 'neutral', icon: 'info' },
};

/** «Allenamenti → Routine rispettate % (stessa settimana): salgono insieme, r +0,72 su 9 settimane». */
export function linkText(l: any): string {
  const when = l.lag ? 'la settimana dopo' : 'stessa settimana';
  const dir = l.r > 0 ? 'salgono insieme' : 'uno sale, l\'altro scende';
  return `${l.a_label} → ${l.b_label} (${when}): ${dir}, r ${l.r > 0 ? '+' : ''}${Number(l.r).toFixed(2).replace('.', ',')} su ${l.weeks} settimane`;
}
