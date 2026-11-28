/**
 * <oracle-memory> — "Memory": what the assistant remembers about the user and where each memory came from (learnt in chat
 * or noted by an external AI through memory_note). Search, filter by origin, forget.
 * Reads/acts on /api/ui/memory… (Oracle → Archive through Hub). SPEC docs/work/2026-10-20-memory-note.
 */
import { HestiaElement, html, css, nothing, locale, tr } from '@hestia/webui-sdk';
import { API } from './util';

function day(iso?: string | null): string {
  if (!iso) return '';
  return new Date(iso).toLocaleString(locale(), { day: 'numeric', month: 'short', year: 'numeric' });
}

function origin(m: any): string {
  return m.source === 'external' ? (m.access || tr('External AI')) : tr('In chat');
}

export class OracleMemory extends HestiaElement {
  static properties = { ...HestiaElement.properties, rows: { state: true }, error: { state: true }, q: { state: true },
                        from: { state: true } };
  declare rows: any[] | null; declare error: string; declare q: string; declare from: string;

  static styles = [...HestiaElement.styles, css`
    .head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    .sub { color: var(--text-3); font-size: 13px; }
    .bar input[type=search] { width: 100%; }
    .chips { display: flex; gap: 6px; flex-wrap: wrap; }
    .chip { font: inherit; font-size: 12.5px; padding: 3px 10px; border-radius: var(--radius-full); cursor: pointer;
      background: var(--surface-2); color: var(--text-2); border: 1px solid transparent; }
    .chip.on { background: var(--accent-soft); color: var(--accent); border-color: var(--accent); }
    .mem { display: flex; gap: 12px; align-items: flex-start; padding: 10px 0; border-top: 1px solid var(--border); }
    .mem:first-child { border-top: 0; padding-top: 0; }
    .mem > hxk-icon { margin-top: 2px; }
    .fact { font-size: 14px; }
    .meta { font-size: 12px; color: var(--text-3); margin-top: 4px; display: flex; gap: 4px; flex-wrap: wrap; align-items: center; }
  `];

  constructor() { super(); this.rows = null; this.error = ''; this.q = ''; this.from = ''; }

  connectedCallback() { super.connectedCallback(); this.load(); this.onHost('refresh', () => this.load()); }

  private async load() {
    const r = await this.host.api('GET', `${API}/memory`);
    if (!r.ok) { this.error = r.status === 0 || r.status >= 500 ? tr('Memory not reachable') : r.error || tr('Memory not reachable'); return; }
    this.error = '';
    this.rows = r.data.memories || [];
  }

  private async forget(m: any) {
    if (!(await this.host.confirm(tr('Forget this memory?'), m.fact, { label: tr('Forget'), danger: true }))) return;
    const r = await this.host.api('DELETE', `${API}/memory/${encodeURIComponent(m.id)}`);
    if (!r.ok) { this.host.toast(r.error || tr('alt::Failed'), 'danger'); return; }
    this.rows = (this.rows || []).filter(x => x.id !== m.id);
    this.host.toast(tr('Memory forgotten'), 'success');
  }

  private renderRow(m: any) {
    const ext = m.source === 'external';
    return html`<div class="mem">
      <hxk-icon name=${ext ? 'external' : 'chat'} tone=${ext ? 'info' : 'accent'} size="18"></hxk-icon>
      <div class="grow">
        <div class="fact">${m.fact}</div>
        <div class="meta"><span>${origin(m)}</span>${m.topic ? html`<span>· ${m.topic}</span>` : nothing}
          <span>· ${day(m.created_at)}</span>
          ${(m.domains || []).filter(Boolean).map((d: string) => html`<hxk-badge>${d}</hxk-badge>`)}</div>
      </div>
      <hxk-button size="sm" variant="ghost" icon="trash" title=${tr("Forget")} @click=${() => this.forget(m)}></hxk-button>
    </div>`;
  }

  render() {
    if (this.error) return html`<div class="page"><hxk-state kind="offline" text=${this.error} @retry=${() => this.load()}></hxk-state></div>`;
    if (!this.rows) return html`<div class="page"><hxk-state kind="loading"></hxk-state></div>`;
    const origins = [...new Set(this.rows.map(origin))].sort();
    const q = this.q.trim().toLowerCase();
    const shown = this.rows.filter(m => (!this.from || origin(m) === this.from)
      && (!q || `${m.fact} ${m.topic} ${(m.domains || []).join(' ')}`.toLowerCase().includes(q)));
    return html`<div class="page">
      <hxk-page-head heading=${tr("Memory")} sub=${tr("What {assistant} remembers about you and where she learned it")} ask=${tr("Memory")}>
        <hxk-button variant="ghost" icon="refresh" title=${tr("Refresh")} @click=${() => this.load()}></hxk-button></hxk-page-head>
      <div class="bar"><input type="search" placeholder=${tr("Search in the memories (e.g. «gym»)")} .value=${this.q}
        @input=${(e: any) => (this.q = e.target.value)}></div>
      ${origins.length > 1 ? html`<div class="chips">
        <button class="chip ${this.from ? '' : 'on'}" @click=${() => (this.from = '')}>${tr("All (")}${this.rows.length})</button>
        ${origins.map(o => html`<button class="chip ${this.from === o ? 'on' : ''}" @click=${() => (this.from = o)}>${o}</button>`)}
      </div>` : nothing}
      <hxk-card>${shown.length ? shown.map(m => this.renderRow(m))
        : html`${this.rows.length ? html`<hxk-state kind="empty" text=${tr('No memory matches')}></hxk-state>` : html`<hxk-empty icon="sparkle" heading=${tr("{assistant} doesn't remember anything yet")} example=${tr("Remember that I'm allergic to nuts")}>${tr("Tell me about you in chat: I keep what matters.")}</hxk-empty>`}`}</hxk-card>
    </div>`;
  }
}
