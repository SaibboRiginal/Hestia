/** Wardrobe UI helpers: API calls, meta cache, labels, photo URLs and shared styles. */
import { HestiaElement, css, html, nothing } from '@hestia/webui-sdk';
import type { ApiResult, HestiaHost, HttpMethod } from '@hestia/webui-sdk';

export const API = '/api/wardrobe';

export interface Vocab { key: string; label: string; hidden?: boolean; order?: number; kind?: string; slot?: string; parent?: string; hex?: string; warmth?: number; formality?: number }
export interface Meta {
  kinds: Record<string, string>; seasons: Record<string, string>; statuses: Record<string, string>;
  conditions: Record<string, string>; slots: Record<string, string>; collection_types: Record<string, string>;
  vocabularies: Record<string, Vocab[]>; today: string; season: string; currency: string; goal: any;
}

let _meta: Promise<Meta | null> | null = null;
let _metaAt = 0;
/** Meta (labels + vocabularies) shared by every element, refreshed every 5 minutes or on demand. */
export function meta(host: HestiaHost, force = false): Promise<Meta | null> {
  if (!_meta || force || Date.now() - _metaAt > 300_000) {
    _metaAt = Date.now();
    _meta = host.api<Meta>('GET', `${API}/meta`).then(r => (r.ok ? r.data : null));
  }
  return _meta;
}
export function resetMeta() { _meta = null; }

export async function call<T = any>(host: HestiaHost, method: HttpMethod, path: string, body?: unknown, query?: Record<string, any>): Promise<ApiResult<T>> {
  const r = await host.api<T>(method, `${API}${path}`, { body, query });
  if (!r.ok) host.toast(r.status === 0 ? 'Sei offline: riprova quando torni in linea' : (r.error || (r.data as any)?.detail || `Errore ${r.status}`), 'danger');
  return r;
}

export const photo = (host: HestiaHost, id: string | null | undefined, size: 'thumb' | 'medium' | 'original' = 'thumb') =>
  id ? host.image(`${API}/files/${id}?size=${size}`) : '';

export const vocabOptions = (m: Meta | null, name: string, withHidden = false) =>
  (m?.vocabularies?.[name] || []).filter(v => withHidden || !v.hidden);
export const label = (m: Meta | null, name: string, key: string) =>
  (m?.vocabularies?.[name] || []).find(v => v.key === key)?.label || key;

export const SEASON_ICON: Record<string, string> = { spring: '🌱', summer: '☀️', autumn: '🍂', winter: '❄️' };
export const STATUS_TONE: Record<string, string> = { active: 'success', laundry: 'info', lent: 'warning', stored: 'neutral', to_repair: 'warning', to_donate: 'neutral', wishlist: 'accent' };

export function localDay(d = new Date()): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}
export function dayLabel(iso?: string | null): string {
  if (!iso) return '';
  const t = localDay(), y = localDay(new Date(Date.now() - 86400000));
  if (iso.slice(0, 10) === t) return 'Oggi';
  if (iso.slice(0, 10) === y) return 'Ieri';
  return new Date(iso.slice(0, 10) + 'T12:00:00').toLocaleDateString('it-IT', { weekday: 'short', day: 'numeric', month: 'short' });
}
export function relDays(iso?: string | null): string {
  if (!iso) return 'mai segnato';
  const days = Math.round((Date.parse(localDay() + 'T12:00:00') - Date.parse(iso.slice(0, 10) + 'T12:00:00')) / 86400000);
  return days <= 0 ? 'oggi' : days === 1 ? 'ieri' : days < 14 ? `${days} giorni fa` : days < 60 ? `${Math.round(days / 7)} settimane fa` : `${Math.round(days / 30)} mesi fa`;
}
export const money = (v: number | null | undefined, cur = 'EUR') =>
  v === null || v === undefined ? '–' : new Intl.NumberFormat('it-IT', { style: 'currency', currency: cur || 'EUR', maximumFractionDigits: v % 1 ? 2 : 0 }).format(v);

export const norm = (s: string) => (s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');

/** Colour dots of a piece (primary first). */
export function dots(colors: any[] | undefined, size = 12) {
  if (!colors?.length) return nothing;
  return html`<span class="dots">${colors.slice(0, 4).map(c => html`<span class="dot" title=${c.name || c.key}
    style="width:${size}px;height:${size}px;background:${c.hex || 'var(--surface-3)'}"></span>`)}</span>`;
}

/** Page/widget base: loads on connect, on ctx change and on host refresh. */
export abstract class WardrobeElement extends HestiaElement {
  protected m: Meta | null = null;
  connectedCallback() {
    super.connectedCallback();
    this.onHost('refresh', () => this.reload());
    this.onHost('visible', () => this.reload());
    this.reload();
  }
  willUpdate(ch: Map<string, unknown>) {
    if (ch.has('ctx') && ch.get('ctx') !== undefined) this.reload();
  }
  protected async reload(force = false) {
    if (!this.host) return;
    this.m = await meta(this.host, force);
    await this.load();
    this.requestUpdate();
  }
  protected async load(): Promise<void> { /* element specific */ }
}

export const wardrobeStyles = css`
  h1 { font-size: 22px; font-weight: 650; margin: 0; letter-spacing: -.01em; }
  h2 { font-size: 15px; font-weight: 600; margin: 0; }
  h3 { font-size: 12px; font-weight: 600; margin: 0; color: var(--text-2); text-transform: uppercase; letter-spacing: .04em; }
  .head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .head .sub { color: var(--text-3); font-size: 13px; }
  .tabs, .chips { display: flex; gap: 6px; flex-wrap: wrap; }
  .chip { border: 1px solid var(--border-strong); background: var(--surface); color: var(--text); border-radius: var(--radius-full);
    padding: 5px 12px; font: inherit; font-size: 13px; cursor: pointer; min-height: 32px; display: inline-flex; align-items: center; gap: 6px; }
  .chip:hover { background: var(--surface-2); }
  .chip[aria-pressed=true] { background: var(--accent); border-color: var(--accent); color: var(--accent-contrast); }
  .chip.soft[aria-pressed=true] { background: var(--accent-soft); color: var(--accent); border-color: transparent; font-weight: 600; }
  input.in, select.in, textarea.in { font: inherit; color: var(--text); background: var(--surface-2); border: 1px solid var(--border-strong);
    border-radius: var(--radius-sm); padding: 7px 10px; outline: none; min-width: 0; }
  input.in:focus, select.in:focus, textarea.in:focus { border-color: var(--accent); box-shadow: 0 0 0 3px var(--focus-ring); }
  input.num { width: 84px; }
  .between { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
  .link { color: var(--accent); cursor: pointer; background: none; border: none; font: inherit; padding: 0; }
  .empty { color: var(--text-3); font-size: 13px; padding: 8px 0; }
  .pill { display: inline-flex; align-items: center; gap: 4px; font-size: 12px; color: var(--text-2); background: var(--surface-2);
    border-radius: var(--radius-full); padding: 2px 8px; }
  .dots { display: inline-flex; gap: 3px; vertical-align: middle; }
  .dot { border-radius: 50%; border: 1px solid var(--border-strong); display: inline-block; }
  .tiles { display: grid; gap: 12px; grid-template-columns: repeat(auto-fill, minmax(var(--tile, 160px), 1fr)); }
  .tile { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-lg); overflow: hidden; cursor: pointer;
    display: flex; flex-direction: column; position: relative; transition: border-color var(--dur-fast) var(--ease); }
  .tile:hover { border-color: var(--border-strong); }
  .tile[data-sel=true] { border-color: var(--accent); box-shadow: 0 0 0 2px var(--accent-soft); }
  .tile .ph { aspect-ratio: 1; background: var(--surface-2); display: grid; place-items: center; color: var(--text-3); overflow: hidden; }
  .tile .ph img { width: 100%; height: 100%; object-fit: cover; }
  .tile .tx { padding: 8px 10px; display: flex; flex-direction: column; gap: 2px; min-width: 0; }
  .tile .nm { font-weight: 550; font-size: 13.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .tile .fav { position: absolute; top: 6px; right: 6px; color: var(--warning); text-shadow: 0 1px 2px rgba(0,0,0,.4); }
  .tile .badge { position: absolute; top: 6px; left: 6px; }
  .tile .check { position: absolute; top: 6px; right: 6px; width: 22px; height: 22px; border-radius: 50%; background: var(--accent);
    color: var(--accent-contrast); display: grid; place-items: center; }
  .thumb { width: 44px; height: 44px; border-radius: var(--radius-sm); background: var(--surface-2); object-fit: cover; flex: none;
    display: grid; place-items: center; color: var(--text-3); overflow: hidden; }
  .thumb img { width: 100%; height: 100%; object-fit: cover; }
  .list { display: flex; flex-direction: column; }
  .li { display: flex; align-items: center; gap: 10px; padding: 8px 4px; border-bottom: 1px solid var(--border); cursor: pointer; }
  .li:last-child { border-bottom: none; }
  .li:hover { background: var(--surface-2); }
  .form { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 10px; }
  .bar { position: sticky; bottom: 0; z-index: 2; background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius-lg);
    padding: 8px 12px; box-shadow: var(--shadow-2); display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  .big { font-size: 22px; font-weight: 650; line-height: 1.15; }
  .reasons { display: flex; gap: 4px; flex-wrap: wrap; }
  @media (max-width: 860px) { .page { padding: 12px 12px 90px; } .tiles { --tile: 130px; gap: 8px; } }
`;

/** One photo or the category initial when there is no photo. */
export function img(host: HestiaHost, id: string | null | undefined, alt: string, size: 'thumb' | 'medium' = 'thumb') {
  return id ? html`<img loading="lazy" src=${photo(host, id, size)} alt=${alt}>` : html`<hxk-icon name="shirt" size="28"></hxk-icon>`;
}
