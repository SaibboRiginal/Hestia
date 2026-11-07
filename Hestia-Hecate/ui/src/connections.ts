/**
 * <hecate-connections> — every account and device Hestia links, as ONE list with the same card for each (Marko
 * 2026-11-07: «averne N come un marketplace», not Google and Garmin each with its own mechanism). A row shows the
 * service, one line on what it gives and its state; opening it shows what to do now right away, drawn from the step
 * Hecate sends (`GET /api/gateway/connections`): fields to fill and one button, a page opened in another tab that the
 * card waits for, or a few steps to follow. Buttons of a connected service come from `actions`. A search box appears
 * when the list is long. Used by the Dispositivi page and by the guided setup (`place="setup"`).
 */
import { HestiaElement, html, css, nothing } from '@hestia/webui-sdk';

const API = '/api/gateway/connections';

interface Field { name: string; label: string; type: string; placeholder?: string; }
interface Step { kind: 'form' | 'wait'; text?: string; fields: Field[]; submit?: string; guide?: string[];
  link?: { label: string; url: string }; url?: string; }
interface Action { id: string; label: string; icon?: string; danger?: boolean; }
interface Item { id: string; label: string; icon: string; what: string; state: 'connected' | 'waiting' | 'not_connected';
  detail: string; step: Step | null; actions: Action[]; }

export class HecateConnections extends HestiaElement {
  static properties = { ...HestiaElement.properties, place: {}, items: { state: true }, open: { state: true },
                        busy: { state: true }, errors: { state: true }, query: { state: true }, err: { state: true } };
  /** «setup»: only the services offered in the guided setup. */
  declare place: string;
  declare items: Item[] | null; declare open: string; declare busy: string; declare errors: Record<string, string>;
  declare query: string; declare err: string;
  private values: Record<string, Record<string, string>> = {};
  private timer: ReturnType<typeof setInterval> | null = null;

  static styles = [...HestiaElement.styles, css`
    :host { display: block; }
    .list { display: flex; flex-direction: column; gap: 8px; }
    .svc { border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--surface); }
    .svc.open { border-color: var(--border-strong); }
    .head { display: flex; gap: 12px; align-items: center; width: 100%; padding: 12px 14px; border: 0; background: none;
            color: var(--text); text-align: left; cursor: pointer; font: inherit; }
    .ic { flex: none; display: grid; place-items: center; width: 34px; height: 34px; border-radius: var(--radius-full); background: var(--accent-soft); }
    .ct { display: flex; flex-direction: column; gap: 2px; flex: 1; min-width: 0; }
    .ct b { font-size: 14px; font-weight: 600; }
    .ct small { font-size: 12px; color: var(--text-3); line-height: 1.4; }
    .body { display: flex; flex-direction: column; gap: 10px; padding: 0 14px 14px 60px; }
    .text { font-size: 13px; color: var(--text-2); line-height: 1.5; margin: 0; }
    ol { margin: 0 0 0 18px; padding: 0; font-size: 13px; color: var(--text-2); line-height: 1.5; }
    a { color: var(--accent); }
    .err { font-size: 13px; color: var(--danger); margin: 0; }
    .search { width: 100%; box-sizing: border-box; padding: 9px 12px; border: 1px solid var(--border); border-radius: var(--radius-md);
              background: var(--surface); color: var(--text); font: inherit; margin-bottom: 8px; }
    @media (max-width: 520px) { .body { padding-left: 14px; } }
  `];

  constructor() {
    super();
    this.place = ''; this.items = null; this.open = ''; this.busy = ''; this.errors = {}; this.query = ''; this.err = '';
  }

  connectedCallback() {
    super.connectedCallback();
    this.load();
    this.onHost('refresh', () => this.load());
    this.onHost('visible', () => this.load());
  }

  disconnectedCallback() { super.disconnectedCallback(); this.stopPoll(); }

  private async load() {
    const place = this.place || this.ctx?.params?.place || '';     // the setup passes it through the plugin outlet
    const r = await this.host.api('GET', API, place ? { query: { place } } : undefined);
    if (!r.ok) { this.err = r.status === 0 ? 'Non raggiungibile' : r.error || 'Non raggiungibile'; return; }
    this.err = '';
    this.items = r.data?.items || [];
    this.poll();
  }

  /** While a service waits for a page opened elsewhere (Google's consent), ask again every 5 s. */
  private poll() {
    const waiting = (this.items || []).some(i => i.step?.kind === 'wait');
    if (waiting && !this.timer) this.timer = setInterval(() => this.load(), 5000);
    if (!waiting) this.stopPoll();
  }
  private stopPoll() { if (this.timer) { clearInterval(this.timer); this.timer = null; } }

  private replace(item: Item) {
    this.items = (this.items || []).map(i => (i.id === item.id ? item : i));
    this.poll();
  }

  private async send(item: Item, method: 'POST' | 'DELETE', path: string, body?: unknown) {
    this.busy = item.id + path;
    this.errors = { ...this.errors, [item.id]: '' };
    const r = await this.host.api(method, `${API}/${item.id}${path}`, body === undefined ? undefined : { body });
    this.busy = '';
    if (!r.ok) { this.errors = { ...this.errors, [item.id]: r.data?.detail || r.error || 'Non riuscito: riprova.' }; return; }
    if (r.data?.open_url) window.open(r.data.open_url, '_blank', 'noopener');
    if (r.data?.message) this.host.toast(r.data.message, 'success');
    if (r.data?.item) this.replace(r.data.item);
  }

  private submit(item: Item) {
    const values = this.values[item.id] || {};
    this.values[item.id] = {};                   // passwords and codes never stay in the page
    this.send(item, 'POST', '', { values });
  }

  private async act(item: Item, a: Action) {
    if (a.id === 'forget') {
      if (!(await this.host.confirm(`Scollegare ${item.label}?`, 'Per ricollegarlo servirà di nuovo l\'accesso.', { label: 'Scollega', danger: true }))) return;
      this.send(item, 'DELETE', '');
      return;
    }
    this.send(item, 'POST', `/${a.id}`);
  }

  private stateText(i: Item): string {
    return i.state === 'connected' ? 'collegato' : i.state === 'waiting' ? 'in attesa' : 'non collegato';
  }

  private stepView(i: Item) {
    const s = i.step;
    if (!s) return nothing;
    const v = (this.values[i.id] ||= {});
    return html`
      ${s.text ? html`<p class="text">${s.text}</p>` : nothing}
      ${s.guide?.length ? html`<ol>${s.guide.map(g => html`<li>${g}</li>`)}</ol>` : nothing}
      ${s.link ? html`<a href=${s.link.url} target="_blank" rel="noopener">${s.link.label}</a>` : nothing}
      ${s.kind === 'wait' && s.url ? html`<a href=${s.url} target="_blank" rel="noopener">Riapri la pagina</a>` : nothing}
      ${s.fields.map(f => html`<hxk-field label=${f.label} type=${f.type} placeholder=${f.placeholder || ''} .value=${v[f.name] || ''}
          @change=${(e: CustomEvent) => { v[f.name] = String(e.detail); }}></hxk-field>`)}
      ${s.submit ? html`<div class="row wrap"><hxk-button variant="primary" icon="link" ?loading=${this.busy === i.id}
          @click=${() => this.submit(i)}>${s.submit}</hxk-button></div>` : nothing}`;
  }

  private row(i: Item) {
    const on = this.open === i.id;
    return html`<div class="svc ${on ? 'open' : ''}">
      <button class="head" aria-expanded=${on} @click=${() => { this.open = on ? '' : i.id; }}>
        <span class="ic"><hxk-icon name=${i.icon} size="18" tone="accent"></hxk-icon></span>
        <span class="ct"><b>${i.label}</b><small>${i.state === 'not_connected' || !i.detail ? i.what : i.detail}</small></span>
        <hxk-badge tone=${i.state === 'connected' ? 'success' : i.state === 'waiting' ? 'warning' : 'neutral'}>${this.stateText(i)}</hxk-badge>
        <hxk-icon name=${on ? 'chevron-up' : 'chevron-down'} size="16" tone="muted"></hxk-icon>
      </button>
      ${on ? html`<div class="body">
        ${i.state === 'connected' && i.detail ? html`<p class="text">${i.what}</p>` : nothing}
        ${i.state !== 'connected' && i.detail ? html`<p class="text">${i.detail}</p>` : nothing}
        ${this.stepView(i)}
        ${this.errors[i.id] ? html`<p class="err">${this.errors[i.id]}</p>` : nothing}
        ${i.actions.length ? html`<div class="row wrap">${i.actions.map(a => html`<hxk-button variant=${a.danger ? 'ghost' : 'secondary'}
            icon=${a.icon || nothing} ?loading=${this.busy === i.id + '/' + a.id || (a.id === 'forget' && this.busy === i.id)}
            @click=${() => this.act(i, a)}>${a.label}</hxk-button>`)}</div>` : nothing}
      </div>` : nothing}
    </div>`;
  }

  render() {
    if (this.err) return html`<hxk-state kind="offline" text=${this.err} @retry=${() => this.load()}></hxk-state>`;
    if (!this.items) return html`<hxk-state kind="loading"></hxk-state>`;
    const q = this.query.trim().toLowerCase();
    const shown = q ? this.items.filter(i => `${i.label} ${i.what}`.toLowerCase().includes(q)) : this.items;
    return html`
      ${this.items.length > 6 ? html`<input class="search" type="search" placeholder="Cerca un servizio" .value=${this.query}
          @input=${(e: Event) => { this.query = (e.target as HTMLInputElement).value; }} />` : nothing}
      <div class="list">${shown.map(i => this.row(i))}</div>`;
  }
}
