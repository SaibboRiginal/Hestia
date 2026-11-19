/**
 * <hxk-connections> — every external thing Hestia links (accounts, devices, programs at home), from every module, as
 * ONE list with the same card for each (docs/work/2026-11-19-unified-connections; Marko 2026-11-07 «have N of them like
 * a marketplace», 2026-11-19: one way to link, like plugins).
 *
 * `sources` = one entry per module that declares connections (`hestia_common.connections`): its host (the module's
 * own API through the WebUI proxy) and the path `<api_prefix>connections`. The rows are merged and grouped
 * (Accounts · Devices · Home services); a search box appears past 6. Opening a row shows what to do now, drawn from
 * the step the module sends: fields + one button, a page opened in another tab that the card waits for (with the code
 * to type there, when there is one), or a few steps to follow. Every card has «Test», which answers in words with what
 * it found (e.g. the GPU and the models of ComfyUI). Used by the «Connections» page and by the guided setup.
 */
import { LitElement, html, css, nothing } from 'lit';
import { kitStyles } from '../styles';
import { tr } from '../i18n';
import type { HestiaHost } from '../types';

export interface ConnectionSource { module: string; host: HestiaHost; path: string; }

interface Field { name: string; label: string; type: string; placeholder?: string; value?: string; }
interface Step { kind: 'form' | 'wait'; text?: string; fields: Field[]; submit?: string; guide?: string[];
  link?: { label: string; url: string }; url?: string; code?: string; }
interface Action { id: string; label: string; icon?: string; danger?: boolean; }
interface Item { id: string; label: string; icon: string; what: string; group: string; keywords?: string[];
  state: 'connected' | 'waiting' | 'not_connected'; detail: string; step: Step | null; actions: Action[]; test?: boolean; }
interface Row extends Item { key: string; src: ConnectionSource; }
interface TestResult { ok: boolean; detail: string; facts: string[]; }

const GROUPS: [string, string][] = [['account', 'Accounts'], ['device', 'Devices'], ['home_service', 'Home services']];

export class HxkConnections extends LitElement {
  static properties = { sources: { attribute: false }, place: {}, open: {}, rows: { state: true }, busy: { state: true },
                        errors: { state: true }, results: { state: true }, query: { state: true }, down: { state: true } };
  declare sources: ConnectionSource[];
  /** «setup»: only the services offered in the guided setup. */
  declare place: string;
  /** `<module>.<id>` of the card to open (Ctrl+K, «Edit in Connections»). */
  declare open: string;
  declare rows: Row[] | null; declare busy: string; declare errors: Record<string, string>;
  declare results: Record<string, TestResult>; declare query: string; declare down: string[];
  private values: Record<string, Record<string, string>> = {};
  private timer: ReturnType<typeof setInterval> | null = null;
  private loaded = '';

  static styles = [kitStyles, css`
    :host { display: block; }
    .list { display: flex; flex-direction: column; gap: 8px; }
    h3 { font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: .04em; color: var(--text-3); margin: 14px 0 2px; }
    h3:first-child { margin-top: 0; }
    .svc { border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--surface); }
    .svc.open { border-color: var(--border-strong); }
    .head { display: flex; gap: 12px; align-items: center; width: 100%; padding: 12px 14px; border: 0; background: none;
            color: var(--text); text-align: left; cursor: pointer; font: inherit; }
    .ic { flex: none; display: grid; place-items: center; width: 34px; height: 34px; border-radius: var(--radius-full); background: var(--accent-soft); }
    .ct { display: flex; flex-direction: column; gap: 2px; flex: 1; min-width: 0; }
    .ct b { font-size: 14px; font-weight: 600; }
    .ct small { font-size: 12px; color: var(--text-3); line-height: 1.4; overflow-wrap: anywhere; }
    .body { display: flex; flex-direction: column; gap: 10px; padding: 0 14px 14px 60px; }
    .text { font-size: 13px; color: var(--text-2); line-height: 1.5; margin: 0; }
    .code { font: 600 20px/1.2 var(--font-mono, monospace); letter-spacing: .12em; color: var(--text); }
    ol, ul { margin: 0 0 0 18px; padding: 0; font-size: 13px; color: var(--text-2); line-height: 1.5; }
    a { color: var(--accent); }
    .err { font-size: 13px; color: var(--danger); margin: 0; }
    .res { display: flex; flex-direction: column; gap: 4px; padding: 10px 12px; border-radius: var(--radius-md); background: var(--surface-2); }
    .res b { display: flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 600; }
    .search { width: 100%; box-sizing: border-box; padding: 9px 12px; border: 1px solid var(--border); border-radius: var(--radius-md);
              background: var(--surface); color: var(--text); font: inherit; margin-bottom: 8px; }
    .row { display: flex; gap: 8px; align-items: center; }
    .wrap { flex-wrap: wrap; }
    .note { font-size: 12px; color: var(--text-3); margin: 6px 0 0; }
    @media (max-width: 520px) { .body { padding-left: 14px; } }
  `];

  constructor() {
    super();
    this.sources = []; this.place = ''; this.open = ''; this.rows = null; this.busy = ''; this.errors = {};
    this.results = {}; this.query = ''; this.down = [];
  }

  disconnectedCallback() { super.disconnectedCallback(); this.stopPoll(); }

  updated(changed: Map<string, unknown>) {
    const key = (this.sources || []).map(s => s.module).join(',') + '|' + this.place;
    if ((changed.has('sources') || changed.has('place')) && key !== this.loaded) { this.loaded = key; void this.load(); }
  }

  /** Re-read every module (the page calls it on «visible» / «refresh»). */
  async load() {
    const sources = this.sources || [];
    const answers = await Promise.all(sources.map(async src => {
      const r = await src.host.api('GET', src.path, this.place ? { query: { place: this.place } } : undefined);
      return { src, r };
    }));
    const rows: Row[] = [];
    const down: string[] = [];
    for (const { src, r } of answers) {
      if (!r.ok) { down.push(src.module); continue; }
      for (const it of (r.data?.items || []) as Item[]) rows.push({ ...it, key: `${src.module}.${it.id}`, src });
    }
    this.rows = rows;
    this.down = down;
    this.poll();
  }

  /** While a service waits for a page opened elsewhere (Google's consent, Microsoft's code), ask again every 5 s. */
  private poll() {
    const waiting = (this.rows || []).some(i => i.step?.kind === 'wait');
    if (waiting && !this.timer) this.timer = setInterval(() => void this.load(), 5000);
    if (!waiting) this.stopPoll();
  }
  private stopPoll() { if (this.timer) { clearInterval(this.timer); this.timer = null; } }

  private replace(row: Row, item: Item) {
    this.rows = (this.rows || []).map(i => (i.key === row.key ? { ...item, key: row.key, src: row.src } : i));
    this.poll();
  }

  private async send(row: Row, method: 'POST' | 'DELETE', path: string, body?: unknown) {
    this.busy = row.key + path;
    this.errors = { ...this.errors, [row.key]: '' };
    const r = await row.src.host.api(method, `${row.src.path}/${row.id}${path}`, body === undefined ? undefined : { body });
    this.busy = '';
    if (!r.ok) { this.errors = { ...this.errors, [row.key]: r.data?.detail || r.error || tr('Failed: try again.') }; return; }
    if (r.data?.open_url) window.open(r.data.open_url, '_blank', 'noopener');
    if (r.data?.message) row.src.host.toast(r.data.message, 'success');
    if (r.data?.result) this.results = { ...this.results, [row.key]: r.data.result };
    else if (path !== '/test') { const { [row.key]: _, ...rest } = this.results; this.results = rest; }
    if (r.data?.item) this.replace(row, r.data.item);
  }

  private submit(row: Row) {
    const values = this.values[row.key] || {};
    this.values[row.key] = {};                   // passwords and codes never stay in the page
    void this.send(row, 'POST', '', { values });
  }

  private async act(row: Row, a: Action) {
    if (a.id === 'forget') {
      if (!(await row.src.host.confirm(tr('Unlink {0}?', row.label), tr('To link it again access will be needed again.'),
                                        { label: tr('Unlink'), danger: true }))) return;
      void this.send(row, 'DELETE', '');
      return;
    }
    void this.send(row, 'POST', `/${a.id}`);
  }

  private stateText(i: Item): string {
    return i.state === 'connected' ? tr('linked') : i.state === 'waiting' ? tr('waiting') : tr('not linked');
  }

  private stepView(i: Row) {
    const s = i.step;
    if (!s) return nothing;
    const v = (this.values[i.key] ||= {});
    for (const f of s.fields) if (f.value && v[f.name] === undefined) v[f.name] = f.value;
    return html`
      ${s.text ? html`<p class="text">${s.text}</p>` : nothing}
      ${s.code ? html`<span class="code">${s.code}</span>` : nothing}
      ${s.guide?.length ? html`<ol>${s.guide.map(g => html`<li>${g}</li>`)}</ol>` : nothing}
      ${s.link ? html`<a href=${s.link.url} target="_blank" rel="noopener">${s.link.label}</a>` : nothing}
      ${s.kind === 'wait' && s.url ? html`<a href=${s.url} target="_blank" rel="noopener">${tr('Reopen the page')}</a>` : nothing}
      ${s.fields.map(f => html`<hxk-field label=${f.label} type=${f.type} placeholder=${f.placeholder || ''} .value=${v[f.name] || ''}
          @change=${(e: CustomEvent) => { v[f.name] = String(e.detail); }}></hxk-field>`)}
      ${s.submit ? html`<div class="row wrap"><hxk-button variant="primary" icon="link" ?loading=${this.busy === i.key}
          @click=${() => this.submit(i)}>${s.submit}</hxk-button></div>` : nothing}`;
  }

  private resultView(i: Row) {
    const r = this.results[i.key];
    if (!r) return nothing;
    return html`<div class="res" role="status">
      <b><hxk-icon name=${r.ok ? 'check' : 'alert'} size="16" tone=${r.ok ? 'success' : 'danger'}></hxk-icon>${r.detail}</b>
      ${r.facts.length ? html`<ul>${r.facts.map(f => html`<li>${f}</li>`)}</ul>` : nothing}
    </div>`;
  }

  private card(i: Row) {
    const on = this.open === i.key;
    const actions = [...(i.test !== false ? [{ id: 'test', label: tr('Test'), icon: 'pulse' } as Action] : []), ...i.actions];
    return html`<div class="svc ${on ? 'open' : ''}" id=${i.key}>
      <button class="head" aria-expanded=${on} @click=${() => { this.open = on ? '' : i.key; }}>
        <span class="ic"><hxk-icon name=${i.icon} size="18" tone="accent"></hxk-icon></span>
        <span class="ct"><b>${i.label}</b><small>${i.state === 'not_connected' || !i.detail ? i.what : i.detail}</small></span>
        <hxk-badge tone=${i.state === 'connected' ? 'success' : i.state === 'waiting' ? 'warning' : 'neutral'}>${this.stateText(i)}</hxk-badge>
        <hxk-icon name=${on ? 'chevron-up' : 'chevron-down'} size="16" tone="muted"></hxk-icon>
      </button>
      ${on ? html`<div class="body">
        ${i.state === 'connected' && i.detail ? html`<p class="text">${i.what}</p>` : nothing}
        ${i.state !== 'connected' && i.detail ? html`<p class="text">${i.detail}</p>` : nothing}
        ${this.stepView(i)}
        ${this.errors[i.key] ? html`<p class="err">${this.errors[i.key]}</p>` : nothing}
        ${this.resultView(i)}
        <div class="row wrap">${actions.map(a => html`<hxk-button variant=${a.danger ? 'ghost' : 'secondary'}
            icon=${a.icon || nothing} ?loading=${this.busy === i.key + '/' + a.id || (a.id === 'forget' && this.busy === i.key)}
            @click=${() => this.act(i, a)}>${a.label}</hxk-button>`)}</div>
      </div>` : nothing}
    </div>`;
  }

  render() {
    if (!this.rows) return html`<hxk-state kind="loading"></hxk-state>`;
    if (!this.rows.length && this.down.length) return html`<hxk-state kind="offline" text=${tr('Not reachable')} @retry=${() => this.load()}></hxk-state>`;
    const q = this.query.trim().toLowerCase();
    const shown = q ? this.rows.filter(i => `${i.label} ${i.what} ${(i.keywords || []).join(' ')}`.toLowerCase().includes(q)) : this.rows;
    const groups = GROUPS.map(([g, label]) => [label, shown.filter(i => i.group === g)] as [string, Row[]])
      .concat([[tr('Other'), shown.filter(i => !GROUPS.some(([g]) => g === i.group))]])
      .filter(([, rows]) => rows.length);
    const single = groups.length === 1 && this.place === 'setup';
    return html`
      ${this.rows.length > 6 ? html`<input class="search" type="search" placeholder=${tr('Search a service')} .value=${this.query}
          @input=${(e: Event) => { this.query = (e.target as HTMLInputElement).value; }} />` : nothing}
      <div class="list">${groups.map(([label, rows]) => html`${single ? nothing : html`<h3>${tr(label)}</h3>`}${rows.map(i => this.card(i))}`)}</div>
      ${this.down.length ? html`<p class="note">${tr('Some services are not reachable at the moment: they will appear when they are back.')}</p>` : nothing}`;
  }
}
