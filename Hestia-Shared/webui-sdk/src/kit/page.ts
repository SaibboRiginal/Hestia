import { LitElement, css, html, nothing } from 'lit';
import { kitStyles, tokens } from '../styles';
import { tr } from '../i18n';

/** Asks the assistant from inside a page: HestiaElement catches it and opens the assistant with the page as context. */
export function askEvent(detail: { label?: string; prompt?: string; suggestions?: string[] }): CustomEvent {
  return new CustomEvent('hxk-ask', { detail, bubbles: true, composed: true });
}

/**
 * The one page header (docs/work/2026-11-27-webui-rethink §3, piece 2): title, one line of context, the page's ONE
 * primary action (default slot; a second action goes in the page, not here) and «Ask» (opens the assistant on this
 * page). The page settings gear is the shell's, top right.
 *
 *   <hxk-page-head heading=${tr('Expenses')} sub=${tr('November: 412 € of 900 €')} ask=${tr('Expenses')}>
 *     <hxk-button variant="primary" icon="plus" @click=…>${tr('New expense')}</hxk-button>
 *   </hxk-page-head>
 */
export class HxkPageHead extends LitElement {
  static properties = { heading: {}, sub: {}, ask: {}, suggestions: { attribute: false } };
  declare heading: string;
  declare sub: string;
  /** Label of the assistant chip; empty = no «Ask» button. */
  declare ask: string;
  declare suggestions: string[];
  static styles = [tokens, kitStyles, css`
    :host { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; min-height: 40px; }
    .t { flex: 1; min-width: 180px; display: flex; flex-direction: column; gap: 2px; }
    h1 { font-size: 24px; line-height: 1.2; }
    .s { color: var(--text-3); font-size: 13.5px; }
    .a { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
    @media (max-width: 860px) { h1 { font-size: 21px; } .ask-l { display: none; } }
  `];
  constructor() { super(); this.heading = ''; this.sub = ''; this.ask = ''; this.suggestions = []; }
  render() {
    return html`<div class="t"><h1>${this.heading}</h1>${this.sub ? html`<span class="s">${this.sub}</span>` : nothing}</div>
      <div class="a"><slot></slot>
        ${this.ask ? html`<hxk-button variant="ghost" icon="sparkle" title=${tr('Ask the assistant about this page')}
          @click=${() => this.dispatchEvent(askEvent({ label: this.ask, suggestions: this.suggestions }))}><span class="ask-l">${tr('Ask')}</span></hxk-button>` : nothing}
      </div>`;
  }
}

/**
 * The one empty state: icon, a sentence, the start button (slot «action») and «or say it in chat» with an example
 * the owner can tap (it opens the assistant with that text).
 *
 *   <hxk-empty icon="wallet" heading=${tr('No expense yet')} example=${tr('I spent 12 € on lunch')}>
 *     ${tr('Add the first one, or import your bank statement.')}
 *     <hxk-button slot="action" variant="primary" icon="plus" …>${tr('New expense')}</hxk-button>
 *   </hxk-empty>
 */
export class HxkEmpty extends LitElement {
  static properties = { icon: {}, heading: {}, example: {} };
  declare icon: string;
  declare heading: string;
  declare example: string;
  static styles = [tokens, kitStyles, css`
    :host { display: flex; flex-direction: column; align-items: center; text-align: center; gap: 10px; padding: 32px 16px;
      border: 1px dashed var(--border-strong); border-radius: var(--radius-lg); }
    .ic { width: 52px; height: 52px; border-radius: 16px; display: grid; place-items: center; color: var(--accent); background: var(--accent-soft); }
    h3 { font-size: 16px; }
    .x { color: var(--text-2); font-size: 14px; max-width: 46ch; }
    .x:empty { display: none; }
    .say { background: none; border: 0; padding: 4px; font: inherit; font-size: 13px; color: var(--text-3); cursor: pointer; }
    .say b { color: var(--accent); font-weight: 500; }
    .say:hover b { text-decoration: underline; }
  `];
  constructor() { super(); this.icon = 'sparkle'; this.heading = ''; this.example = ''; }
  render() {
    return html`<span class="ic"><hxk-icon name=${this.icon} size="24"></hxk-icon></span>
      ${this.heading ? html`<h3>${this.heading}</h3>` : nothing}
      <div class="x"><slot></slot></div>
      <slot name="action"></slot>
      ${this.example ? html`<button class="say" @click=${() => this.dispatchEvent(askEvent({ prompt: this.example }))}>
        ${tr('or say it in chat:')} <b>«${this.example}»</b></button>` : nothing}`;
  }
}
