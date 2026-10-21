/**
 * <oracle-memory> — "Memoria": what Hestia remembers about the user and where each memory came from (learnt in chat
 * or noted by an external AI through memory_note). Search, filter by origin, forget.
 * Reads/acts on /api/ui/memory… (Oracle → Archive through Hub). SPEC docs/work/2026-10-20-memory-note.
 */
import { HestiaElement, html, css, nothing } from '@hestia/webui-sdk';
import { API } from './util';

function day(iso?: string | null): string {
  if (!iso) return '';
  return new Date(iso).toLocaleString('it-IT', { day: 'numeric', month: 'short', year: 'numeric' });
}

function origin(m: any): string {
  return m.source === 'external' ? (m.access || 'AI esterna') : 'In chat';
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
    if (!r.ok) { this.error = r.status === 0 || r.status >= 500 ? 'Memoria non raggiungibile' : r.error || 'Memoria non raggiungibile'; return; }
    this.error = '';
    this.rows = r.data.memories || [];
  }

  private async forget(m: any) {
    if (!(await this.host.confirm('Dimenticare questo ricordo?', m.fact, { label: 'Dimentica', danger: true }))) return;
    const r = await this.host.api('DELETE', `${API}/memory/${encodeURIComponent(m.id)}`);
    if (!r.ok) { this.host.toast(r.error || 'Non riuscito', 'danger'); return; }
    this.rows = (this.rows || []).filter(x => x.id !== m.id);
    this.host.toast('Ricordo dimenticato', 'success');
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
      <hxk-button size="sm" variant="ghost" icon="trash" title="Dimentica" @click=${() => this.forget(m)}></hxk-button>
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
      <div class="head"><div class="grow"><h1>Memoria</h1>
        <div class="sub">Quello che Hestia ricorda di te e da dove l'ha saputo</div></div>
        <hxk-button variant="ghost" icon="refresh" title="Aggiorna" @click=${() => this.load()}></hxk-button></div>
      <div class="bar"><input type="search" placeholder="Cerca nei ricordi (es. «palestra»)" .value=${this.q}
        @input=${(e: any) => (this.q = e.target.value)}></div>
      ${origins.length > 1 ? html`<div class="chips">
        <button class="chip ${this.from ? '' : 'on'}" @click=${() => (this.from = '')}>Tutti (${this.rows.length})</button>
        ${origins.map(o => html`<button class="chip ${this.from === o ? 'on' : ''}" @click=${() => (this.from = o)}>${o}</button>`)}
      </div>` : nothing}
      <hxk-card>${shown.length ? shown.map(m => this.renderRow(m))
        : html`<hxk-state kind="empty" text=${this.rows.length ? 'Nessun ricordo corrisponde' : 'Hestia non ricorda ancora nulla di te'}></hxk-state>`}</hxk-card>
    </div>`;
  }
}
