/**
 * Calliope («Documenti») WebUI plugin (plugin contract docs/work/2026-10-17-client-plugins/SPEC.md §4; dossier
 * docs/work/2026-10-24-tutto-brainstorm-cindy W7). Page declared in Hestia-Calliope/app/main.py.
 */
import { HestiaElement, css, definePlugin, html, nothing } from '@hestia/webui-sdk';
import type { ApiResult, HestiaHost, HttpMethod } from '@hestia/webui-sdk';

const API = '/api/office';
const FORMAT: Record<string, string> = { pdf: 'PDF', docx: 'Word', xlsx: 'Excel' };

async function call<T = any>(host: HestiaHost, method: HttpMethod, path: string, body?: unknown): Promise<ApiResult<T>> {
  const r = await host.api<T>(method, `${API}${path}`, body === undefined ? undefined : { body });
  if (!r.ok && method !== 'GET') host.toast(r.status === 0 ? 'Non raggiungibile, riprova' : r.error || 'Errore', 'warning');
  return r;
}
const when = (iso: string) => new Date(iso).toLocaleString('it-IT', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });

const styles = css`
  .between { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
  .doc { display: flex; gap: 12px; align-items: center; padding: 10px 4px; border-bottom: 1px solid var(--border); }
  .doc:last-child { border-bottom: 0; }
  .ext { width: 42px; height: 42px; border-radius: var(--radius-sm); display: grid; place-items: center; font-size: 11px; font-weight: 700;
    background: var(--accent-soft); color: var(--accent); flex: none; }
  .form { display: grid; gap: 10px; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); }
  textarea { width: 100%; min-height: 180px; font-family: var(--font-mono); font-size: 13px; }
`;

export class CalliopeDocs extends HestiaElement {
  static properties = { ...HestiaElement.properties, items: { state: true }, themes: { state: true }, draft: { state: true }, busy: { state: true } };
  declare items: any[] | null | undefined;
  declare themes: Record<string, string>;
  declare draft: any;
  declare busy: boolean;
  static styles = [...HestiaElement.styles, styles];
  constructor() { super(); this.items = undefined; this.themes = {}; this.draft = null; this.busy = false; }
  connectedCallback() { super.connectedCallback(); this.load(); this.onHost('refresh', () => this.load()); }
  async load() { const r = await call(this.host, 'GET', ''); this.items = r.ok ? r.data.items : null; if (r.ok) this.themes = r.data.themes; }
  private async download(d: any) {
    const r = await call(this.host, 'GET', `/${d.id}/b64`);
    if (!r.ok) { this.host.toast('Non riesco a scaricarlo adesso', 'warning'); return; }
    const bytes = Uint8Array.from(atob(r.data.data_b64), c => c.charCodeAt(0));
    const url = URL.createObjectURL(new Blob([bytes], { type: r.data.mime }));
    const a = document.createElement('a');
    a.href = url; a.download = r.data.name; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  }
  private async create() {
    const d = this.draft;
    if (!d.title?.trim() || !d.html?.trim()) { this.host.toast('Servono titolo e contenuto', 'warning'); return; }
    this.busy = true;
    const r = await call(this.host, 'POST', '', { ...d, must_contain: (d.must || '').split('\n').map((s: string) => s.trim()).filter(Boolean) });
    this.busy = false;
    if (!r.ok) return;
    if (!r.data.created) { this.host.toast(`Il controllo non è passato: manca ${(r.data.check?.missing || []).join(', ')}`, 'warning'); return; }
    this.draft = null;
    this.host.toast(`${r.data.title} pronto`, 'success');
    this.load();
  }
  private async deleteDoc(d: any) {
    if (!await this.host.confirm('Eliminare il documento?', d.title, { label: 'Elimina', danger: true })) return;
    const r = await call(this.host, 'DELETE', `/${d.id}`);
    if (r.ok) this.load();
  }
  private editor() {
    const d = this.draft;
    const set = (k: string) => (e: any) => { this.draft = { ...this.draft, [k]: e.detail ?? e.target.value }; };
    return html`<div class="card col">
      <div class="form">
        <hxk-field label="Titolo" .value=${d.title || ''} @change=${set('title')}></hxk-field>
        <hxk-field label="Formato" type="enum" .options=${Object.entries(FORMAT).map(([value, label]) => ({ value, label }))} .value=${d.format} @change=${set('format')}></hxk-field>
        <hxk-field label="Stile" type="enum" .options=${[{ value: '', label: 'Quello scelto nelle impostazioni' }, ...Object.entries(this.themes).map(([value, label]) => ({ value, label }))]} .value=${d.theme || ''} @change=${set('theme')}></hxk-field>
      </div>
      <label class="small muted">Contenuto: testo semplice (paragrafi separati da una riga vuota) o HTML con titoli, elenchi e tabelle. In Excel ogni tabella diventa un foglio.</label>
      <textarea .value=${d.html || ''} @input=${set('html')}></textarea>
      <hxk-field label="Deve contenere (una riga per frase o numero)" type="textarea" .value=${d.must || ''} @change=${set('must')}></hxk-field>
      <div class="row"><hxk-button variant="primary" ?loading=${this.busy} @click=${() => this.create()}>Crea</hxk-button>
        <hxk-button variant="ghost" @click=${() => { this.draft = null; }}>Annulla</hxk-button></div>
    </div>`;
  }
  render() {
    if (this.items === undefined) return html`<hxk-state kind="loading"></hxk-state>`;
    if (this.items === null) return html`<hxk-state kind="offline" @retry=${() => this.load()}></hxk-state>`;
    return html`<div class="page">
      <div class="between"><h1>Documenti creati</h1>
        <div class="row"><hxk-button variant="ghost" icon="chat" @click=${() => this.host.assistant({ label: 'Nuovo documento', suggestions: ['Fammi un PDF con…', 'Un Excel con le spese del mese', 'Una lettera in Word per…'] })}>Chiedi all'assistente</hxk-button>
          <hxk-button variant="primary" icon="plus" @click=${() => { this.draft = { format: 'pdf' }; }}>Nuovo</hxk-button></div></div>
      ${this.draft ? this.editor() : nothing}
      <div class="card">${this.items.length ? this.items.map(d => html`<div class="doc">
          <div class="ext">${(FORMAT[d.format] || d.format).slice(0, 4).toUpperCase()}</div>
          <div class="grow"><div class="truncate">${d.title}</div><div class="small muted">${when(d.created_at)} · ${d.pages} ${d.format === 'pdf' ? 'pagine' : d.format === 'xlsx' ? 'fogli' : 'parti'} · ${Math.max(1, Math.round((d.size || 0) / 1024))} KB</div></div>
          <hxk-button size="sm" icon="download" @click=${() => this.download(d)}>Scarica</hxk-button>
          <hxk-button size="sm" variant="ghost" icon="trash" @click=${() => this.deleteDoc(d)}></hxk-button></div>`)
        : html`<hxk-state kind="empty" text="Ancora nessun documento. Chiedi in chat «fammi un PDF con…» o creane uno qui."></hxk-state>`}</div>
    </div>`;
  }
}

definePlugin({ 'calliope-docs': CalliopeDocs });
