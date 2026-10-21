/**
 * Small building blocks the SDK kit does not have yet (kept local to Chronos): icons used by the calendar,
 * <chronos-dialog> (modal / phone full-screen), <chronos-pop> (floating panel next to a rect, sheet on phones),
 * <chronos-menu> (⋯ menu), and the segmented / toggle templates.
 */
import { LitElement, css, html, nothing, svg, tokens, kitStyles } from '@hestia/webui-sdk';
import type { TemplateResult } from '@hestia/webui-sdk';

const PATHS: Record<string, string> = {
  event: 'M4 6h16v14H4zM4 10h16M8 3v4M16 3v4M8 14h3v3H8z',
  task: 'M9 11l3 3 8-8M20 12v7H4V5h11',
  repeat: 'M17 2l4 4-4 4M3 11V9a3 3 0 013-3h15M7 22l-4-4 4-4M21 13v2a3 3 0 01-3 3H3',
  window: 'M3 5h18v14H3zM3 9h18',
  zap: 'M13 2L4 14h7l-1 8 9-12h-7z',
  alert: 'M12 3l10 18H2zM12 10v5M12 18h.01',
  list: 'M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01',
  info: 'M12 21a9 9 0 110-18 9 9 0 010 18zM12 11v5M12 8h.01',
  branch: 'M6 3v12M18 9a3 3 0 100-6 3 3 0 000 6zM6 21a3 3 0 100-6 3 3 0 000 6zM18 9a9 9 0 01-9 9',
  skip: 'M5 4l10 8-10 8zM19 5v14',
  copy: 'M9 9h11v11H9zM5 15H4V4h11v1',
  terminal: 'M4 17l6-5-6-5M12 19h8',
  code: 'M8 6l-6 6 6 6M16 6l6 6-6 6',
  sidebar: 'M3 4h18v16H3zM9 4v16',
  settings: 'M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0M14 4v4M8 10v4M16 16v4',
  'chevron-down': 'M6 9l6 6 6-6',
};

/** Icon: calendar-specific paths, everything else from the kit's <hxk-icon>. */
export function ic(name: string, size = 16): TemplateResult {
  const d = PATHS[name];
  if (!d) return html`<hxk-icon name=${name} size=${size}></hxk-icon>`;
  return html`<svg class="ic" width=${size} height=${size} viewBox="0 0 24 24" aria-hidden="true" style="fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round;flex-shrink:0">${svg`<path d=${d}></path>`}</svg>`;
}

/** Weather of a day as a small chip «icon 9–18°» (tooltip: condition, rain hours, located events of the day). */
export function wxChip(day: { min_c: number | null; max_c: number | null; condition: string; icon: string; rain_hours?: string[] } | undefined,
                       extra: string[] = []): TemplateResult | typeof nothing {
  if (!day) return nothing;
  const rain = day.rain_hours?.length ? `, pioggia ${day.rain_hours[0]}${day.rain_hours.length > 1 ? '–' + day.rain_hours[day.rain_hours.length - 1] : ''}` : '';
  const title = [`${day.condition}${rain}`, ...extra].join('\n');
  const wet = ['rain', 'drizzle', 'storm', 'snow'].includes(day.icon);
  return html`<span class="wx" title=${title}><hxk-icon name=${day.icon || 'cloud'} size=${13} tone=${wet ? 'info' : 'warning'}></hxk-icon>${day.min_c ?? ''}–${day.max_c ?? ''}°</span>`;
}

/** Segmented control (one choice of a few). */
export function segmented<T extends string>(opts: { value: T; label: string; title?: string }[], value: T, pick: (v: T) => void): TemplateResult {
  return html`<div class="seg" role="radiogroup">${opts.map(o => html`<button type="button" role="radio" aria-checked=${o.value === value}
    title=${o.title ?? o.label} @click=${() => pick(o.value)}>${o.label}</button>`)}</div>`;
}

/** Switch with a label. */
export function toggle(label: string, checked: boolean, change: (v: boolean) => void): TemplateResult {
  return html`<label class="tgl"><input type="checkbox" role="switch" .checked=${checked} @change=${(e: any) => change(e.target.checked)}><span class="trk"></span><span>${label}</span></label>`;
}

/** Shared CSS for the templates above + buttons-as-text. Include in each calendar element's styles. */
export const calStyles = css`
  button { font: inherit; color: inherit; background: none; border: 0; padding: 0; cursor: pointer; }
  button:focus-visible { outline: none; box-shadow: 0 0 0 3px var(--focus-ring); border-radius: var(--radius-sm); }
  .seg { display: inline-flex; background: var(--surface-2); border-radius: var(--radius-md); padding: 2px; gap: 2px; flex-wrap: wrap; }
  .seg button { padding: 4px 10px; border-radius: var(--radius-sm); font-size: 13px; color: var(--text-2); }
  .seg button[aria-checked=true] { background: var(--surface); color: var(--text); box-shadow: var(--shadow-1); font-weight: 500; }
  .tgl { display: flex; align-items: center; gap: 8px; font-size: 13px; cursor: pointer; user-select: none; }
  .tgl input { position: absolute; opacity: 0; width: 1px; height: 1px; }
  .tgl .trk { width: 30px; height: 18px; border-radius: 9px; background: var(--border-strong); position: relative; flex-shrink: 0; transition: background var(--dur-fast, .12s); }
  .tgl .trk::after { content: ''; position: absolute; top: 2px; left: 2px; width: 14px; height: 14px; border-radius: 50%; background: var(--surface); transition: transform var(--dur-fast, .12s); }
  .tgl input:checked + .trk { background: var(--accent); } .tgl input:checked + .trk::after { transform: translateX(12px); }
  .tgl input:focus-visible + .trk { box-shadow: 0 0 0 3px var(--focus-ring); }
  input[type=checkbox].chk { width: 16px; height: 16px; accent-color: var(--accent); padding: 0; margin: 0; }
  code { font-family: var(--font-mono); font-size: 12px; background: var(--surface-2); padding: 1px 5px; border-radius: var(--radius-xs, 4px); }
  .lnk { color: var(--accent); font-weight: 500; font-size: 12.5px; } .lnk:hover { text-decoration: underline; }
`;

/** Modal dialog: `open`, `heading`, `size` (md|lg); slot `footer`; event `close` (Esc, backdrop, ×). */
export class ChronosDialog extends LitElement {
  static properties = { open: { type: Boolean, reflect: true }, heading: {}, size: { reflect: true } };
  declare open: boolean; declare heading: string; declare size: string;
  static styles = [tokens, kitStyles, css`
    :host { display: contents; }
    .bd { position: fixed; inset: 0; background: var(--overlay); z-index: 900; display: grid; place-items: center; padding: 16px; }
    .dlg { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-lg); box-shadow: var(--shadow-3);
      width: min(560px, 100%); max-height: calc(100dvh - 32px); display: flex; flex-direction: column; }
    :host([size=lg]) .dlg { width: min(720px, 100%); }
    header { display: flex; align-items: center; gap: 8px; padding: 14px 16px 10px 20px; }
    header h2 { flex: 1; font-size: 18px; }
    .x { background: none; border: 0; color: var(--text-3); cursor: pointer; border-radius: var(--radius-sm); padding: 4px; line-height: 0; }
    .x:hover { background: var(--surface-2); color: var(--text); }
    .body { padding: 4px 20px 16px; overflow: auto; flex: 1; min-height: 0; }
    footer { display: flex; gap: 8px; justify-content: flex-end; flex-wrap: wrap; padding: 12px 16px; border-top: 1px solid var(--border); }
    @media (max-width: 600px) { .bd { padding: 0; } .dlg { width: 100% !important; height: 100dvh; max-height: none; border-radius: 0; } }
  `];
  constructor() { super(); this.open = false; this.heading = ''; this.size = 'md'; }
  private esc = (e: KeyboardEvent) => { if (e.key === 'Escape' && this.open) { e.stopPropagation(); this.close(); } };
  connectedCallback() { super.connectedCallback(); document.addEventListener('keydown', this.esc, true); }
  disconnectedCallback() { super.disconnectedCallback(); document.removeEventListener('keydown', this.esc, true); }
  private close() { this.dispatchEvent(new CustomEvent('close')); }
  render() {
    if (!this.open) return nothing;
    return html`<div class="bd" @click=${(e: Event) => { if (e.target === e.currentTarget) this.close(); }}>
      <div class="dlg" role="dialog" aria-modal="true" aria-label=${this.heading}>
        <header><h2>${this.heading}</h2><button class="x" aria-label="Chiudi" @click=${this.close}><hxk-icon name="x" size="18"></hxk-icon></button></header>
        <div class="body"><slot></slot></div>
        <footer><slot name="footer"></slot></footer>
      </div></div>`;
  }
}

/** Floating panel next to `anchor` (a DOMRect), flips to stay on screen; bottom sheet on phones. Event `close`. */
export class ChronosPop extends LitElement {
  static properties = { open: { type: Boolean }, anchor: { attribute: false }, width: { type: Number }, placement: {} };
  declare open: boolean; declare anchor: DOMRect | null; declare width: number; declare placement: 'side' | 'below';
  static styles = [tokens, css`
    :host { display: contents; }
    .scrim { position: fixed; inset: 0; z-index: 800; }
    .p { position: fixed; z-index: 801; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-lg);
      box-shadow: var(--shadow-3); max-height: calc(100dvh - 24px); overflow: auto; }
    @media (max-width: 600px) {
      .scrim { background: var(--overlay); }
      .p { left: 0 !important; right: 0; top: auto !important; bottom: 0; width: auto !important; max-height: 80dvh;
        border-radius: var(--radius-lg) var(--radius-lg) 0 0; }
    }
  `];
  constructor() { super(); this.open = false; this.anchor = null; this.width = 340; this.placement = 'side'; }
  private esc = (e: KeyboardEvent) => { if (e.key === 'Escape' && this.open) { e.stopPropagation(); this.close(); } };
  connectedCallback() { super.connectedCallback(); document.addEventListener('keydown', this.esc, true); }
  disconnectedCallback() { super.disconnectedCallback(); document.removeEventListener('keydown', this.esc, true); }
  private close() { this.dispatchEvent(new CustomEvent('close')); }
  private pos(): string {
    const vw = window.innerWidth, vh = window.innerHeight, w = Math.min(this.width, vw - 16), r = this.anchor;
    if (!r) return `left:${(vw - w) / 2}px;top:80px;width:${w}px`;
    const clampX = (x: number) => Math.max(8, Math.min(x, vw - w - 8));
    if (this.placement === 'below') {
      const top = r.bottom + 4 + 260 > vh ? Math.max(8, r.top - 4 - Math.min(400, vh - 16)) : r.bottom + 4;
      return `left:${clampX(r.right - w)}px;top:${top}px;width:${w}px`;
    }
    const side = r.right + 8 + w <= vw - 8 ? r.right + 8 : r.left - w - 8 >= 8 ? r.left - w - 8 : null;
    if (side === null) return `left:${clampX(r.left)}px;top:${Math.min(r.bottom + 6, vh - 220)}px;width:${w}px`;
    return `left:${side}px;top:${Math.max(8, Math.min(r.top, vh - 360))}px;width:${w}px`;
  }
  render() {
    if (!this.open) return nothing;
    return html`<div class="scrim" @click=${this.close}></div><div class="p" style=${this.pos()} role="dialog"><slot></slot></div>`;
  }
}

export interface MenuItem { id: string; label: string; icon?: string; danger?: boolean; divider?: boolean; }

/** ⋯ / ▾ menu: the slotted trigger opens a list; event `select` (detail = item id). */
export class ChronosMenu extends LitElement {
  static properties = { items: { attribute: false }, open: { state: true }, rect: { state: true } };
  declare items: MenuItem[]; declare open: boolean; declare rect: DOMRect | null;
  static styles = [tokens, css`
    :host { display: inline-flex; }
    .l { display: flex; flex-direction: column; padding: 4px; }
    .it { display: flex; align-items: center; gap: 8px; padding: 7px 10px; border-radius: var(--radius-sm); font: inherit; font-size: 13.5px;
      color: var(--text); background: none; border: 0; cursor: pointer; text-align: left; }
    .it:hover, .it:focus-visible { background: var(--surface-2); outline: none; }
    .it.danger { color: var(--danger); }
    hr { border: 0; border-top: 1px solid var(--border); margin: 4px 0; }
  `];
  constructor() { super(); this.items = []; this.open = false; this.rect = null; }
  private toggle(e: Event) { e.stopPropagation(); this.rect = this.getBoundingClientRect(); this.open = !this.open; }
  private pick(id: string) { this.open = false; this.dispatchEvent(new CustomEvent('select', { detail: id, bubbles: true, composed: true })); }
  render() {
    return html`<span @click=${this.toggle}><slot></slot></span>
      <chronos-pop .open=${this.open} .anchor=${this.rect} .width=${230} placement="below" @close=${() => (this.open = false)}>
        <div class="l" role="menu">${this.items.map(i => i.divider ? html`<hr>` : html`<button class="it ${i.danger ? 'danger' : ''}" role="menuitem"
          @click=${() => this.pick(i.id)}>${i.icon ? ic(i.icon, 15) : nothing}<span>${i.label}</span></button>`)}</div>
      </chronos-pop>`;
  }
}
