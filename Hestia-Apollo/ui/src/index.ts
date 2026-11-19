/**
 * Apollo («Images», ComfyUI) WebUI plugin (plugin contract docs/work/2026-10-17-client-plugins/SPEC.md §4; dossier
 * docs/work/2026-10-24-whole-cindy-brainstorm W7). Pages declared in Hestia-Apollo/app/main.py.
 */
import { HestiaElement, css, definePlugin, html, nothing, tr } from '@hestia/webui-sdk';
import type { ApiResult, HestiaHost, HttpMethod } from '@hestia/webui-sdk';

const API = '/api/images';
const STATUS: Record<string, [string, string]> = { queued: [tr('queued'), 'neutral'], running: [tr('running'), 'info'], done: [tr('f::ready'), 'success'], failed: [tr('f::failed'), 'danger'] };
const WHY: Record<string, string> = { missing_flow: tr('A workflow for this kind of image is missing: upload it in Workflows.'),
  not_configured: tr('The image generator is not linked yet.') };

async function call<T = any>(host: HestiaHost, method: HttpMethod, path: string, body?: unknown, query?: Record<string, any>): Promise<ApiResult<T>> {
  const r = await host.api<T>(method, `${API}${path}`, { body, query });
  if (!r.ok && method !== 'GET') host.toast(r.status === 0 ? tr('Not reachable, try again') : r.error || tr('Error'), 'warning');
  return r;
}

const styles = css`
  .between { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
  .click { cursor: pointer; }
  .thumb { aspect-ratio: 1; border-radius: var(--radius-lg); overflow: hidden; background: var(--surface-2); display: grid; place-items: center;
    border: 1px solid var(--border); cursor: pointer; position: relative; }
  .thumb img { width: 100%; height: 100%; object-fit: cover; }
  .thumb .cap { position: absolute; left: 0; right: 0; bottom: 0; padding: 6px 8px; font-size: 12px; background: linear-gradient(transparent, var(--overlay)); color: #fff; }
  .big img { max-width: 100%; border-radius: var(--radius-lg); }
  textarea { width: 100%; min-height: 70px; }
  .flow { display: flex; gap: 10px; align-items: center; padding: 8px 2px; border-bottom: 1px solid var(--border); }
  .flow:last-child { border-bottom: 0; }
`;

export class ApolloImages extends HestiaElement {
  static properties = { ...HestiaElement.properties, s: { state: true }, jobs: { state: true }, prompt: { state: true }, purpose: { state: true }, busy: { state: true } };
  declare s: any;
  declare jobs: any[];
  declare prompt: string;
  declare purpose: string;
  declare busy: boolean;
  private timer = 0;
  static styles = [...HestiaElement.styles, styles];
  constructor() { super(); this.s = undefined; this.jobs = []; this.prompt = ''; this.purpose = 'generic'; this.busy = false; }
  connectedCallback() { super.connectedCallback(); this.load(); this.onHost('refresh', () => this.load()); }
  disconnectedCallback() { super.disconnectedCallback(); clearTimeout(this.timer); }
  async load() {
    const [s, j] = await Promise.all([call(this.host, 'GET', '/status'), call(this.host, 'GET', '/jobs', undefined, { limit: 24 })]);
    this.s = s.ok ? s.data : null;
    this.jobs = j.ok ? j.data.items : [];
    clearTimeout(this.timer);
    if (this.jobs.some(x => x.status === 'queued' || x.status === 'running')) this.timer = window.setTimeout(() => this.load(), 4000);
  }
  private async create() {
    if (!this.prompt.trim()) return;
    this.busy = true;
    const r = await call(this.host, 'POST', '/jobs', { prompt: this.prompt, purpose: this.purpose, by: 'user', notify: true });
    this.busy = false;
    if (r.ok) { this.prompt = ''; if (r.data.status === 'failed') this.host.toast(WHY[r.data.error] || tr('alt2::Failed'), 'warning'); this.load(); }
  }
  render() {
    const s = this.s;
    if (s === undefined) return html`<hxk-state kind="loading"></hxk-state>`;
    if (s === null) return html`<hxk-state kind="offline" @retry=${() => this.load()}></hxk-state>`;
    return html`<div class="page">
      <div class="between"><h1>${tr("Images")}</h1><hxk-button variant="ghost" icon="upload" @click=${() => this.host.navigate('workflows')}>${tr("Workflows (")}${s.flows})</hxk-button></div>
      ${!s.configured ? html`<div class="card small">${tr("The generator is not linked: the address of your ComfyUI (APOLLO_COMFYUI_URL in the configuration file) and an uploaded workflow are needed.")}</div>`
        : !s.reachable ? html`<div class="card small">${tr("ComfyUI doesn't answer now: the requests stay in the queue.")}</div>` : nothing}
      <div class="card col">
        <textarea placeholder=${tr("Describe the image (better in English)")} .value=${this.prompt} @input=${(e: any) => { this.prompt = e.target.value; }}></textarea>
        <div class="row wrap"><select @change=${(e: any) => { this.purpose = e.target.value; }}>
            ${Object.entries(s.purposes as Record<string, string>).map(([k, v]) => html`<option value=${k} ?selected=${k === this.purpose}>${v}</option>`)}</select>
          <hxk-button variant="primary" icon="sparkle" ?loading=${this.busy} @click=${() => this.create()}>${tr("Create")}</hxk-button></div>
      </div>
      ${this.jobs.length ? html`<div class="grid" style="--min: 160px">${this.jobs.map(j => html`<div class="thumb" @click=${() => this.host.navigate('job/' + j.id)}>
          ${j.status === 'done' && j.blob_ids?.length ? html`<img loading="lazy" src=${this.host.image(`${API}/jobs/${j.id}/image/0`)} alt="">` : html`<hxk-badge tone=${STATUS[j.status]?.[1] || 'neutral'}>${STATUS[j.status]?.[0] || j.status}</hxk-badge>`}
          <div class="cap truncate">${j.prompt}</div></div>`)}</div>`
        : html`<hxk-state kind="empty" text=${tr("No image yet.")}></hxk-state>`}
    </div>`;
  }
}

export class ApolloJob extends HestiaElement {
  static properties = { ...HestiaElement.properties, j: { state: true } };
  declare j: any;
  private timer = 0;
  static styles = [...HestiaElement.styles, styles];
  constructor() { super(); this.j = undefined; }
  connectedCallback() { super.connectedCallback(); this.load(); }
  disconnectedCallback() { super.disconnectedCallback(); clearTimeout(this.timer); }
  async load() {
    const r = await call(this.host, 'GET', `/jobs/${encodeURIComponent(this.ctx?.params?.id || '')}`);
    this.j = r.ok ? r.data : null;
    if (this.j && (this.j.status === 'queued' || this.j.status === 'running')) this.timer = window.setTimeout(() => this.load(), 4000);
  }
  render() {
    const j = this.j;
    if (j === undefined) return html`<hxk-state kind="loading"></hxk-state>`;
    if (j === null) return html`<hxk-state kind="error" text=${tr("Image not found.")}></hxk-state>`;
    return html`<div class="page">
      <div class="between"><h1>${tr("Image")}</h1><hxk-badge tone=${STATUS[j.status]?.[1] || 'neutral'}>${STATUS[j.status]?.[0] || j.status}</hxk-badge></div>
      <div class="small muted">${j.prompt}</div>
      ${j.status === 'failed' ? html`<div class="card small">${WHY[j.error] || j.error}</div>` : nothing}
      <div class="col big">${(j.blob_ids || []).map((_: string, n: number) => html`<a href=${this.host.image(`${API}/jobs/${j.id}/image/${n}`)} download=${`image-${n + 1}.png`}>
        <img src=${this.host.image(`${API}/jobs/${j.id}/image/${n}`)} alt=""></a>`)}</div>
    </div>`;
  }
}

export class ApolloFlows extends HestiaElement {
  static properties = { ...HestiaElement.properties, items: { state: true }, purposes: { state: true }, draft: { state: true } };
  declare items: any[] | null | undefined;
  declare purposes: Record<string, string>;
  declare draft: any;
  static styles = [...HestiaElement.styles, styles];
  constructor() { super(); this.items = undefined; this.purposes = {}; this.draft = null; }
  connectedCallback() { super.connectedCallback(); this.load(); }
  async load() { const r = await call(this.host, 'GET', '/flows'); this.items = r.ok ? r.data.items : null; if (r.ok) this.purposes = r.data.purposes; }
  private pick(e: any) {
    const f: File | undefined = e.target.files?.[0];
    if (!f) return;
    f.text().then(t => {
      try { this.draft = { ...this.draft, graph: JSON.parse(t), file: f.name, name: this.draft?.name || f.name.replace(/\.json$/i, '') }; }
      catch { this.host.toast(tr('The file is not valid JSON'), 'warning'); }
    });
  }
  private async save() {
    if (!this.draft?.graph) { this.host.toast(tr('Choose the workflow file'), 'warning'); return; }
    const { file, ...body } = this.draft;
    const r = await call(this.host, 'POST', '/flows', body);
    if (r.ok) { this.draft = null; this.host.toast(tr('Workflow uploaded'), 'success'); this.load(); }
  }
  render() {
    if (this.items === undefined) return html`<hxk-state kind="loading"></hxk-state>`;
    if (this.items === null) return html`<hxk-state kind="offline" @retry=${() => this.load()}></hxk-state>`;
    return html`<div class="page">
      <div class="between"><h1>${tr("Workflows")}</h1><hxk-button variant="primary" icon="upload" @click=${() => { this.draft = { purpose: 'generic', default: true }; }}>${tr("Upload")}</hxk-button></div>
      <div class="small muted">${tr("In ComfyUI: Save → API Format. One workflow per kind of image; the text, the size and the seed go in the usual nodes (I find them myself).")}</div>
      ${this.draft ? html`<div class="card col">
        <input type="file" accept=".json,application/json" @change=${(e: any) => this.pick(e)}>
        <div class="row wrap"><hxk-field label=${tr("Name")} .value=${this.draft.name || ''} @change=${(e: any) => { this.draft = { ...this.draft, name: e.detail }; }}></hxk-field>
          <hxk-field label=${tr("Image type")} type="enum" .options=${Object.entries(this.purposes).map(([value, label]) => ({ value, label }))} .value=${this.draft.purpose} @change=${(e: any) => { this.draft = { ...this.draft, purpose: e.detail }; }}></hxk-field>
          <hxk-field label=${tr("Default for this type")} type="bool" .value=${this.draft.default} @change=${(e: any) => { this.draft = { ...this.draft, default: e.detail }; }}></hxk-field></div>
        <div class="row"><hxk-button variant="primary" @click=${() => this.save()}>${tr("Save")}</hxk-button><hxk-button variant="ghost" @click=${() => { this.draft = null; }}>${tr("Cancel")}</hxk-button></div></div>` : nothing}
      <div class="card">${this.items.length ? this.items.map(f => html`<div class="flow"><div class="grow"><div>${f.name}${f.default ? html` <hxk-badge tone="accent">${tr("default")}</hxk-badge>` : nothing}</div>
          <div class="small muted">${this.purposes[f.purpose] || f.purpose} · ${Object.keys(f.inputs || {}).join(', ')}</div></div>
          <hxk-button size="sm" variant="ghost" icon="trash" @click=${async () => { if (await this.host.confirm(tr('Delete the workflow?'), f.name, { label: tr('Delete'), danger: true })) { await call(this.host, 'DELETE', `/flows/${f.id}`); this.load(); } }}></hxk-button></div>`)
        : html`<hxk-state kind="empty" text=${tr("No workflow uploaded.")}></hxk-state>`}</div>
    </div>`;
  }
}

definePlugin({ 'apollo-images': ApolloImages, 'apollo-job': ApolloJob, 'apollo-flows': ApolloFlows });
