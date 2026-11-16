/**
 * Calliope («Documenti») WebUI plugin (plugin contract docs/work/2026-10-17-client-plugins/SPEC.md §4; dossier
 * docs/work/2026-10-24-tutto-brainstorm-cindy W7). Page declared in Hestia-Calliope/app/main.py.
 */
import { HestiaElement, css, definePlugin, html, nothing, locale, tr } from '@hestia/webui-sdk';
import type { ApiResult, HestiaHost, HttpMethod } from '@hestia/webui-sdk';

const API = '/api/office';
const FORMAT: Record<string, string> = { pdf: 'PDF', docx: 'Word', xlsx: tr('Excel') };

async function call<T = any>(host: HestiaHost, method: HttpMethod, path: string, body?: unknown): Promise<ApiResult<T>> {
  const r = await host.api<T>(method, `${API}${path}`, body === undefined ? undefined : { body });
  if (!r.ok && method !== 'GET') host.toast(r.status === 0 ? tr('Not reachable, try again') : r.error || tr('Error'), 'warning');
  return r;
}
const when = (iso: string) => new Date(iso).toLocaleString(locale(), { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });

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
    if (!r.ok) { this.host.toast(tr('I can\'t download it now'), 'warning'); return; }
    const bytes = Uint8Array.from(atob(r.data.data_b64), c => c.charCodeAt(0));
    const url = URL.createObjectURL(new Blob([bytes], { type: r.data.mime }));
    const a = document.createElement('a');
    a.href = url; a.download = r.data.name; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  }
  private async create() {
    const d = this.draft;
    if (!d.title?.trim() || !d.html?.trim()) { this.host.toast(tr('Title and content are needed'), 'warning'); return; }
    this.busy = true;
    const r = await call(this.host, 'POST', '', { ...d, must_contain: (d.must || '').split('\n').map((s: string) => s.trim()).filter(Boolean) });
    this.busy = false;
    if (!r.ok) return;
    if (!r.data.created) { this.host.toast(tr("The check didn't pass: {0} is missing", (r.data.check?.missing || []).join(', ')), 'warning'); return; }
    this.draft = null;
    this.host.toast(tr('{0} ready', r.data.title), 'success');
    this.load();
  }
  private async deleteDoc(d: any) {
    if (!await this.host.confirm(tr('Delete the document?'), d.title, { label: tr('Delete'), danger: true })) return;
    const r = await call(this.host, 'DELETE', `/${d.id}`);
    if (r.ok) this.load();
  }
  private editor() {
    const d = this.draft;
    const set = (k: string) => (e: any) => { this.draft = { ...this.draft, [k]: e.detail ?? e.target.value }; };
    return html`<div class="card col">
      <div class="form">
        <hxk-field label=${tr("Title")} .value=${d.title || ''} @change=${set('title')}></hxk-field>
        <hxk-field label=${tr("Format")} type="enum" .options=${Object.entries(FORMAT).map(([value, label]) => ({ value, label }))} .value=${d.format} @change=${set('format')}></hxk-field>
        <hxk-field label=${tr("Style")} type="enum" .options=${[{ value: '', label: tr('The one chosen in the settings') }, ...Object.entries(this.themes).map(([value, label]) => ({ value, label }))]} .value=${d.theme || ''} @change=${set('theme')}></hxk-field>
      </div>
      <label class="small muted">${tr("Content: plain text (paragraphs separated by an empty line) or HTML with titles, lists and tables. In Excel every table becomes a sheet.")}</label>
      <textarea .value=${d.html || ''} @input=${set('html')}></textarea>
      <hxk-field label=${tr("Must contain (one line per sentence or number)")} type="textarea" .value=${d.must || ''} @change=${set('must')}></hxk-field>
      <div class="row"><hxk-button variant="primary" ?loading=${this.busy} @click=${() => this.create()}>${tr("Create")}</hxk-button>
        <hxk-button variant="ghost" @click=${() => { this.draft = null; }}>${tr("Cancel")}</hxk-button></div>
    </div>`;
  }
  render() {
    if (this.items === undefined) return html`<hxk-state kind="loading"></hxk-state>`;
    if (this.items === null) return html`<hxk-state kind="offline" @retry=${() => this.load()}></hxk-state>`;
    return html`<div class="page">
      <div class="between"><h1>${tr("Documents created")}</h1>
        <div class="row"><hxk-button variant="ghost" icon="chat" @click=${() => this.host.assistant({ label: tr('New document'), suggestions: [tr('Make me a PDF with…'), tr('An Excel with this month\'s expenses'), tr('A Word letter for…')] })}>${tr("Ask the assistant")}</hxk-button>
          <hxk-button variant="primary" icon="plus" @click=${() => { this.draft = { format: 'pdf' }; }}>${tr("New")}</hxk-button></div></div>
      ${this.draft ? this.editor() : nothing}
      <div class="card">${this.items.length ? this.items.map(d => html`<div class="doc">
          <div class="ext">${(FORMAT[d.format] || d.format).slice(0, 4).toUpperCase()}</div>
          <div class="grow"><div class="truncate">${d.title}</div><div class="small muted">${when(d.created_at)} · ${d.pages} ${d.format === 'pdf' ? tr('pages') : d.format === 'xlsx' ? tr('sheets') : tr('parts')} · ${Math.max(1, Math.round((d.size || 0) / 1024))} KB</div></div>
          <hxk-button size="sm" icon="download" @click=${() => this.download(d)}>${tr("Download")}</hxk-button>
          <hxk-button size="sm" variant="ghost" icon="trash" @click=${() => this.deleteDoc(d)}></hxk-button></div>`)
        : html`<hxk-state kind="empty" text=${tr("No document yet. Ask in chat «make me a PDF with…» or create one here.")}></hxk-state>`}</div>
    </div>`;
  }
}

definePlugin({ 'calliope-docs': CalliopeDocs });
