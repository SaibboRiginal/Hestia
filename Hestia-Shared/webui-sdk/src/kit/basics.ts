import { LitElement, css, html, nothing, svg } from 'lit';
import { kitStyles, toneColor, tokens } from '../styles';

/** Small inline icon set (stroke icons, same style as the WebUI hx-icon). */
const ICONS: Record<string, string> = {
  // Same names and paths as the WebUI hx-icon set (checked by tools/governance/check_icons.py).
  chat: 'M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z',
  bell: 'M6 16V11a6 6 0 1 1 12 0v5l1.5 2h-15L6 16zM10 20a2 2 0 0 0 4 0',
  'bell-off': 'M6 16V11a6 6 0 0 1 .6-2.6M9 5.6A6 6 0 0 1 18 11v5l1.5 2H6M10 20a2 2 0 0 0 4 0M3 3l18 18',
  calendar: 'M8 3v4M16 3v4M3.5 9.5h17M5 5h14a1.5 1.5 0 0 1 1.5 1.5v12A1.5 1.5 0 0 1 19 20H5a1.5 1.5 0 0 1-1.5-1.5v-12A1.5 1.5 0 0 1 5 5z',
  terminal: 'M4 17l5-5-5-5M12 19h8',
  file: 'M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5',
  settings: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z',
  plus: 'M12 5v14M5 12h14',
  minus: 'M5 12h14',
  x: 'M18 6 6 18M6 6l12 12',
  check: 'M20 6 9 17l-5-5',
  'chevron-left': 'M15 18l-6-6 6-6',
  'chevron-right': 'M9 18l6-6-6-6',
  'chevron-down': 'M6 9l6 6 6-6',
  'chevron-up': 'M18 15l-6-6-6 6',
  search: 'M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM21 21l-4.3-4.3',
  trash: 'M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6',
  edit: 'M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z',
  play: 'M6 4l14 8-14 8z',
  pause: 'M7 4h3v16H7zM14 4h3v16h-3z',
  skip: 'M5 4l10 8-10 8zM19 5v14',
  sun: 'M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10zM12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4',
  moon: 'M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z',
  menu: 'M3 6h18M3 12h18M3 18h18',
  sidebar: 'M4 4h16a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1zM9 4v16',
  logout: 'M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9',
  send: 'M12 19V5M5 12l7-7 7 7',
  stop: 'M7 7h10v10H7z',
  paperclip: 'M21.4 11.1l-9.2 9.2a6 6 0 0 1-8.5-8.5l9.2-9.2a4 4 0 0 1 5.7 5.7l-9.2 9.2a2 2 0 0 1-2.8-2.8l8.5-8.5',
  'thumb-up': 'M7 10v11H4V10zM7 10l4-8a2 2 0 0 1 3 2l-1 5h6a2 2 0 0 1 2 2.3l-1.4 7A2 2 0 0 1 17.6 20H7',
  'thumb-down': 'M17 14V3h3v11zM17 14l-4 8a2 2 0 0 1-3-2l1-5H5a2 2 0 0 1-2-2.3l1.4-7A2 2 0 0 1 6.4 4H17',
  refresh: 'M21 12a9 9 0 1 1-3-6.7L21 8M21 3v5h-5',
  alert: 'M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z',
  info: 'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 16v-4M12 8h.01',
  clock: 'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 6v6l4 2',
  repeat: 'M17 1l4 4-4 4M3 11V9a4 4 0 0 1 4-4h14M7 23l-4-4 4-4M21 13v2a4 4 0 0 1-4 4H3',
  list: 'M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01',
  grid: 'M3 3h7v7H3zM14 3h7v7h-7zM14 14h7v7h-7zM3 14h7v7H3z',
  columns: 'M4 4h16v16H4zM9.3 4v16M14.7 4v16',
  square: 'M4 4h16v16H4z',
  filter: 'M22 3H2l8 9.5V19l4 2v-8.5z',
  more: 'M12 13a1 1 0 1 0 0-2 1 1 0 0 0 0 2zM19 13a1 1 0 1 0 0-2 1 1 0 0 0 0 2zM5 13a1 1 0 1 0 0-2 1 1 0 0 0 0 2z',
  copy: 'M9 9h11v11H9zM5 15H4V4h11v1',
  zap: 'M13 2 3 14h9l-1 8 10-12h-9z',
  window: 'M3 5h18v14H3zM3 9h18',
  task: 'M9 11l3 3 8-8M20 12v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11',
  event: 'M12 22s7-6.3 7-12a7 7 0 1 0-14 0c0 5.7 7 12 7 12zM12 12.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z',
  brain: 'M9 3a3 3 0 0 0-3 3 3 3 0 0 0-2 5 3 3 0 0 0 2 5 3 3 0 0 0 6 1V5a2 2 0 0 0-3-2zM15 3a3 3 0 0 1 3 3 3 3 0 0 1 2 5 3 3 0 0 1-2 5 3 3 0 0 1-6 1',
  sparkle: 'M12 3l1.9 5.6L19.5 10.5l-5.6 1.9L12 18l-1.9-5.6L4.5 10.5l5.6-1.9z',
  user: 'M20 21a8 8 0 1 0-16 0M12 13a5 5 0 1 0 0-10 5 5 0 0 0 0 10z',
  palette: 'M12 22a10 10 0 1 1 10-10c0 2.8-2.2 3-4 3h-2a2 2 0 0 0-1 3.7A2 2 0 0 1 12 22zM7.5 11a1 1 0 1 0 0-2 1 1 0 0 0 0 2zM12 7a1 1 0 1 0 0-2 1 1 0 0 0 0 2zM16.5 11a1 1 0 1 0 0-2 1 1 0 0 0 0 2z',
  memory: 'M4 4h16v12H4zM8 20h8M12 16v4',
  bookmark: 'M6 3h12v18l-6-4-6 4z',
  undo: 'M3 7v6h6M3 13a9 9 0 1 0 3-7.7L3 8',
  branch: 'M6 3v12M18 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM18 9a9 9 0 0 1-9 9',
  commit: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM3 12h6M15 12h6',
  folder: 'M3 6.5A1.5 1.5 0 0 1 4.5 5H9l2 2.5h8.5A1.5 1.5 0 0 1 21 9v9.5a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 18.5z',
  mail: 'M3 6h18v12H3zM3 7l9 6 9-6',
  wallet: 'M3 7a2 2 0 0 1 2-2h13v4M3 7v11a2 2 0 0 0 2 2h15V9H5a2 2 0 0 1-2-2zM16 14.5h.01',
  upload: 'M12 16V4M7 9l5-5 5 5M4 16v4h16v-4',
  download: 'M12 4v12M7 11l5 5 5-5M4 16v4h16v-4',
  target: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM12 12h.01',
  tag: 'M20.6 13.4 13.4 20.6a2 2 0 0 1-2.8 0L3 13V3h10l7.6 7.6a2 2 0 0 1 0 2.8zM7.5 7.5h.01',
  flask: 'M9 3h6M10 3v6.5L4.6 18.4A1.7 1.7 0 0 0 6 21h12a1.7 1.7 0 0 0 1.4-2.6L14 9.5V3M7.5 15h9',
  code: 'M16 18l6-6-6-6M8 6l-6 6 6 6',
  'arrow-left': 'M19 12H5M12 19l-7-7 7-7',
  external: 'M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14 21 3',
  diff: 'M12 3v8M8 7h8M8 17h8M5 21h14a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2z',
  home: 'M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z',
  chart: 'M4 20V10M10 20V4M16 20v-7M22 20H2',
  pulse: 'M2 12h4l3-8 4 16 3-8h6',
  host: 'M3 4h18v6H3zM3 14h18v6H3zM7 7h.01M7 17h.01',
  shirt: 'M8.5 3.5L3.5 6.5l2 4 2-1V20.5h9V9.5l2 1 2-4-5-3a3.5 3.5 0 0 1-7 0z',
  pin: 'M12 17v5M9 4h6M10 4v6l-3 3v2h10v-2l-3-3V4',
  star: 'M12 3l2.8 5.7 6.2.9-4.5 4.4 1 6.2L12 17.3 6.5 20.2l1-6.2L3 9.6l6.2-.9z',
  heart: 'M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z',
  camera: 'M4 8h3l2-3h6l2 3h3v11H4zM12 17a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7z',
  puzzle: 'M10 4a2 2 0 1 1 4 0v2h4v4h-2a2 2 0 1 0 0 4h2v4h-4v-2a2 2 0 1 0-4 0v2H6v-4H4a2 2 0 1 1 0-4h2V6h4z',
  offline: 'M2 2l20 20M8.5 16.5a5 5 0 0 1 7 0M5 13a10 10 0 0 1 5.2-2.8M19 13a10 10 0 0 0-2.4-1.7M12 20h.01',
  command: 'M9 6a3 3 0 1 0-3 3h12a3 3 0 1 0-3-3v12a3 3 0 1 0 3-3H6a3 3 0 1 0 3 3z',
  'eye-off': 'M3 3l18 18M10.6 6.1A10 10 0 0112 6c5 0 9 6 9 6a17 17 0 01-2.7 3.3M6.4 7.4C4.2 8.9 3 12 3 12s4 6 9 6c1.5 0 2.9-.4 4.1-1M9.9 9.9a3 3 0 004.2 4.2',
  link: 'M10 14a4 4 0 005.7 0l3-3a4 4 0 00-5.7-5.7l-1 1M14 10a4 4 0 00-5.7 0l-3 3a4 4 0 005.7 5.7l1-1',
  trophy: 'M7 4h10v5a5 5 0 0 1-10 0zM7 6H4.5a2.5 2.5 0 0 0 0 5H7M17 6h2.5a2.5 2.5 0 0 1 0 5H17M12 14v4M8 21h8M9 18h6',
  flame: 'M12 22a7 7 0 0 0 7-7c0-4-3-6.5-4.5-10-1 2.5-2.2 3.6-3.5 4C10.5 7 10 5 10 2.5 7 4.5 5 8 5 11.5V15a7 7 0 0 0 7 7z',
  timer: 'M10 2h4M12 14l3-3M12 22a8 8 0 1 0 0-16 8 8 0 0 0 0 16z',
  hourglass: 'M6 2h12M6 22h12M7 2v4l5 6-5 6v4M17 2v4l-5 6 5 6v4',
  cart: 'M8 21a1 1 0 1 0 0-2 1 1 0 0 0 0 2zM19 21a1 1 0 1 0 0-2 1 1 0 0 0 0 2zM2 2h2l2.7 12.4a2 2 0 0 0 2 1.6h9.7a2 2 0 0 0 2-1.6L22 7H5.1',
  bag: 'M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4zM3 6h18M16 10a4 4 0 0 1-8 0',
  leaf: 'M11 20A7 7 0 0 1 4 13c0-6 5-9 16-10-1 11-4 16-9 17zM4 21c3-5 6-8 10-10',
  snowflake: 'M12 2v20M3.3 7l17.4 10M3.3 17 20.7 7M9 4l3 2 3-2M9 20l3-2 3 2',
  umbrella: 'M22 12a10 10 0 0 0-20 0zM12 12v7a2 2 0 0 0 4 0M12 2v1',
  droplet: 'M12 2.7l5.7 5.6a8 8 0 1 1-11.3 0z',
  unlock: 'M5 11h14v10H5zM8 11V7a4 4 0 0 1 7.8-1.2',
  'trend-down': 'M22 17l-8.5-8.5-5 5L2 7M16 17h6v-6',
  'trend-up': 'M22 7l-8.5 8.5-5-5L2 17M16 7h6v6',
  'check-circle': 'M22 11.1V12a10 10 0 1 1-5.9-9.1M22 4 12 14l-3-3',
  'x-circle': 'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM15 9l-6 6M9 9l6 6',
  wrench: 'M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.8-3.8a6 6 0 0 1-7.9 7.9l-6.9 6.9a2.1 2.1 0 0 1-3-3l6.9-6.9a6 6 0 0 1 7.9-7.9z',
  book: 'M4 19.5A2.5 2.5 0 0 1 6.5 17H20V2H6.5A2.5 2.5 0 0 0 4 4.5zM4 19.5A2.5 2.5 0 0 0 6.5 22H20v-5',
  'arrows-v': 'M8 3v18M4 7l4-4 4 4M16 21V3M12 17l4 4 4-4',
  dumbbell: 'M6.5 6.5v11M17.5 6.5v11M3.5 9v6M20.5 9v6M6.5 12h11',
  coffee: 'M17 8h1a4 4 0 0 1 0 8h-1M3 8h14v9a4 4 0 0 1-4 4H7a4 4 0 0 1-4-4zM6 2v3M10 2v3M14 2v3',
  'battery-low': 'M2 7h16v10H2zM22 11v2M6 11v2',
  eye: 'M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z',
  scissors: 'M6 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM20 4 8.1 15.9M14.5 14.5 20 20M8.1 8.1 12 12',
  smile: 'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM8 14s1.5 2 4 2 4-2 4-2M9 9h.01M15 9h.01',
  'map-pin': 'M12 21s-7-6.2-7-11a7 7 0 1 1 14 0c0 4.8-7 11-7 11zM12 12.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z',
  drop: 'M12 21.5a7 7 0 0 0 7-7c0-2-1-3.9-3-5.5s-3.5-4-4-6.5c-.5 2.5-2 4.9-4 6.5S5 12.5 5 14.5a7 7 0 0 0 7 7z',
  history: 'M3 12a9 9 0 1 0 2.6-6.4L3 8M3 3v5h5M12 7v5l3 2',
  scale: 'M12 3a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM6.5 8h11a2 2 0 0 1 1.9 1.5l2.4 9A2 2 0 0 1 19.9 21H4.1a2 2 0 0 1-1.9-2.5l2.4-9A2 2 0 0 1 6.5 8z',
  note: 'M4 4h16v16H4zM8 9h8M8 13h8M8 17h5',
};

export class HxkIcon extends LitElement {
  static properties = { name: {}, size: { type: Number }, tone: {} };
  declare name: string;
  declare size: number;
  /** Intent colour: success | warning | danger | info | accent | muted; empty = inherit the text colour. */
  declare tone: string;
  static styles = css`:host { display: inline-flex; line-height: 0; vertical-align: -0.15em; } svg { fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }`;
  constructor() { super(); this.size = 16; this.name = ''; this.tone = ''; }
  render() {
    const d = ICONS[this.name] ?? ICONS['more'];
    const color = this.tone ? `color:${toneColor(this.tone)[0]}` : '';
    return html`<svg style=${color} width=${this.size} height=${this.size} viewBox="0 0 24 24" aria-hidden="true">${svg`<path d=${d}></path>`}</svg>`;
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
