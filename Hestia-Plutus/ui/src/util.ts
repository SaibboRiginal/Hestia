/** Plutus UI helpers: API calls, money and dates, category chips, shared styles of pages and widgets. */
import { css, html, nothing } from '@hestia/webui-sdk';
import type { ApiResult, HestiaHost, HttpMethod } from '@hestia/webui-sdk';

export const API = '/api/finance';

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
/** Categories, accounts, currency: cached for 5 minutes per page load. */
export async function meta(host: HestiaHost, fresh = false): Promise<any> {
  if (!fresh && metaCache && Date.now() - metaCache.at < 300000) return metaCache.data;
  const r = await host.api('GET', `${API}/meta`);
  if (r.ok) metaCache = { at: Date.now(), data: r.data };
  return metaCache?.data ?? null;
}
export const dropMeta = () => { metaCache = null; };

export function money(x: number | null | undefined, currency = 'EUR', sign = false): string {
  if (x === null || x === undefined) return '–';
  const s = Number(x).toLocaleString('it-IT', { style: 'currency', currency });
  return sign && x > 0 ? '+' + s : s;
}
export function localDay(d: Date = new Date()): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}
export const today = () => localDay();
export function addDays(iso: string, n: number): string {
  const d = new Date(iso + 'T12:00:00');
  d.setDate(d.getDate() + n);
  return localDay(d);
}
/** First day of the month `n` months away from `iso` (keeps the day: the budget month may start on the 27th). */
export function addMonths(iso: string, n: number): string {
  const d = new Date(iso + 'T12:00:00');
  const day = d.getDate();
  d.setDate(1); d.setMonth(d.getMonth() + n); d.setDate(Math.min(day, 28));
  return localDay(d);
}
export function dayLabel(iso: string | null | undefined): string {
  if (!iso) return '';
  if (iso === today()) return 'Oggi';
  if (iso === addDays(today(), -1)) return 'Ieri';
  return new Date(iso + 'T12:00:00').toLocaleDateString('it-IT', { weekday: 'short', day: 'numeric', month: 'short' });
}
export const SOURCE: Record<string, string> = { manual: 'a mano', quick: 'veloce', chat: 'chat', email: 'email', statement: 'estratto' };
export const PERIOD: Record<string, string> = { weekly: 'ogni settimana', monthly: 'ogni mese', yearly: "ogni anno" };

export const catDot = (t: any) => html`<span class="dot" style="background:var(--cal-${colorIndex(t.category_color || t.color)})"></span>`;
const COLORS = ['green', 'blue', 'teal', 'orange', 'purple', 'red', 'pink', 'amber', 'indigo', 'cyan', 'rose', 'slate', 'gray'];
export const colorIndex = (c: string | undefined) => (Math.max(0, COLORS.indexOf(c || 'gray')) % 8) + 1;

/** One transaction row (list, widget, detail «simili»). */
export function txRow(host: HestiaHost, t: any, cur: string) {
  const sub = [t.category_label, t.account, SOURCE[t.source] || t.source].filter(Boolean).join(' · ');
  return html`<div class="li" @click=${() => host.navigate('movimenti/' + t.id)}>
    ${catDot(t)}
    <div class="grow"><div class="truncate"><b>${t.merchant || t.description || 'Movimento'}</b></div>
      <div class="small muted truncate">${dayLabel(t.date)} · ${sub}</div></div>
    ${t.status === 'to_review' ? html`<span class="pill warn">da rivedere</span>` : nothing}
    ${!t.counted ? html`<span class="pill" title="Collegato a un altro movimento o trasferimento: non conta nei totali">non conta</span>` : nothing}
    <span class="tnum amt ${t.amount > 0 ? 'in' : ''}">${money(t.amount, t.currency || cur, true)}</span></div>`;
}

/** Shared styles of Plutus pages (on top of the kit). */
export const plutusStyles = css`
  h1 { font-size: 22px; font-weight: 650; margin: 0; letter-spacing: -.01em; }
  h2 { font-size: 15px; font-weight: 600; margin: 0; }
  h3 { font-size: 12px; font-weight: 600; margin: 0; color: var(--text-2); text-transform: uppercase; letter-spacing: .05em; }
  .head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
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
  input.money { width: 120px; text-align: right; font-variant-numeric: tabular-nums; }
  .tnum { font-variant-numeric: tabular-nums; }
  .amt { font-weight: 600; white-space: nowrap; } .amt.in { color: var(--success); }
  .pill { display: inline-flex; align-items: center; gap: 4px; font-size: 12px; color: var(--text-2); background: var(--surface-2);
    border-radius: var(--radius-full); padding: 2px 8px; white-space: nowrap; }
  .pill.warn { color: var(--warning); } .pill.bad { color: var(--danger); } .pill.good { color: var(--success); }
  .dot { width: 10px; height: 10px; border-radius: 50%; flex: none; display: inline-block; }
  .between { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
  .link { color: var(--accent); cursor: pointer; background: none; border: none; font: inherit; padding: 0; }
  .empty { color: var(--text-3); font-size: 13px; padding: 8px 0; }
  .list { display: flex; flex-direction: column; }
  .li { display: flex; align-items: center; gap: 10px; padding: 10px 4px; border-bottom: 1px solid var(--border); cursor: pointer; }
  .li:last-child { border-bottom: none; }
  .li:hover { background: var(--surface-2); }
  .form { display: grid; gap: 10px; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); }
  .form .full { grid-column: 1 / -1; }
  .form label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--text-2); }
  .note { font-size: 13px; padding: 8px 10px; border-radius: var(--radius-sm); background: var(--surface-2); }
  .note.warning { color: var(--warning); }
  .big { font-size: 24px; font-weight: 650; line-height: 1.1; font-variant-numeric: tabular-nums; }
  .bar { height: 8px; border-radius: 4px; background: var(--surface-3); overflow: hidden; }
  .bar > span { display: block; height: 100%; border-radius: 4px; background: var(--success); }
  .bar > span.warn { background: var(--warning); } .bar > span.bad { background: var(--danger); }
  .click { cursor: pointer; }
  .sheet { position: fixed; inset: 0; z-index: 50; background: rgba(0,0,0,.35); display: flex; align-items: flex-end; justify-content: center; }
  .sheet > .card { width: min(640px, 100%); max-height: 88vh; overflow: auto; border-radius: var(--radius-lg) var(--radius-lg) 0 0; }
  @media (min-width: 861px) { .sheet { align-items: center; } .sheet > .card { border-radius: var(--radius-lg); } }
  @media (max-width: 860px) { .page { padding: 12px 12px 90px; } }
`;

/** Budget bar: green under the alert threshold, amber over it, red over 100 %. */
export function budgetBar(pct: number | null | undefined) {
  if (pct === null || pct === undefined) return nothing;
  const cls = pct >= 100 ? 'bad' : pct >= 80 ? 'warn' : '';
  return html`<div class="bar"><span class=${cls} style="width:${Math.min(100, pct)}%"></span></div>`;
}
