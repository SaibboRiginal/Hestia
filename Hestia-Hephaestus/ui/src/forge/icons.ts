/** Icons of the Sviluppo page missing from the kit's hxk-icon set (same stroke style); the rest go to hxk-icon. */
import { html, svg } from '@hestia/webui-sdk';

const EXTRA: Record<string, string> = {
  terminal: 'M4 5h16v14H4zM8 10l3 2-3 2M13 15h3',
  branch: 'M6 3v12M6 15a3 3 0 103 3M18 9a3 3 0 10-3-3 3 3 0 003 3zM18 9c0 5-6 4-9 9',
  commit: 'M12 15a3 3 0 100-6 3 3 0 000 6zM3 12h6M15 12h6',
  file: 'M6 3h8l4 4v14H6zM14 3v4h4',
  folder: 'M3 6h6l2 2h10v11H3z',
  diff: 'M8 4v10M3 9h10M11 20h10M16 4v16',
  list: 'M9 6h11M9 12h11M9 18h11M4 6h.01M4 12h.01M4 18h.01',
  flask: 'M9 3h6M10 3v6l-5 9a2 2 0 002 3h10a2 2 0 002-3l-5-9V3M7 15h10',
  info: 'M12 21a9 9 0 110-18 9 9 0 010 18zM12 11v5M12 8h.01',
  alert: 'M12 3l10 18H2zM12 10v4M12 17h.01',
  'arrow-left': 'M19 12H5M11 6l-6 6 6 6',
  tag: 'M3 3h8l10 10-8 8L3 11zM7.5 7.5h.01',
  code: 'M8 7l-5 5 5 5M16 7l5 5-5 5',
  brain: 'M9 4a3 3 0 00-3 3 3 3 0 00-2 5 3 3 0 002 5 3 3 0 006 1V4.5A3 3 0 009 4zM15 4a3 3 0 013 3 3 3 0 012 5 3 3 0 01-2 5 3 3 0 01-6 1',
  user: 'M12 12a4 4 0 100-8 4 4 0 000 8zM4 21a8 8 0 0116 0',
  send: 'M4 12l16-8-6 16-3-7z',
  chat: 'M4 5h16v11H9l-5 4z',
  'chevron-down': 'M6 9l6 6 6-6',
  copy: 'M9 9h11v11H9zM5 15H4V4h11v1',
  download: 'M12 4v11M7 10l5 5 5-5M4 20h16',
  checks: 'M3 12l4 4 7-8M10 16l1 1 10-11',
};

export function icon(name: string, size = 15) {
  const d = EXTRA[name];
  if (!d) return html`<hxk-icon name=${name} size=${size}></hxk-icon>`;
  return html`<svg class="ic" width=${size} height=${size} viewBox="0 0 24 24" aria-hidden="true"
    style="fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round;flex-shrink:0">${svg`<path d=${d}></path>`}</svg>`;
}
