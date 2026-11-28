import { LitElement } from 'lit';
import type { HestiaHost, HostEvent, PluginContext } from './types';
import { kitStyles, tokens } from './styles';
import { tr } from './i18n';

/**
 * Base class for plugin pages and widgets: receives `host` and `ctx` from the WebUI, shares the kit styles,
 * and drops host listeners on disconnect.
 *
 *   export class ScoutListings extends HestiaElement {
 *     static styles = [...HestiaElement.styles, css`...`];
 *     render() { return html`<div class="page">…</div>`; }
 *   }
 *   definePlugin({ 'scout-listings': ScoutListings });
 */
export class HestiaElement extends LitElement {
  static styles = [tokens, kitStyles];
  static properties = { host: { attribute: false }, ctx: { attribute: false } };

  declare host: HestiaHost;
  declare ctx: PluginContext;
  private _offs: Array<() => void> = [];

  constructor() {
    super();
    // «Ask» from the kit (hxk-page-head, hxk-empty): the assistant opens with this page as context.
    this.addEventListener('hxk-ask', (e: Event) => {
      const d = (e as CustomEvent).detail ?? {};
      e.stopPropagation();
      this.host?.assistant({ label: d.label || this.ctx?.title || this.ctx?.id || '', prompt: d.prompt,
                             suggestions: d.suggestions?.length ? d.suggestions : undefined, hints: { page: this.ctx?.id ?? '' } });
    });
  }

  /** Subscribe to a host event for the element's lifetime. */
  protected onHost(event: HostEvent, cb: () => void): void {
    if (this.host) this._offs.push(this.host.on(event, cb));
  }

  /** Widgets: «nothing to show now» — the dashboard gives the cell less room until there is something again. */
  protected markEmpty(empty: boolean): void {
    if (this.ctx?.surface !== 'widget' || this._empty === empty) return;
    this._empty = empty;
    this.dispatchEvent(new CustomEvent('hestia-widget-empty', { detail: empty, bubbles: true, composed: true }));
  }
  private _empty?: boolean;

  disconnectedCallback(): void {
    super.disconnectedCallback();
    this._offs.forEach(off => off());
    this._offs = [];
  }
}

/** Registers custom elements once (bundles may be reloaded when their version changes). */
export function definePlugin(elements: Record<string, CustomElementConstructor>): void {
  for (const [name, ctor] of Object.entries(elements)) {
    if (!customElements.get(name)) customElements.define(name, ctor);
  }
}

/** Fill `{name}` placeholders of a path from values (encoded). */
export function fillPath(path: string, values: Record<string, string | number>): string {
  return path.replace(/\{(\w+)\}/g, (_, k) => encodeURIComponent(String(values[k] ?? '')));
}

/** `plural(3, 'exercise', 'exercises')` → «3 exercises»: count plus the right form, both written in English and
 * translated (it and en: only 1 is singular). */
export function plural(n: number | null | undefined, one: string, many: string): string {
  const v = Number(n ?? 0);
  return `${v} ${tr(v === 1 ? one : many)}`;
}
