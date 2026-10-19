/** Shared helpers of the Chronos plugin (Italian labels, it-IT dates). */
import type { HestiaHost } from '@hestia/webui-sdk';

export const API = '/api/agenda';

export function when(iso?: string | null): string {
  if (!iso) return '–';
  const d = new Date(iso);
  return d.toDateString() === new Date().toDateString()
    ? d.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' })
    : d.toLocaleString('it-IT', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}

export function ms(v?: number | null): string {
  if (v === null || v === undefined) return '';
  return v < 1000 ? `${v} ms` : v < 60000 ? `${(v / 1000).toFixed(1).replace('.', ',')} s` : `${Math.round(v / 60000)} min`;
}

export const STATUS: Record<string, { text: string; tone: string }> = {
  ok: { text: 'riuscito', tone: 'success' },
  failed: { text: 'fallito', tone: 'danger' },
  skipped: { text: 'saltato', tone: 'neutral' },
};

/** «Riprova»: the agenda's existing run-now action. Returns true when the run went fine. */
export async function retry(host: HestiaHost, key: string, title: string): Promise<boolean> {
  const r = await host.api('POST', `${API}/items/${encodeURIComponent(key)}/run`);
  if (!r.ok) { host.toast(r.error || `${title}: non avviato`, 'danger'); return false; }
  const ok = !!r.data?.ok;
  const back = ok && r.data?.reactivated ? ' · regola riattivata' : '';
  host.toast(ok ? `${title}: eseguito${back}` : `${title}: fallito di nuovo`, ok ? 'success' : 'danger');
  return ok;
}
