import { LitElement, css, html, nothing, svg } from 'lit';
import { kitStyles, toneColor, tokens } from '../styles';

/** Small inline icon set (stroke icons, same style as the WebUI hx-icon). */
const ICONS: Record<string, string> = {
  check: 'M5 12l5 5L20 7',
  plus: 'M12 5v14M5 12h14',
  x: 'M6 6l12 12M18 6L6 18',
  refresh: 'M20 11a8 8 0 10-2.3 5.7M20 4v7h-7',
  star: 'M12 3l2.8 5.7 6.2.9-4.5 4.4 1 6.2L12 17.3 6.5 20.2l1-6.2L3 9.6l6.2-.9z',
  more: 'M5 12h.01M12 12h.01M19 12h.01',
  home: 'M3 11l9-7 9 7v9a1 1 0 01-1 1h-5v-6H9v6H4a1 1 0 01-1-1z',
  chart: 'M4 20V10M10 20V4M16 20v-7M22 20H2',
  clock: 'M12 7v5l3 2M12 21a9 9 0 110-18 9 9 0 010 18z',
  heart: 'M12 20s-7-4.4-7-10a4 4 0 017-2.6A4 4 0 0119 10c0 5.6-7 10-7 10z',
  trash: 'M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3',
  edit: 'M4 20h4L19 9l-4-4L4 16zM14 6l4 4',
  camera: 'M4 8h3l2-3h6l2 3h3v11H4zM12 17a3.5 3.5 0 100-7 3.5 3.5 0 000 7z',
  search: 'M11 18a7 7 0 110-14 7 7 0 010 14zM21 21l-5-5',
  calendar: 'M4 6h16v14H4zM4 10h16M8 3v4M16 3v4',
  undo: 'M9 14L4 9l5-5M4 9h10a6 6 0 010 12h-3',
  link: 'M10 14a4 4 0 005.7 0l3-3a4 4 0 00-5.7-5.7l-1 1M14 10a4 4 0 00-5.7 0l-3 3a4 4 0 005.7 5.7l1-1',
  play: 'M7 4l13 8-13 8z',
  pause: 'M7 4h4v16H7zM14 4h4v16h-4z',
  offline: 'M2 2l20 20M8.5 16.5a5 5 0 017 0M5 13a10 10 0 015.2-2.8M19 13a10 10 0 00-2.4-1.7M12 20h.01',
};

export class HxkIcon extends LitElement {
  static properties = { name: {}, size: { type: Number } };
  declare name: string;
  declare size: number;
  static styles = css`:host { display: inline-flex; line-height: 0; } svg { fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }`;
  constructor() { super(); this.size = 16; this.name = ''; }
  render() {
    const d = ICONS[this.name] ?? ICONS['more'];
    return html`<svg width=${this.size} height=${this.size} viewBox="0 0 24 24" aria-hidden="true">${svg`<path d=${d}></path>`}</svg>`;
  }
}

export class HxkButton extends LitElement {
  static properties = { variant: { reflect: true }, icon: {}, disabled: { type: Boolean, reflect: true },
                        loading: { type: Boolean }, size: { reflect: true } };
  declare variant: 'default' | 'primary' | 'ghost' | 'danger';
  declare icon: string;
  declare disabled: boolean;
  declare loading: boolean;
  declare size: 'sm' | 'md' | 'lg';
  static styles = [tokens, css`
    :host { display: inline-flex; }
    button { font: inherit; font-weight: 500; display: inline-flex; align-items: center; gap: 6px; cursor: pointer;
      border-radius: var(--radius-md); border: 1px solid var(--border-strong); background: var(--surface);
      color: var(--text); padding: 7px 12px; transition: background var(--dur-fast) var(--ease); white-space: nowrap; }
    button:hover { background: var(--surface-2); }
    :host([variant=primary]) button { background: var(--accent); color: var(--accent-contrast); border-color: var(--accent); }
    :host([variant=primary]) button:hover { background: var(--accent-hover); }
    :host([variant=ghost]) button { background: transparent; border-color: transparent; color: var(--text-2); }
    :host([variant=ghost]) button:hover { background: var(--surface-2); }
    :host([variant=danger]) button { color: var(--danger); }
    :host([size=sm]) button { padding: 4px 8px; font-size: 13px; }
    :host([size=lg]) button { padding: 11px 18px; font-size: 15px; }
    :host([disabled]) button { opacity: .5; pointer-events: none; }
    button:focus-visible { outline: none; box-shadow: 0 0 0 3px var(--focus-ring); }
    .spin { animation: spin 1s linear infinite; } @keyframes spin { to { transform: rotate(360deg); } }
  `];
  constructor() { super(); this.variant = 'default'; this.icon = ''; this.disabled = false; this.loading = false; this.size = 'md'; }
  render() {
    return html`<button ?disabled=${this.disabled || this.loading} part="button">
      ${this.loading ? html`<hxk-icon class="spin" name="refresh"></hxk-icon>` : this.icon ? html`<hxk-icon name=${this.icon}></hxk-icon>` : nothing}
      <slot></slot></button>`;
  }
}

export class HxkBadge extends LitElement {
  static properties = { tone: {} };
  declare tone: string;
  constructor() { super(); this.tone = 'neutral'; }
  static styles = css`:host { display: inline-flex; } span { font-size: 11.5px; font-weight: 600; padding: 2px 8px; border-radius: var(--radius-full); white-space: nowrap; }`;
  render() {
    const [fg, bg] = toneColor(this.tone);
    return html`<span style="color:${fg};background:${bg}"><slot></slot></span>`;
  }
}

/** Card with optional title/subtitle, header actions slot and click target. */
export class HxkCard extends LitElement {
  static properties = { heading: {}, subtitle: {}, clickable: { type: Boolean, reflect: true }, flush: { type: Boolean, reflect: true } };
  declare heading: string;
  declare subtitle: string;
  declare clickable: boolean;
  declare flush: boolean;
  constructor() { super(); this.heading = ''; this.subtitle = ''; this.clickable = false; this.flush = false; }
  static styles = [tokens, css`
    :host { display: block; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-lg);
      overflow: hidden; height: 100%; }
    :host([clickable]) { cursor: pointer; transition: border-color var(--dur-fast) var(--ease); }
    :host([clickable]:hover) { border-color: var(--border-strong); }
    header { display: flex; align-items: center; gap: 8px; padding: 12px 16px 0; }
    .t { font-weight: 600; font-size: 14px; } .s { color: var(--text-3); font-size: 12px; }
    .body { padding: 12px 16px 14px; } :host([flush]) .body { padding: 0; }
  `];
  render() {
    const head = this.heading || this.subtitle;
    return html`${head ? html`<header><div style="flex:1;min-width:0"><div class="t">${this.heading}</div>
        ${this.subtitle ? html`<div class="s">${this.subtitle}</div>` : nothing}</div><slot name="actions"></slot></header>` : nothing}
      <div class="body"><slot></slot></div>`;
  }
}

/** KPI tiles: items [{label, value, unit?, delta?, tone?, hint?}]. */
export class HxkStat extends LitElement {
  static properties = { items: { attribute: false } };
  declare items: Array<{ label: string; value: string | number; unit?: string; delta?: string; tone?: string; hint?: string }>;
  constructor() { super(); this.items = []; }
  static styles = [tokens, css`
    :host { display: grid; gap: 10px; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); }
    .tile { background: var(--surface-2); border-radius: var(--radius-md); padding: 10px 12px; }
    .l { font-size: 12px; color: var(--text-3); } .v { font-size: 22px; font-weight: 600; font-family: var(--font-serif); }
    .u { font-size: 13px; color: var(--text-3); margin-left: 3px; } .d { font-size: 12px; font-weight: 600; }
  `];
  render() {
    return this.items.map(i => html`<div class="tile" title=${i.hint ?? ''}><div class="l">${i.label}</div>
      <div><span class="v">${i.value}</span>${i.unit ? html`<span class="u">${i.unit}</span>` : nothing}</div>
      ${i.delta ? html`<div class="d" style="color:${toneColor(i.tone)[0]}">${i.delta}</div>` : nothing}</div>`);
  }
}

/** Loading / empty / error / offline state with optional retry (event 'retry'). */
export class HxkState extends LitElement {
  static properties = { kind: {}, text: {} };
  declare kind: 'loading' | 'empty' | 'error' | 'offline';
  declare text: string;
  constructor() { super(); this.kind = 'loading'; this.text = ''; }
  static styles = [tokens, css`
    :host { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; padding: 24px 12px;
      color: var(--text-3); text-align: center; font-size: 13px; min-height: 80px; }
    .spin { animation: spin 1s linear infinite; } @keyframes spin { to { transform: rotate(360deg); } }
  `];
  render() {
    const def = { loading: 'Carico…', empty: 'Niente da mostrare', error: 'Qualcosa è andato storto', offline: 'Modulo non raggiungibile' }[this.kind];
    const icon = { loading: 'refresh', empty: 'search', error: 'x', offline: 'offline' }[this.kind];
    return html`<hxk-icon name=${icon} size="20" class=${this.kind === 'loading' ? 'spin' : ''}></hxk-icon>
      <div>${this.text || def}</div>
      ${this.kind === 'error' || this.kind === 'offline'
        ? html`<hxk-button size="sm" variant="ghost" icon="refresh" @click=${() => this.dispatchEvent(new CustomEvent('retry', { bubbles: true, composed: true }))}>Riprova</hxk-button>`
        : nothing}`;
  }
}

/** List of items [{id, title, subtitle?, meta?, badge?:{text,tone}, image?, icon?}] → event 'item-click' (detail = item). */
export class HxkList extends LitElement {
  static properties = { items: { attribute: false }, dense: { type: Boolean, reflect: true } };
  declare items: Array<{ id: string; title: string; subtitle?: string; meta?: string; badge?: { text: string; tone?: string }; image?: string; icon?: string }>;
  declare dense: boolean;
  constructor() { super(); this.items = []; this.dense = false; }
  static styles = [tokens, kitStyles, css`
    :host { display: flex; flex-direction: column; }
    .it { display: flex; align-items: center; gap: 10px; padding: 8px 6px; border-radius: var(--radius-md); cursor: pointer; }
    .it:hover { background: var(--surface-2); }
    :host([dense]) .it { padding: 5px 6px; }
    img { width: 40px; height: 40px; border-radius: var(--radius-sm); object-fit: cover; background: var(--surface-2); }
    .ic { width: 32px; height: 32px; border-radius: var(--radius-sm); display: grid; place-items: center; background: var(--surface-2); color: var(--text-2); }
    .t { font-weight: 500; } .meta { color: var(--text-3); font-size: 12px; white-space: nowrap; }
  `];
  render() {
    return this.items.map(i => html`<div class="it" @click=${() => this.dispatchEvent(new CustomEvent('item-click', { detail: i, bubbles: true, composed: true }))}>
      ${i.image ? html`<img src=${i.image} alt="" loading="lazy">` : i.icon ? html`<div class="ic"><hxk-icon name=${i.icon}></hxk-icon></div>` : nothing}
      <div class="grow"><div class="t truncate">${i.title}</div>${i.subtitle ? html`<div class="muted small truncate">${i.subtitle}</div>` : nothing}</div>
      ${i.badge ? html`<hxk-badge tone=${i.badge.tone ?? 'neutral'}>${i.badge.text}</hxk-badge>` : nothing}
      ${i.meta ? html`<span class="meta">${i.meta}</span>` : nothing}</div>`);
  }
}
