/** Small formatting helpers shared by the Oracle page and widget. */
export const API = '/api/ui';

export const ROUTES: Record<string, { label: string; tone: string }> = {
  quick: { label: 'rapida', tone: 'neutral' },
  quick_chat: { label: 'conversazione', tone: 'info' },
  agent: { label: 'agente', tone: 'accent' },
};

export function num(n: number | null | undefined): string {
  const v = Number(n || 0);
  return Math.abs(v) >= 10000 ? new Intl.NumberFormat('it-IT', { notation: 'compact', maximumFractionDigits: 1 }).format(v)
    : new Intl.NumberFormat('it-IT').format(Math.round(v));
}

export function cost(usd: number | null | undefined): string {
  const v = Number(usd || 0);
  if (!v) return '0 $';
  return `${v < 0.01 ? v.toFixed(4) : v.toFixed(2)} $`.replace('.', ',');
}

export function ms(n: number | null | undefined): string {
  const v = Number(n || 0);
  if (v < 1000) return `${v} ms`;
  if (v < 60000) return `${(v / 1000).toFixed(1).replace('.', ',')} s`;
  return `${Math.floor(v / 60000)} min ${Math.round((v % 60000) / 1000)} s`;
}

/** Epoch seconds → "14:03" today, "12 ott 14:03" otherwise. */
export function when(ts: number | null | undefined): string {
  if (!ts) return '–';
  const d = new Date(ts * 1000);
  const today = new Date().toDateString() === d.toDateString();
  return today ? d.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' })
    : d.toLocaleString('it-IT', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}

export function ago(seconds: number | null | undefined): string {
  if (seconds == null) return 'nessuna chat da quando Oracle è partito';
  if (seconds < 60) return 'adesso';
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min fa`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h fa`;
  return `${Math.floor(seconds / 86400)} giorni fa`;
}

export function dayLabel(iso: string): string {
  const d = new Date(iso + 'T12:00:00');
  return d.toLocaleDateString('it-IT', { day: 'numeric', month: 'numeric' });
}
