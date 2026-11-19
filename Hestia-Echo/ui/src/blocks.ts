/**
 * <echo-blocks> — Voice, tab «Engines» (dossier docs/work/2026-10-20-voice-module §5): named providers (keys stay in
 * .env as ECHO_KEY_<NAME>), chains of listen or voice (order = fallback, quota state per step), every use declared by
 * a module → chain / mode. Built like Oracle's «Models». Saves through Themis (PUT /api/voice/blocks/<part>).
 */
import { HestiaElement, html, css, nothing, tr } from '@hestia/webui-sdk';
import { API, DIRECTIONS, STATES, clone, slug } from './util';

type Opt = { value: string; label: string };
type Part = 'providers' | 'chains' | 'usecases';
const MODES: Opt[] = [{ value: 'internal', label: tr('Internal') }, { value: 'external', label: tr('External') }];

export class EchoBlocks extends HestiaElement {
  static properties = { ...HestiaElement.properties, live: { state: true }, error: { state: true }, providers: { state: true },
                        chains: { state: true }, overrides: { state: true }, dirty: { state: true }, saving: { state: true } };
  declare live: any; declare error: string; declare providers: Record<string, any>; declare chains: Record<string, any>;
  declare overrides: Record<string, any>; declare dirty: Record<string, boolean>; declare saving: string;

  static styles = [...HestiaElement.styles, css`
    .section { display: flex; flex-direction: column; gap: 12px; margin-top: 16px; }
    .section:first-child { margin-top: 0; }
    .section h2 { margin: 0; font-size: 16px; }
    .hint { font-size: 12.5px; color: var(--text-3); }
    .grid2 { display: grid; gap: 10px; grid-template-columns: repeat(auto-fit, minmax(min(100%, 200px), 1fr)); }
    .state { grid-column: 2 / -1; font-size: 12px; display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
    .uc { display: grid; grid-template-columns: minmax(0, 1.4fr) repeat(2, minmax(0, 1fr)); gap: 8px; align-items: end;
      padding: 8px 0; border-top: 1px solid var(--border); }
    .uc:first-of-type { border-top: 0; }
    .key { font-family: var(--font-mono, monospace); font-size: 12px; }
    .actions { display: flex; gap: 8px; justify-content: flex-end; flex-wrap: wrap; }
    @media (max-width: 560px) { .uc { grid-template-columns: 1fr 1fr; } .uc > :first-child { grid-column: 1 / -1; } }
  `];

  constructor() {
    super(); this.live = null; this.error = ''; this.providers = {}; this.chains = {}; this.overrides = {};
    this.dirty = {}; this.saving = '';
  }

  connectedCallback() {
    super.connectedCallback();
    this.load();
    this.onHost('refresh', () => { if (!Object.values(this.dirty).some(Boolean)) this.load(); });
  }

  async load() {
    const [p, c, u, s] = await Promise.all([this.host.api('GET', `${API}/providers`), this.host.api('GET', `${API}/chains`),
      this.host.api('GET', `${API}/usecases`), this.host.api('GET', `${API}/standards`)]);
    if (!p.ok) { this.error = p.error || tr('Not reachable'); return; }
    this.error = '';
    this.live = { providers: p.data.items || [], chains: c.ok ? c.data.items || {} : {}, usecases: u.ok ? u.data.items || [] : [],
                  standards: s.ok ? s.data.items || [] : [] };
    const provs: Record<string, any> = {};
    for (const x of this.live.providers) provs[x.name] = { type: x.type, label: x.label, url: x.url || '', options: x.options || {} };
    this.providers = provs;
    const chains: Record<string, any> = {};
    for (const [n, ch] of Object.entries<any>(this.live.chains))
      chains[n] = { label: ch.label, direction: ch.direction,
                    steps: ch.steps.map((st: any) => ({ provider: st.provider, model: st.model || '', voice: st.voice || '', options: st.options || {} })) };
    this.chains = chains;
    const ov: Record<string, any> = {};
    for (const x of this.live.usecases) if (x.overridden) ov[x.id] = { ...(x.chain !== x.suggested_chain ? { chain: x.chain } : {}), ...(x.mode !== 'follow' ? { mode: x.mode } : {}) };
    this.overrides = clone(ov);
    this.dirty = {};
  }

  private touch(part: Part) { this.dirty = { ...this.dirty, [part]: true }; this.requestUpdate(); }

  private async save(part: Part) {
    const value = part === 'providers' ? this.providers : part === 'chains' ? this.chains : this.overrides;
    this.saving = part;
    const r = await this.host.api('PUT', `${API}/blocks/${part}`, { body: { value } });
    this.saving = '';
    if (!r.ok) { this.host.toast(r.error || tr('Not saved'), 'danger'); return; }
    this.host.toast(tr('Saved'), 'success');
    this.dirty = { ...this.dirty, [part]: false };
    window.setTimeout(() => this.load(), 800);
  }

  private std(type: string) { return (this.live?.standards || []).find((s: any) => s.id === type) || {}; }
  private liveProvider(name: string) { return (this.live?.providers || []).find((x: any) => x.name === name) || {}; }

  // ── providers ──────────────────────────────────────────────────────────
  private providerCard(name: string) {
    const p = this.providers[name];
    const live = this.liveProvider(name);
    const std = this.std(p.type);
    const set = (k: string, v: any) => { this.providers = { ...this.providers, [name]: { ...p, [k]: v } }; this.touch('providers'); };
    const setOpt = (k: string, v: any) => set('options', { ...p.options, [k]: v });
    const st = STATES[live.state] || { label: live.state || '–', tone: 'neutral' };
    const types: Opt[] = (this.live?.standards || []).map((s: any) => ({ value: s.id, label: s.label }));
    return html`<hxk-card heading=${p.label || name} subtitle=${`${name} · ${(std.directions || []).join(' · ')}`}>
      <hxk-button slot="actions" variant="ghost" icon="trash" @click=${() => this.removeProvider(name)}>${tr("alt::Remove")}</hxk-button>
      <div class="grid2">
        <hxk-field label=${tr("Visible name")} .value=${p.label} @change=${(e: CustomEvent) => set('label', e.detail)}></hxk-field>
        <hxk-field type="enum" label=${tr("Standard")} .options=${types} .value=${p.type} @change=${(e: CustomEvent) => set('type', e.detail)}></hxk-field>
        ${std.needs_url || std.default_url ? html`<hxk-field label=${tr("Address")} .value=${p.url} placeholder=${std.default_url || ''}
          @change=${(e: CustomEvent) => set('url', e.detail)}></hxk-field>` : nothing}
        ${(std.options || []).map((o: any) => html`<hxk-field type=${o.type === 'string' ? 'text' : o.type} label=${o.label}
          .options=${o.options || []} help=${o.help || ''} .value=${p.options?.[o.key] ?? o.default}
          @change=${(e: CustomEvent) => setOpt(o.key, e.detail)}></hxk-field>`)}
      </div>
      <div class="state" style="margin-top:8px">
        <hxk-badge tone=${st.tone}>${st.label}</hxk-badge>
        ${live.needs_key ? html`<span>${tr("Key in .env:")} <span class="key">${live.key_env}</span>
          ${live.key ? html`<hxk-icon name="check" size=${13} tone="success" title=${tr("set")}></hxk-icon>` : tr(' — missing')}</span>` : nothing}
        ${Object.keys(live.quota || {}).length ? html`<hxk-badge tone="warning">${tr("no quota")}</hxk-badge>
          <hxk-button variant="ghost" @click=${() => this.retry(name)}>${tr("Try again now")}</hxk-button>` : nothing}
      </div>
    </hxk-card>`;
  }

  private async retry(name: string) {
    await this.host.api('POST', `${API}/providers/${name}/retry`);
    this.load();
  }

  private addProvider() {
    const raw = window.prompt(tr('Name of the new provider (e.g. deepgram). The key goes in .env as ECHO_KEY_<NAME>.'));
    const name = slug(raw || '');
    if (!name || this.providers[name]) return;
    this.providers = { ...this.providers, [name]: { type: 'openai', label: raw!.trim(), url: '', options: {} } };
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
  /** The engines (and their models or voices) that fit this chain's direction, for the one chain editor. */
  private chainProps(chain: string) {
    const c = this.chains[chain];
    const speaking = c.direction === 'voice';
    const providers = Object.entries<any>(this.providers)
      .filter(([, p]) => (this.std(p.type).directions || []).includes(c.direction))
      .map(([n, p]) => ({ value: n, label: p.label || n }));
    const choices: Record<string, any> = {};
    for (const { value } of providers) {
      const lp = this.liveProvider(value);
      choices[value] = ((speaking ? lp.voices : lp.models) || []).map((m: any) => ({ value: m.id, label: m.label || m.id }));
    }
    const live = this.live?.chains?.[chain]?.steps || [];
    const states = c.steps.map((_: any, i: number) => {
      const l = live[i];
      const st = l ? STATES[l.state] : null;
      if (!l || l.state === 'ready' || !st) return null;
      return { tone: st.tone, text: `${st.label}${l.until ? tr(" until {0}", String(l.until).slice(11, 16)) : ''}`, retry: l.state === 'quota' };
    });
    return { providers, choices, states, field: speaking ? 'voice' : 'model' };
  }

  private setSteps(chain: string, steps: any[]) {
    this.chains = { ...this.chains, [chain]: { ...this.chains[chain], steps } };
    this.touch('chains');
  }

  private chainCard(name: string) {
    const c = this.chains[name];
    const cp = this.chainProps(name);
    return html`<hxk-card heading=${c.label || name} subtitle=${`${name} · ${c.direction === 'voice' ? tr('voice') : tr('listening')}`}>
      <hxk-button slot="actions" variant="ghost" icon="trash" @click=${() => this.removeChain(name)}>${tr("Delete")}</hxk-button>
      <hxk-field label=${tr("Visible name")} .value=${c.label}
        @change=${(e: CustomEvent) => { this.chains = { ...this.chains, [name]: { ...c, label: e.detail } }; this.touch('chains'); }}></hxk-field>
      <hxk-chain .steps=${c.steps} .providers=${cp.providers} .choices=${cp.choices} .states=${cp.states} field=${cp.field}
        pick-label=${cp.field === 'voice' ? tr('Voice') : tr('Model')} add-label=${tr('Add a step')}
        @steps-change=${(e: CustomEvent) => this.setSteps(name, e.detail.map((st: any) => ({ model: '', voice: '', options: {}, ...st })))}
        @retry=${(e: CustomEvent) => this.retry(e.detail.step.provider)}></hxk-chain>
    </hxk-card>`;
  }

  private addChain() {
    const raw = window.prompt(tr('Name of the new chain (e.g. warm-voice)'));
    const name = slug(raw || '');
    if (!name || this.chains[name]) return;
    const voice = window.confirm(tr('Is it a voice chain (text → voice)? Cancel = listening.'));
    this.chains = { ...this.chains, [name]: { label: raw!.trim(), direction: voice ? 'voice' : 'listen', steps: [] } };
    this.touch('chains');
  }

  private async removeChain(name: string) {
    const users = (this.live?.usecases || []).filter((u: any) => u.chain === name).map((u: any) => u.label);
    const text = users.length ? tr("Used by: {0}. They'll go back to the default chain.", users.join(', ')) : tr('No use picks it.');
    if (!(await this.host.confirm(tr("Delete the chain {0}?", name), text, { label: tr('Delete'), danger: true }))) return;
    const next = { ...this.chains }; delete next[name];
    this.chains = next; this.touch('chains');
  }

  // ── use cases ──────────────────────────────────────────────────────────
  private ucRow(u: any) {
    const o = this.overrides[u.id] || {};
    const chainOpts: Opt[] = [{ value: '', label: tr("Suggested ({0})", u.suggested_chain || u.direction) },
      ...Object.entries<any>(this.chains).filter(([, c]) => c.direction === u.direction).map(([n, c]) => ({ value: n, label: c.label || n }))];
    const modeOpts: Opt[] = [{ value: '', label: tr('Like the whole item') }, ...MODES];
    const set = (k: string, v: string) => {
      const next = { ...o, [k]: v }; if (!v) delete next[k];
      const all: Record<string, any> = { ...this.overrides, [u.id]: next }; if (!Object.keys(next).length) delete all[u.id];
      this.overrides = all; this.touch('usecases');
    };
    return html`<div class="uc">
      <div><div class="truncate"><b>${u.label}</b>${u.undeclared ? html` <hxk-badge tone="warning">${tr("not declared")}</hxk-badge>` : nothing}</div>
        <div class="small muted truncate" title=${u.help || ''}>${u.direction} · ${u.id}${u.help ? ` · ${u.help}` : ''}</div></div>
      <hxk-field type="enum" label=${tr("Chain")} .options=${chainOpts} .value=${o.chain || ''} @change=${(e: CustomEvent) => set('chain', e.detail)}></hxk-field>
      <hxk-field type="enum" label=${tr("alt::Mode")} .options=${modeOpts} .value=${o.mode && o.mode !== 'follow' ? o.mode : ''}
        @change=${(e: CustomEvent) => set('mode', e.detail)}></hxk-field>
    </div>`;
  }

  private usecases() {
    const groups: Record<string, any[]> = {};
    for (const u of this.live?.usecases || []) (groups[u.module || tr('other')] ||= []).push(u);
    return Object.entries(groups).map(([mod, rows]) => html`<hxk-card heading=${mod}>${rows.map(u => this.ucRow(u))}</hxk-card>`);
  }

  private saveBar(part: Part) {
    if (!this.dirty[part]) return nothing;
    return html`<div class="actions"><hxk-button variant="ghost" @click=${() => this.load()}>${tr("Cancel")}</hxk-button>
      <hxk-button variant="primary" icon="check" ?loading=${this.saving === part} @click=${() => this.save(part)}>${tr("Save")}</hxk-button></div>`;
  }

  render() {
    if (this.error) return html`<hxk-state kind="error" text=${this.error} @retry=${() => this.load()}></hxk-state>`;
    if (!this.live) return html`<hxk-state kind="loading"></hxk-state>`;
    const byDir = (d: string) => Object.keys(this.chains).filter(n => this.chains[n].direction === d);
    return html`
      <div class="section"><h2>${tr("Module uses")}</h2>
        <div class="hint">${tr("Each module declares where it listens or speaks; here you choose the chain and the mode (Internal = chains of this page, External = the engine chosen in Settings does everything). Empty = the suggested choice.")}</div>
        ${this.usecases()}${this.saveBar('usecases')}</div>
      ${DIRECTIONS.map(d => html`<div class="section"><h2>${tr("Chains of")} ${d.value}</h2>
        <div class="hint">${d.label}${tr(". The first ready step is used; if an engine fails or its quota ends I move to the next.")}</div>
        ${byDir(d.value).map(n => this.chainCard(n))}</div>`)}
      <div class="actions"><hxk-button variant="ghost" icon="plus" @click=${() => this.addChain()}>${tr("New chain")}</hxk-button></div>
      ${this.saveBar('chains')}
      <div class="section"><h2>${tr("Providers")}</h2>
        <div class="hint">${tr("Where the voice engines are. The key is not written here: it goes in the .env file as ECHO_KEY_<NAME>.")}</div>
        ${Object.keys(this.providers).map(n => this.providerCard(n))}
        <div class="actions"><hxk-button variant="ghost" icon="plus" @click=${() => this.addProvider()}>${tr("New provider")}</hxk-button></div>
        ${this.saveBar('providers')}</div>`;
  }
}
