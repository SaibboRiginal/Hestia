import { css } from 'lit';

/**
 * Shared kit styles. Every value is a WebUI design token (CSS custom properties set on <html> by the
 * WebUI ThemeService); custom properties inherit into shadow DOM, so plugins follow every theme.
 * Token list: Hestia-WebUI/frontend/DESIGN-SYSTEM.md § Tokens.
 */
export const tokens = css`
  :host {
    font-family: var(--font-sans);
    color: var(--text);
    font-size: 14px;
    line-height: 1.45;
    box-sizing: border-box;
  }
  *, *::before, *::after { box-sizing: inherit; }
  /* scrollbar-color inherits from the WebUI <html>; scrollbar-width does not cross the shadow root */
  * { scrollbar-width: thin; }
`;

/** Utility classes mirroring the WebUI helpers (.hx-row, .hx-card…), usable inside any plugin shadow root. */
export const kitStyles = css`
  .row { display: flex; align-items: center; gap: 8px; }
  .col { display: flex; flex-direction: column; gap: 8px; }
  .grow { flex: 1; min-width: 0; }
  .wrap { flex-wrap: wrap; }
  .muted { color: var(--text-3); }
  .small { font-size: 12px; }
  .truncate { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 14px 16px; }
  .grid { display: grid; gap: 12px; grid-template-columns: repeat(auto-fill, minmax(var(--min, 220px), 1fr)); }
  .page { display: flex; flex-direction: column; gap: 16px; padding: 18px 24px; max-width: 1200px; margin: 0 auto; width: 100%; }
  h1, h2, h3 { font-family: var(--font-serif); font-weight: 500; margin: 0; color: var(--text); }
  h1 { font-size: 24px; } h2 { font-size: 18px; } h3 { font-size: 15px; }
  a { color: var(--accent); text-decoration: none; } a:hover { text-decoration: underline; }
  input, select, textarea {
    font: inherit; color: var(--text); background: var(--surface-2); border: 1px solid var(--border-strong);
    border-radius: var(--radius-sm); padding: 7px 10px; outline: none; min-width: 0;
  }
  input:focus, select:focus, textarea:focus { border-color: var(--accent); box-shadow: 0 0 0 3px var(--focus-ring); }
  /* Touch screens: --tap is 44px there (WebUI styles.scss, pointer: coarse), 0 elsewhere. data-dense opts out. */
  button:not([data-dense]), select, input:not([type=checkbox]):not([type=radio]):not([type=range]):not([type=color]) {
    min-height: var(--tap, 0px); }
  @media (max-width: 860px) { .page { padding: 14px 12px; } }
  /* Phone: the WebUI shell's menu button is on the first line (its height, 44px, set as --head-inset). */
  .page > :first-child { margin-left: var(--head-inset, 0px); min-height: min(var(--head-inset, 0px), 40px); }
`;

export const toneColor = (tone?: string) => {
  switch (tone) {
    case 'success': return ['var(--success)', 'var(--success-soft)'];
    case 'warning': return ['var(--warning)', 'var(--warning-soft)'];
    case 'danger': return ['var(--danger)', 'var(--danger-soft)'];
    case 'info': return ['var(--info)', 'var(--info-soft)'];
    case 'accent': return ['var(--accent)', 'var(--accent-soft)'];
    default: return ['var(--text-2)', 'var(--surface-2)'];
  }
};
