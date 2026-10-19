/**
 * <oracle-documents> — "Documenti": the files Hestia keeps for the chat (RAG). List with domain filter, semantic
 * search (same as the chat), add a file (archived like a chat attachment), keep for good, delete.
 * Reads/acts on /api/ui/documents… (Oracle → Archive through Hub). Ported from the built-in WebUI page (§A4).
 */
import { HestiaElement, html, css, nothing } from '@hestia/webui-sdk';
import { API } from './util';

const ACCEPT = 'image/*,audio/*,video/*,text/*,application/pdf,application/json,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.odt,.ods,.odp,.md,.csv,.yaml,.yml';

function day(iso?: string | null): string {
  if (!iso) return '';
  return new Date(iso).toLocaleString('it-IT', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function size(n?: number | null): string {
  const v = Number(n || 0);
  if (!v) return '';
  if (v < 1024) return `${v} B`;
  if (v < 1024 * 1024) return `${Math.round(v / 1024)} KB`;
  return `${(v / 1024 / 1024).toFixed(1).replace('.', ',')} MB`;
}

export class OracleDocuments extends HestiaElement {
  static properties = { ...HestiaElement.properties, docs: { state: true }, error: { state: true }, domain: { state: true },
                        q: { state: true }, hits: { state: true }, searching: { state: true }, adding: { state: true },
                        pending: { state: true } };
  declare docs: any[] | null; declare error: string; declare domain: string; declare q: string; declare hits: any[] | null;
  declare searching: boolean; declare adding: boolean; declare pending: string[];
  private timer: number | undefined;

  static styles = [...HestiaElement.styles, css`
    .head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    .sub { color: var(--text-3); font-size: 13px; }
    .bar { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
    .bar input[type=search] { flex: 1; min-width: 180px; }
    .chips { display: flex; gap: 6px; flex-wrap: wrap; }
    .chip { font: inherit; font-size: 12.5px; padding: 3px 10px; border-radius: var(--radius-full); cursor: pointer;
      background: var(--surface-2); color: var(--text-2); border: 1px solid transparent; }
    .chip.on { background: var(--accent-soft); color: var(--accent); border-color: var(--accent); }
    .docs { --min: 280px; }
    .doc { display: flex; gap: 12px; align-items: flex-start; }
    .doc > hxk-icon { color: var(--accent); margin-top: 2px; }
    .name { font-weight: 500; }
    .meta { font-size: 12px; color: var(--text-3); margin: 2px 0 6px; }
    .sum { font-size: 13px; color: var(--text-2); display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
    .tags { display: flex; gap: 4px; flex-wrap: wrap; margin-top: 6px; }
    .acts { display: flex; flex-direction: column; gap: 2px; }
    .hit { padding: 10px 0; border-top: 1px solid var(--border); }
    .hit:first-child { border-top: 0; padding-top: 0; }
    .passage { font-size: 13px; color: var(--text-2); white-space: pre-wrap; margin: 4px 0 0; }
  `];

  constructor() {
    super(); this.docs = null; this.error = ''; this.domain = ''; this.q = ''; this.hits = null;
    this.searching = false; this.adding = false; this.pending = [];
  }

  connectedCallback() { super.connectedCallback(); this.load(); this.onHost('refresh', () => this.load()); }
  disconnectedCallback() { super.disconnectedCallback(); window.clearTimeout(this.timer); }

  private async load() {
    const r = await this.host.api('GET', `${API}/documents`, { query: { limit: 200 } });
    if (!r.ok) { this.error = r.status === 0 || r.status >= 500 ? 'Oracle non raggiungibile' : r.error || 'Oracle non raggiungibile'; return; }
    this.error = '';
    this.docs = r.data.documents || [];
    const ids = new Set(this.docs!.map(d => d.document_id));
    this.pending = this.pending.filter(id => !ids.has(id));
    window.clearTimeout(this.timer);
    if (this.pending.length) this.timer = window.setTimeout(() => this.load(), 5000);   // archiving runs in background
  }

  private async search() {
    const q = this.q.trim();
    if (!q) { this.hits = null; return; }
    this.searching = true;
    const r = await this.host.api('GET', `${API}/documents/search`, { query: { query: q, limit: 10 } });
    this.searching = false;
    if (!r.ok) { this.host.toast(r.status === 0 ? 'Oracle non raggiungibile' : r.error || 'Ricerca non riuscita', 'danger'); return; }
    this.hits = r.data.chunks || [];
  }

  private async add() {
    const files = await this.host.upload({ accept: ACCEPT, multiple: true, maxSide: 2400 });
    if (!files.length) return;
    this.adding = true;
    let ok = 0;
    for (const f of files) {
      const r = await this.host.api('POST', `${API}/documents`, { body: { name: f.name, mime: f.mime, data_b64: f.data_b64 } });
      if (r.ok) { ok++; this.pending = [...this.pending, r.data.document_id]; }
      else this.host.toast(`${f.name}: ${r.error || 'non aggiunto'}`, 'danger');
    }
    this.adding = false;
    if (ok) this.host.toast(ok === 1 ? 'Sto leggendo il file: comparirà tra poco' : `Sto leggendo ${ok} file: compariranno tra poco`, 'success');
    this.load();
  }

  private async keep(d: any) {
    const r = await this.host.api('PATCH', `${API}/documents/${encodeURIComponent(d.document_id)}/permanent`,
      { body: { is_permanent: !d.is_permanent } });
    if (!r.ok) { this.host.toast(r.error || 'Non riuscito', 'danger'); return; }
    this.docs = (this.docs || []).map(x => x.document_id === d.document_id ? { ...x, is_permanent: !d.is_permanent } : x);
    this.host.toast(d.is_permanent ? 'Ora è temporaneo: può essere ripulito se non lo usi' : 'Tenuto per sempre', 'success');
  }

  private async remove(d: any) {
    if (!(await this.host.confirm('Eliminare il documento?', d.title || d.filename || d.document_id, { label: 'Elimina', danger: true }))) return;
    const r = await this.host.api('DELETE', `${API}/documents/${encodeURIComponent(d.document_id)}`);
    if (!r.ok) { this.host.toast(r.error || 'Eliminazione non riuscita', 'danger'); return; }
    this.docs = (this.docs || []).filter(x => x.document_id !== d.document_id);
    this.hits = this.hits ? this.hits.filter(h => h.document_id !== d.document_id) : null;
    this.host.toast('Documento eliminato', 'success');
  }

  private ask(d: any) {
    this.host.assistant({ label: `Documento · ${d.title || d.filename || 'file'}`, hints: { documento: d.document_id },
      suggestions: ['Riassumilo', 'Cosa dice su…?', 'Quali scadenze contiene?'] });
  }

  private renderHits() {
    if (this.hits === null) return nothing;
    return html`<hxk-card heading="Risultati per «${this.q.trim()}»" subtitle="Passaggi più vicini alla domanda, come li vede la chat">
      ${this.hits.length ? this.hits.map(h => html`<div class="hit">
          <div class="row"><b class="grow truncate">${h.title || 'Documento'}</b>
            <span class="small muted">distanza ${Number(h.distance ?? 0).toFixed(2).replace('.', ',')}</span></div>
          <p class="passage">${h.chunk_text}</p></div>`)
        : html`<hxk-state kind="empty" text="Nessun passaggio abbastanza vicino"></hxk-state>`}
      <hxk-button slot="actions" size="sm" variant="ghost" icon="x" @click=${() => { this.hits = null; this.q = ''; }}>Chiudi</hxk-button>
    </hxk-card>`;
  }

  private renderDoc(d: any) {
    const meta = [day(d.created_at), d.mime_type, size(d.file_size_bytes), d.chunk_count ? `${d.chunk_count} passaggi` : '']
      .filter(Boolean).join(' · ');
    return html`<div class="card doc">
      <hxk-icon name="file" size="22"></hxk-icon>
      <div class="grow">
        <div class="name truncate" title=${d.filename || ''}>${d.title || d.filename || d.document_id}</div>
        <div class="meta">${meta}${d.access_count ? ` · usato ${d.access_count}×` : ''}</div>
        ${d.summary ? html`<div class="sum">${d.summary}</div>` : nothing}
        <div class="tags">${d.is_permanent ? html`<hxk-badge tone="accent">per sempre</hxk-badge>` : nothing}
          <hxk-badge>${d.domain}</hxk-badge>${(d.tags || []).slice(0, 4).map((t: string) => html`<hxk-badge tone="info">${t}</hxk-badge>`)}</div>
      </div>
      <div class="acts">
        <hxk-button size="sm" variant="ghost" icon="sparkle" title="Chiedi a Hestia" @click=${() => this.ask(d)}></hxk-button>
        <hxk-button size="sm" variant="ghost" icon="pin" title=${d.is_permanent ? 'Rendi temporaneo' : 'Tieni per sempre'}
          @click=${() => this.keep(d)}></hxk-button>
        <hxk-button size="sm" variant="ghost" icon="trash" title="Elimina" @click=${() => this.remove(d)}></hxk-button>
      </div>
    </div>`;
  }

  render() {
    if (this.error) return html`<div class="page"><hxk-state kind="offline" text=${this.error} @retry=${() => this.load()}></hxk-state></div>`;
    if (!this.docs) return html`<div class="page"><hxk-state kind="loading"></hxk-state></div>`;
    const domains = [...new Set(this.docs.map(d => d.domain))].sort();
    const shown = this.domain ? this.docs.filter(d => d.domain === this.domain) : this.docs;
    return html`<div class="page">
      <div class="head"><div class="grow"><h1>Documenti</h1>
        <div class="sub">File che hai condiviso con Hestia: la chat li usa quando ne parli</div></div>
        <hxk-button variant="ghost" icon="refresh" title="Aggiorna" @click=${() => this.load()}></hxk-button>
        <hxk-button variant="primary" icon="plus" ?loading=${this.adding} @click=${() => this.add()}>Aggiungi file</hxk-button></div>
      <div class="bar">
        <input type="search" placeholder="Cerca nei documenti (es. «scadenza contratto»)" .value=${this.q}
          @input=${(e: any) => (this.q = e.target.value)} @keydown=${(e: KeyboardEvent) => e.key === 'Enter' && this.search()}>
        <hxk-button icon="search" ?loading=${this.searching} @click=${() => this.search()}>Cerca</hxk-button>
      </div>
      ${this.renderHits()}
      ${this.pending.length ? html`<div class="small muted">Sto leggendo ${this.pending.length} file…</div>` : nothing}
      ${domains.length > 1 ? html`<div class="chips">
        <button class="chip ${this.domain ? '' : 'on'}" @click=${() => (this.domain = '')}>Tutti (${this.docs.length})</button>
        ${domains.map(dm => html`<button class="chip ${this.domain === dm ? 'on' : ''}" @click=${() => (this.domain = dm)}>${dm}</button>`)}
      </div>` : nothing}
      ${shown.length ? html`<div class="grid docs">${shown.map(d => this.renderDoc(d))}</div>`
        : html`<hxk-state kind="empty" text="Nessun documento: aggiungine uno qui o allega un file in chat."></hxk-state>`}
    </div>`;
  }
}
