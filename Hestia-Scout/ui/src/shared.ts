import { css, html } from '@hestia/webui-sdk';

export interface Listing {
  id: string; url: string; title: string; address: string; city: string;
  price: number | null; price_per_m2: number | null; surface_m2: number | null;
  rooms: number | string | null; bedrooms: number | null; bathrooms: number | null; floor: string | null;
  elevator: boolean; balcony: boolean; parking: boolean;
  image: string; status: string; status_label: string; flag: '' | 'favorite' | 'discarded';
  source: string; created_at: string | null; updated_at: string | null;
}
export interface ListingDetail extends Listing {
  summary: string; images: string[]; lat: number | null; lon: number | null; features: string[];
  characteristics: Record<string, string>; heating: string | null; year_built: number | null;
  property_state: string | null; condo_fees: number | string | null; agency: string;
}
export interface Stats {
  total: number; new: number; favorites: number; discarded: number; available: number;
  avg_price: number | null; avg_ppm2: number | null;
  by_status: { status: string; label: string; count: number }[];
  weeks: { week: string; label: string; count: number }[];
  price_by_city: { city: string; count: number; avg_price: number | null; avg_ppm2: number | null }[];
  cities: string[];
}

const nf = new Intl.NumberFormat('it-IT');
export const euro = (n: number | null | undefined) => n ? `€ ${nf.format(n)}` : '—';
export const compactEuro = (n: number | null | undefined) =>
  n ? `€ ${new Intl.NumberFormat('it-IT', { notation: 'compact', maximumFractionDigits: 1 }).format(n)}` : '—';
export const num = (n: number | null | undefined) => (n || n === 0) ? nf.format(n) : '—';

export const statusTone = (s: string) =>
  ({ available: 'success', in_negotiation: 'warning', investment_occupied: 'info', sold: 'danger' } as Record<string, string>)[s] ?? 'neutral';

export function ago(iso: string | null): string {
  if (!iso) return '';
  const d = new Date(iso); const days = Math.floor((Date.now() - d.getTime()) / 86_400_000);
  if (days <= 0) return 'oggi'; if (days === 1) return 'ieri'; if (days < 7) return `${days} giorni fa`;
  return d.toLocaleDateString('it-IT', { day: 'numeric', month: 'short' });
}

export function facts(l: Listing): string {
  return [l.surface_m2 ? `${num(l.surface_m2)} m²` : '', l.rooms ? `${l.rooms} ${Number(l.rooms) === 1 ? 'locale' : 'locali'}` : '', l.city].filter(Boolean).join(' · ');
}

/** Photo with a calm fallback (listing CDNs block hotlinks now and then). */
export const photo = (src: string, cls = 'ph') => src
  ? html`<img class=${cls} src=${src} alt="" loading="lazy" referrerpolicy="no-referrer"
          @error=${(e: Event) => (e.target as HTMLElement).replaceWith(Object.assign(document.createElement('div'), { className: cls + ' none' }))}>`
  : html`<div class="${cls} none"></div>`;

export const cardStyles = css`
  .lc { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-lg); overflow: hidden;
        display: flex; flex-direction: column; cursor: pointer; transition: border-color .15s, box-shadow .15s; }
  .lc:hover { border-color: var(--border-strong); box-shadow: var(--shadow-1); }
  .lc.discarded { opacity: .55; }
  .ph { width: 100%; aspect-ratio: 4 / 3; object-fit: cover; display: block; background: var(--surface-2); }
  .ph.none { background: var(--surface-2) center / 42px no-repeat
    url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23999' stroke-width='1.5'%3E%3Cpath d='M3 11l9-7 9 7v9a1 1 0 01-1 1h-5v-6H9v6H4a1 1 0 01-1-1z'/%3E%3C/svg%3E"); }
  .lb { padding: 10px 12px 12px; display: flex; flex-direction: column; gap: 4px; }
  .price { font-family: var(--font-serif); font-size: 19px; font-weight: 600; }
  .ppm { color: var(--text-3); font-size: 12px; font-weight: 400; margin-left: 6px; font-family: var(--font-sans); }
  .tt { font-weight: 500; }
  .ft { color: var(--text-2); font-size: 12.5px; }
  .foot { display: flex; align-items: center; gap: 6px; margin-top: 6px; }
  .flagbtn { border: 1px solid var(--border); background: var(--surface); color: var(--text-2); border-radius: 999px;
             width: 32px; height: 32px; display: inline-grid; place-items: center; cursor: pointer; padding: 0; }
  .flagbtn:hover { border-color: var(--accent); color: var(--accent); }
  .flagbtn.on.fav { background: var(--warning-soft); color: var(--warning); border-color: transparent; }
  .flagbtn.on.dis { background: var(--surface-2); color: var(--text); border-color: var(--border-strong); }
  .when { margin-left: auto; color: var(--text-3); font-size: 12px; }
`;
