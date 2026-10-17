import { LitElement } from 'lit';
import type { HestiaHost, HostEvent, PluginContext } from './types';
import { kitStyles, tokens } from './styles';

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

  /** Subscribe to a host event for the element's lifetime. */
  protected onHost(event: HostEvent, cb: () => void): void {
    if (this.host) this._offs.push(this.host.on(event, cb));
  }

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
