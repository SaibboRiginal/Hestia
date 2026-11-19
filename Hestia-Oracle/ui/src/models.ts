/**
 * <oracle-models> — Brain tab «Models» (dossier 2026-10-19-oracle-blocks §A-C): named providers (keys stay in
 * .env as ORACLE_KEY_<NAME>), reusable chains of provider/model steps (order = fallback, quota state per step),
 * every use case declared by a module → chain / mode / thinking. Saves through Themis (PUT /api/ui/models/<part>).
 */
import { HestiaElement, html, css, nothing, tr } from '@hestia/webui-sdk';
import { API } from './util';

type Opt = { value: string; label: string };
/** «at 14:05» today, «on 19/11 at 09:00» another day. */
function when(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  const time = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  return d.toDateString() === new Date().toDateString() ? tr('at {0}', time)
    : tr('on {0} at {1}', d.toLocaleDateString([], { day: '2-digit', month: '2-digit' }), time);
}

const THINKING: Opt[] = [{ value: '', label: tr('As suggested') }, { value: 'auto', label: tr('Automatic') },
  { value: 'true', label: tr('Yes') }, { value: 'false', label: 'No' }];

function clone<T>(v: T): T { return JSON.parse(JSON.stringify(v ?? {})); }

function slug(s: string): string {
  return s.trim().toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '');
}

export class OracleModels extends HestiaElement {
  static properties = { ...HestiaElement.properties, data: { state: true }, error: { state: true }, providers: { state: true },
                        chains: { state: true }, overrides: { state: true }, dirty: { state: true }, saving: { state: true },
                        models: { state: true }, advanced: { state: true } };
  declare data: any; declare error: string; declare providers: Record<string, any>; declare chains: Record<string, any>;
  declare overrides: Record<string, any>; declare dirty: Record<string, boolean>; declare saving: string;
  declare models: Record<string, string[]>; declare advanced: boolean;

  static styles = [...HestiaElement.styles, css`
    .section { display: flex; flex-direction: column; gap: 12px; margin-top: 16px; }
    .section h2 { margin: 0; font-size: 16px; }
    .hint { font-size: 12.5px; color: var(--text-3); }
    .grid2 { display: grid; gap: 10px; grid-template-columns: repeat(auto-fit, minmax(min(100%, 200px), 1fr)); }
    .uc { display: grid; grid-template-columns: minmax(0, 1.3fr) repeat(var(--cols, 1), minmax(0, 1fr)); gap: 8px; align-items: end;
      padding: 8px 0; border-top: 1px solid var(--border); }
    .uc:first-of-type { border-top: 0; }
    .state { font-size: 12px; display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
    .key { font-family: var(--font-mono, monospace); font-size: 12px; }
    .actions { display: flex; gap: 8px; justify-content: flex-end; flex-wrap: wrap; }
    @media (max-width: 560px) { .uc { grid-template-columns: 1fr 1fr; } }
  `];

  constructor() {
    super(); this.data = null; this.error = ''; this.providers = {}; this.chains = {}; this.overrides = {};
    this.dirty = {}; this.saving = ''; this.models = {}; this.advanced = false;
  }

  connectedCallback() {
    super.connectedCallback();
    this.load();
    this.onHost('refresh', () => { if (!Object.values(this.dirty).some(Boolean)) this.load(); });
  }

  async load() {
    const r = await this.host.api('GET', `${API}/models`);
    if (!r.ok) { this.error = r.error || tr('Not available right now'); return; }
    this.error = '';
    this.data = r.data;
    const provs: Record<string, any> = {};
    for (const p of r.data.providers || []) provs[p.name] = { type: p.type, label: p.label || '', url: p.url || '' };
    this.providers = provs;
    const chains: Record<string, any> = {};
    for (const [name, c] of Object.entries<any>(r.data.chains || {}))
      chains[name] = { label: c.label, steps: c.steps.map((s: any) => ({ provider: s.provider, model: s.model, ...(s.thinking ? { thinking: s.thinking } : {}) })) };
    this.chains = chains;
    this.overrides = clone(r.data.overrides || {});
    this.dirty = {};
  }

  private touch(part: string) { this.dirty = { ...this.dirty, [part]: true }; this.requestUpdate(); }

  private async save(part: 'providers' | 'chains' | 'usecases') {
    const value = part === 'providers' ? this.providers : part === 'chains' ? this.chains : this.overrides;
    this.saving = part;
    const r = await this.host.api('PUT', `${API}/models/${part}`, { body: { value } });
    this.saving = '';
    if (!r.ok) { this.host.toast(r.error || tr('Not saved'), 'danger'); return; }
    this.host.toast(tr('Saved'), 'success');
    this.dirty = { ...this.dirty, [part]: false };
    window.setTimeout(() => this.load(), 800);   // Themis pushes the new value back to Oracle
  }

  /** Models of *provider* that fit *use* (chat | embedding): the chain editor shows only those. */
  private async loadModels(provider: string, use: string) {
    const key = `${provider}|${use}`;
    if (!provider || this.models[key]) return;
    if (this.asking.has(key)) return;
    this.asking.add(key);                                   // no second request while this one runs
    const r = await this.host.api('GET', `${API}/models/list`, { query: { provider, use } });
    this.asking.delete(key);
    this.models = { ...this.models, [key]: r.ok ? r.data.models || [] : [] };
  }

  private asking = new Set<string>();

  private useOf(chain: string): string { return this.data?.chains?.[chain]?.use || 'chat'; }

  /** {provider: options} of the models listed for this chain's use; undefined = not loaded yet. */
  private choicesFor(chain: string): Record<string, { value: string; label: string }[] | undefined> {
    const use = this.useOf(chain);
    const out: Record<string, any> = {};
    for (const p of Object.keys(this.providers)) {
      const list = this.models[`${p}|${use}`];
      if (list) out[p] = list.map(m => ({ value: m, label: m }));
    }
    return out;
  }

  /** One sentence per step that is not usable now (or «available again at …»). */
  private statesFor(chain: string) {
    const live = this.data?.chains?.[chain]?.steps || [];
    return (this.chains[chain]?.steps || []).map((s: any) => {
      const l = live.find((x: any) => x.provider === s.provider && x.model === s.model);
      if (!l) return null;
      if (l.exhausted_until) return { tone: 'warning', text: tr('Limit reached: available again {0}', when(l.exhausted_until)), retry: true };
      if (!l.available) return { tone: 'neutral', text: tr('Skipped: {0}', l.detail) };
      return null;
    });
  }

  private async retry(provider: string, model: string) {
    await this.host.api('POST', `${API}/models/quota/reset`, { query: { provider, model } });
    this.load();
  }

  // ── providers ──────────────────────────────────────────────────────────
  private providerCard(name: string) {
    const p = this.providers[name];
    const live = (this.data?.providers || []).find((x: any) => x.name === name) || {};
    const set = (k: string, v: any) => { this.providers = { ...this.providers, [name]: { ...p, [k]: v } }; this.touch('providers'); };
    return html`<hxk-card heading=${p.label || name} subtitle=${name}>
      <hxk-button slot="actions" variant="ghost" icon="trash" @click=${() => this.removeProvider(name)}>${tr("alt::Remove")}</hxk-button>
      <div class="grid2">
        <hxk-field label=${tr("Visible name")} .value=${p.label} @change=${(e: CustomEvent) => set('label', e.detail)}></hxk-field>
        <hxk-field type="enum" label=${tr("Standard")} .options=${this.data?.types || []} .value=${p.type}
          @change=${(e: CustomEvent) => set('type', e.detail)}></hxk-field>
        <hxk-field label=${tr("Address")} .value=${p.url} placeholder=${p.type === 'ollama' ? tr('from OLLAMA_URL') : tr('default')}
          @change=${(e: CustomEvent) => set('url', e.detail)}></hxk-field>
      </div>
      <div class="state" style="margin-top:8px">
        <hxk-badge tone=${live.available ? 'success' : 'warning'}>${live.available ? tr('m::ready') : tr('not ready')}</hxk-badge>
        ${live.needs_key || live.key_set ? html`<span>${tr("Key in .env:")} <span class="key">${live.key_env}</span> ${live.key_set ? html`<hxk-icon name="check" size=${13} tone="success" title=${tr("set")}></hxk-icon>` : tr('— missing')}</span>` : nothing}
        ${!live.available && live.detail ? html`<span class="muted">${live.detail}</span>` : nothing}
      </div>
    </hxk-card>`;
  }

  private async addProvider() {
    const raw = window.prompt(tr('Name of the new provider (e.g. openrouter). The key goes in .env as ORACLE_KEY_<NAME>.'));
    const name = slug(raw || '');
    if (!name || this.providers[name]) return;
    this.providers = { ...this.providers, [name]: { type: 'openai', label: raw!.trim(), url: '' } };
    this.touch('providers');
  }

  private async removeProvider(name: string) {
    const used = Object.entries<any>(this.chains).filter(([, c]) => c.steps.some((s: any) => s.provider === name)).map(([n]) => n);
    const text = used.length ? tr("It's used by the chains {0}: those steps will be skipped.", used.join(', ')) : tr('It\'s not used by any chain.');
    if (!(await this.host.confirm(tr("Remove {0}?", name), text, { label: tr('alt::Remove'), danger: true }))) return;
    const next = { ...this.providers }; delete next[name];
    this.providers = next; this.touch('providers');
  }

  // ── chains ─────────────────────────────────────────────────────────────
  private setSteps(chain: string, steps: any[]) {
    this.chains = { ...this.chains, [chain]: { ...this.chains[chain], steps } };
    this.touch('chains');
  }

  private chainCard(name: string) {
    const c = this.chains[name];
    const provOpts = Object.entries<any>(this.providers).map(([n, p]) => ({ value: n, label: p.label || n }));
    const embedding = this.useOf(name) === 'embedding';
    return html`<hxk-card heading=${c.label || name} subtitle=${embedding ? tr('For the memory: finding notes and documents again') : ''}>
      <hxk-button slot="actions" variant="ghost" icon="trash" @click=${() => this.removeChain(name)}>${tr("Delete")}</hxk-button>
      <hxk-chain .steps=${c.steps} .providers=${provOpts} .choices=${this.choicesFor(name)} .states=${this.statesFor(name)}
        @need-choices=${(e: CustomEvent) => this.loadModels(e.detail, this.useOf(name))}
        @steps-change=${(e: CustomEvent) => this.setSteps(name, e.detail)}
        @retry=${(e: CustomEvent) => this.retry(e.detail.step.provider, e.detail.step.model)}></hxk-chain>
      ${this.advanced ? html`<hxk-field label=${tr("Visible name")} .value=${c.label}
        @change=${(e: CustomEvent) => { this.chains = { ...this.chains, [name]: { ...c, label: e.detail } }; this.touch('chains'); }}></hxk-field>` : nothing}
    </hxk-card>`;
  }

  private addChain() {
    const raw = window.prompt(tr('Name of the new chain (e.g. cheap)'));
    const name = slug(raw || '');
    if (!name || this.chains[name]) return;
    this.chains = { ...this.chains, [name]: { label: raw!.trim(), steps: [] } };
    this.touch('chains');
  }

  private async removeChain(name: string) {
    const users = (this.data?.usecases || []).filter((u: any) => u.effective_chain === name).map((u: any) => u.label);
    const text = users.length ? tr("Used by: {0}. They'll go back to the «General use» chain.", users.join(', ')) : tr('No use picks it.');
    if (!(await this.host.confirm(tr("Delete the chain {0}?", name), text, { label: tr('Delete'), danger: true }))) return;
    const next = { ...this.chains }; delete next[name];
    this.chains = next; this.touch('chains');
  }

  // ── use cases ──────────────────────────────────────────────────────────
  private ucRow(u: any) {
    const o = this.overrides[u.id] || {};
    const chainOpts: Opt[] = [{ value: '', label: tr("Suggested ({0})", u.chain || 'general') },
      ...Object.entries<any>(this.chains).map(([n, c]) => ({ value: n, label: c.label || n }))];
    const modeOpts: Opt[] = [{ value: '', label: tr("Suggested ({0})", u.mode || 'follow') }, ...(this.data?.modes || [])];
    const set = (k: string, v: string) => {
      const next = { ...o, [k]: v }; if (!v) delete next[k];
      const all: Record<string, any> = { ...this.overrides, [u.id]: next }; if (!Object.keys(next).length) delete all[u.id];
      this.overrides = all; this.touch('usecases');
    };
    return html`<div class="uc" style=${this.advanced ? '--cols:3' : '--cols:1'}>
      <div><div class="truncate"><b>${u.label}</b>${u.undeclared ? html` <hxk-badge tone="warning">${tr("not declared")}</hxk-badge>` : nothing}</div>
        <div class="small muted truncate" title=${u.help || ''}>${u.help || (this.advanced ? u.id : '')}</div></div>
      <hxk-field type="enum" label=${tr("Chain")} .options=${chainOpts} .value=${o.chain || ''} @change=${(e: CustomEvent) => set('chain', e.detail)}></hxk-field>
      ${this.advanced ? html`<hxk-field type="enum" label=${tr("alt::Mode")} .options=${modeOpts} .value=${o.mode || ''} @change=${(e: CustomEvent) => set('mode', e.detail)}></hxk-field>
      <hxk-field type="enum" label=${tr("Reasoning")} .options=${THINKING} .value=${o.thinking || ''} @change=${(e: CustomEvent) => set('thinking', e.detail)}></hxk-field>` : nothing}
    </div>`;
  }

  private usecases() {
    const groups: Record<string, any[]> = {};
    for (const u of this.data?.usecases || []) (groups[u.module || tr('other')] ||= []).push(u);
    return Object.entries(groups).map(([mod, rows]) => html`<hxk-card heading=${mod}>${rows.map(u => this.ucRow(u))}</hxk-card>`);
  }

  private saveBar(part: 'providers' | 'chains' | 'usecases') {
    if (!this.dirty[part]) return nothing;
    return html`<div class="actions"><hxk-button variant="ghost" @click=${() => this.load()}>${tr("Cancel")}</hxk-button>
      <hxk-button variant="primary" icon="check" ?loading=${this.saving === part} @click=${() => this.save(part)}>${tr("Save")}</hxk-button></div>`;
  }

  render() {
    if (this.error) return html`<hxk-state kind="error" text=${this.error} @retry=${() => this.load()}></hxk-state>`;
    if (!this.data) return html`<hxk-state kind="loading"></hxk-state>`;
    return html`
      <div class="actions"><hxk-field type="bool" label=${tr("Show the advanced settings")} .value=${this.advanced}
        @change=${(e: CustomEvent) => { this.advanced = !!e.detail; }}></hxk-field></div>
      <div class="section"><h2>${tr("What each function uses")}</h2>
        <div class="hint">${tr("Each function has a suggested list of models; change it only if you want another one.")}</div>
        ${this.usecases()}${this.saveBar('usecases')}</div>
      <div class="section"><h2>${tr("Model chains")}</h2>
        <div class="hint">${tr("The first model of a list is used; when it is not available (or its limit is reached) the next one answers.")}</div>
        ${Object.keys(this.chains).map(n => this.chainCard(n))}
        <div class="actions"><hxk-button variant="ghost" icon="plus" @click=${() => this.addChain()}>${tr("New chain")}</hxk-button></div>
        ${this.saveBar('chains')}</div>
      <div class="section"><h2>${tr("Providers")}</h2>
        <div class="hint">${tr("Where the models are. The key is not written here: it goes in the .env file as ORACLE_KEY_<NAME>.")}</div>
        ${Object.keys(this.providers).map(n => this.providerCard(n))}
        <div class="actions"><hxk-button variant="ghost" icon="plus" @click=${() => this.addProvider()}>${tr("New provider")}</hxk-button></div>
        ${this.saveBar('providers')}</div>`;
  }
}
