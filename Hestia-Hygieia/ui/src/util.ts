/** Hygieia UI helpers: API calls, labels, formatting and shared styles of pages and widgets. */
import { css } from '@hestia/webui-sdk';
import type { ApiResult, HestiaHost, HttpMethod, Tone } from '@hestia/webui-sdk';

export const API = '/api/selfcare';

/** Call the module; a failed write shows a toast with the module's message. */
export async function call<T = any>(host: HestiaHost, method: HttpMethod, path: string,
                                    opts?: { query?: Record<string, any>; body?: unknown; quiet?: boolean }): Promise<ApiResult<T>> {
  const r = await host.api<T>(method, path.startsWith('/') ? path : `${API}/${path}`, opts);
  if (!r.ok && !opts?.quiet && method !== 'GET') {
    const msg = r.error === 'offline' || r.status === 0 ? 'Non raggiungibile, riprova' : r.error || 'Errore';
    host.toast(msg, 'warning');
  }
  return r;
}

let metaCache: { at: number; data: any } | null = null;
/** Lists (areas, categories, actives…) change rarely: cached for 5 minutes per page load. */
export async function meta(host: HestiaHost, fresh = false): Promise<any> {
  if (!fresh && metaCache && Date.now() - metaCache.at < 300000) return metaCache.data;
  const r = await host.api('GET', `${API}/meta`);
  if (r.ok) metaCache = { at: Date.now(), data: r.data };
  return metaCache?.data ?? null;
}
export const dropMeta = () => { metaCache = null; };

export const label = (list: any[] | undefined, value: string) => (list || []).find(o => o.value === value)?.label || value;

export const STATE: Record<string, { text: string; tone: Tone }> = {
  done: { text: 'Fatta', tone: 'success' }, due: { text: 'Da fare', tone: 'warning' }, suggested: { text: 'Consigliata', tone: 'accent' },
  wait: { text: 'Aspetta', tone: 'neutral' }, ok: { text: 'In regola', tone: 'success' }, off: { text: 'Non oggi', tone: 'neutral' },
  rest: { text: 'Quando vuoi', tone: 'neutral' }, blocked: { text: 'Non oggi', tone: 'danger' }, paused: { text: 'In pausa', tone: 'neutral' },
};
export const STEP_STATE: Record<string, string> = {
  due: 'tocca oggi', suggested: 'consigliato oggi', wait: 'non serve oggi', ok: 'obiettivo raggiunto', blocked: 'non oggi',
  paused: 'in pausa', off: 'non oggi', rest: 'se vuoi', always: '',
};
export const SLOT_ICON: Record<string, string> = { morning: '☀️', evening: '🌙', anytime: '✨' };
export const STATUS_TONE: Record<string, Tone> = {
  in_use: 'success', stock: 'info', paused: 'neutral', wishlist: 'accent', finished: 'neutral', discarded: 'danger',
};
export const WEEKDAYS = ['Lun', 'Mar', 'Mer', 'Gio', 'Ven', 'Sab', 'Dom'];
export const AREA_EMOJI: Record<string, string> = {
  viso: '🧴', occhi: '👁️', labbra: '👄', capelli: '💇', cuoio_capelluto: '💆', barba: '🧔', corpo: '🛁', mani: '🤲',
  piedi: '🦶', unghie: '💅', denti: '🦷', profumo: '🌸',
};

export function localDay(d: Date = new Date()): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}
export const today = () => localDay();
export function addDays(iso: string, n: number): string {
  const d = new Date(iso + 'T12:00:00');
  d.setDate(d.getDate() + n);
  return localDay(d);
}
export function dayLabel(iso: string | null | undefined, withWeekday = true): string {
  if (!iso) return '';
  const d = iso.length === 10 ? new Date(iso + 'T12:00:00') : new Date(iso);
  const ld = localDay(d);
  if (ld === today()) return 'Oggi';
  if (ld === addDays(today(), -1)) return 'Ieri';
  if (ld === addDays(today(), 1)) return 'Domani';
  return d.toLocaleDateString('it-IT', withWeekday ? { weekday: 'short', day: 'numeric', month: 'short' } : { day: 'numeric', month: 'short', year: '2-digit' });
}
export function relDays(iso: string | null | undefined): string {
  if (!iso) return 'mai';
  const days = Math.round((Date.parse(today() + 'T12:00:00') - Date.parse(iso.slice(0, 10) + 'T12:00:00')) / 86400000);
  return days <= 0 ? 'oggi' : days === 1 ? 'ieri' : days < 14 ? `${days} giorni fa` : days < 60 ? `${Math.round(days / 7)} settimane fa` : `${Math.round(days / 30)} mesi fa`;
}
export function inDays(n: number | null | undefined): string {
  if (n === null || n === undefined) return '';
  if (n < 0) return `scaduto da ${-n} g`;
  if (n === 0) return 'oggi';
  return n < 60 ? `tra ${n} g` : `tra ${Math.round(n / 30)} mesi`;
}
export function money(x: number | null | undefined, currency = 'EUR'): string {
  if (x === null || x === undefined) return '–';
  return Number(x).toLocaleString('it-IT', { style: 'currency', currency });
}
export function secs(s: number): string {
  const v = Math.max(0, Math.round(s));
  return v >= 60 ? `${Math.floor(v / 60)}:${String(v % 60).padStart(2, '0')}` : `${v}s`;
}
export const productName = (p: any) => p ? `${p.brand ? p.brand + ' ' : ''}${p.name}` : '';

export function cadenceText(c: any): string {
  if (!c) return '';
  if (c.mode === 'daily') return 'Ogni giorno';
  if (c.mode === 'as_needed') return 'Quando capita';
  if (c.mode === 'fixed_days') return (c.days || []).length ? 'Ogni ' + c.days.map((d: number) => WEEKDAYS[d].toLowerCase()).join(', ') : 'Giorni fissi';
  const t = c.times || 1;
  return `Almeno ${t} ${t === 1 ? 'volta' : 'volte'} a${c.per === 'month' ? 'l mese' : ' settimana'}`;
}

export function search(items: any[], q: string, fields: (it: any) => string): any[] {
  const n = (s: string) => (s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
  const words = n(q).split(/\s+/).filter(Boolean);
  if (!words.length) return items;
  return items.filter(it => { const hay = n(fields(it)); return words.every(w => hay.includes(w)); });
}

/** Shared styles of Hygieia pages (on top of the kit). */
export const hygieiaStyles = css`
  h1 { font-size: 22px; font-weight: 650; margin: 0; letter-spacing: -.01em; }
  h2 { font-size: 15px; font-weight: 600; margin: 0; }
  h3 { font-size: 12px; font-weight: 600; margin: 0; color: var(--text-2); text-transform: uppercase; letter-spacing: .05em; }
  .head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .head .sub { color: var(--text-3); font-size: 13px; }
  .nav { display: flex; gap: 6px; flex-wrap: wrap; }
  .tabs { display: flex; gap: 4px; flex-wrap: wrap; }
  .tab { border: 1px solid var(--border); background: var(--surface); color: var(--text-2); border-radius: var(--radius-full);
    padding: 6px 12px; font: inherit; font-size: 13px; cursor: pointer; }
  .tab[aria-pressed=true] { background: var(--accent-soft); color: var(--accent); border-color: transparent; font-weight: 600; }
  .chips { display: flex; gap: 6px; flex-wrap: wrap; }
  .chip { border: 1px solid var(--border-strong); background: var(--surface); color: var(--text); border-radius: var(--radius-full);
    padding: 6px 12px; font: inherit; font-size: 13px; cursor: pointer; min-height: 34px; }
  .chip[aria-pressed=true] { background: var(--accent); border-color: var(--accent); color: var(--accent-contrast); }
  input.in, select.in, textarea.in { font: inherit; color: var(--text); background: var(--surface-2); border: 1px solid var(--border-strong);
    border-radius: var(--radius-sm); padding: 7px 10px; outline: none; min-width: 0; }
  input.in:focus, select.in:focus, textarea.in:focus { border-color: var(--accent); box-shadow: 0 0 0 3px var(--focus-ring); }
  input.num { width: 76px; text-align: center; font-variant-numeric: tabular-nums; }
  .tnum { font-variant-numeric: tabular-nums; }
  .pill { display: inline-flex; align-items: center; gap: 4px; font-size: 12px; color: var(--text-2); background: var(--surface-2);
    border-radius: var(--radius-full); padding: 2px 8px; white-space: nowrap; }
  .pill.warn { color: var(--warning); } .pill.bad { color: var(--danger); } .pill.good { color: var(--success); }
  .between { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
  .link { color: var(--accent); cursor: pointer; background: none; border: none; font: inherit; padding: 0; }
  .empty { color: var(--text-3); font-size: 13px; padding: 8px 0; }
  .list { display: flex; flex-direction: column; }
  .li { display: flex; align-items: center; gap: 10px; padding: 10px 4px; border-bottom: 1px solid var(--border); cursor: pointer; }
  .li:last-child { border-bottom: none; }
  .li:hover { background: var(--surface-2); }
  .form { display: grid; gap: 10px; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); }
  .form .full { grid-column: 1 / -1; }
  .note { font-size: 13px; padding: 8px 10px; border-radius: var(--radius-sm); background: var(--surface-2); }
  .note.warning { background: var(--warning-soft, var(--surface-2)); color: var(--warning); }
  .big { font-size: 22px; font-weight: 650; line-height: 1.1; }
  .click { cursor: pointer; }
  .sheet { position: fixed; inset: 0; z-index: 50; background: rgba(0,0,0,.35); display: flex; align-items: flex-end; justify-content: center; }
  .sheet > .card { width: min(640px, 100%); max-height: 88vh; overflow: auto; border-radius: var(--radius-lg) var(--radius-lg) 0 0; }
  @media (min-width: 861px) { .sheet { align-items: center; } .sheet > .card { border-radius: var(--radius-lg); } }
  @media (max-width: 860px) { .page { padding: 12px 12px 90px; } }
`;
