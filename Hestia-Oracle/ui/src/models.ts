/**
 * <oracle-models> — Cervello tab «Modelli» (dossier 2026-10-19-oracle-a-blocchi §A-C): named providers (keys stay in
 * .env as ORACLE_KEY_<NAME>), reusable chains of provider/model steps (order = fallback, quota state per step),
 * every use case declared by a module → chain / mode / thinking. Saves through Themis (PUT /api/ui/models/<part>).
 */
import { HestiaElement, html, css, nothing } from '@hestia/webui-sdk';
import { API } from './util';

type Opt = { value: string; label: string };
const THINKING: Opt[] = [{ value: '', label: 'Come suggerito' }, { value: 'auto', label: 'Automatico' },
  { value: 'true', label: 'Sì' }, { value: 'false', label: 'No' }];

function clone<T>(v: T): T { return JSON.parse(JSON.stringify(v ?? {})); }

function slug(s: string): string {
  return s.trim().toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '');
}

export class OracleModels extends HestiaElement {
  static properties = { ...HestiaElement.properties, data: { state: true }, error: { state: true }, providers: { state: true },
                        chains: { state: true }, overrides: { state: true }, dirty: { state: true }, saving: { state: true },
                        models: { state: true } };
  declare data: any; declare error: string; declare providers: Record<string, any>; declare chains: Record<string, any>;
  declare overrides: Record<string, any>; declare dirty: Record<string, boolean>; declare saving: string;
  declare models: Record<string, string[]>;

  static styles = [...HestiaElement.styles, css`
    .section { display: flex; flex-direction: column; gap: 12px; margin-top: 16px; }
    .section h2 { margin: 0; font-size: 16px; }
    .hint { font-size: 12.5px; color: var(--text-3); }
    .grid2 { display: grid; gap: 10px; grid-template-columns: repeat(auto-fit, minmax(min(100%, 200px), 1fr)); }
    .step { display: grid; grid-template-columns: 24px minmax(0, 1fr) minmax(0, 1.4fr) auto; gap: 8px; align-items: end;
      padding: 8px 0; border-top: 1px solid var(--border); }
    .step:first-of-type { border-top: 0; }
    .idx { font-variant-numeric: tabular-nums; color: var(--text-3); padding-bottom: 8px; }
    .tools { display: flex; gap: 2px; }
    .state { grid-column: 2 / -1; font-size: 12px; display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
    .uc { display: grid; grid-template-columns: minmax(0, 1.3fr) repeat(3, minmax(0, 1fr)); gap: 8px; align-items: end;
      padding: 8px 0; border-top: 1px solid var(--border); }
    .uc:first-of-type { border-top: 0; }
    .key { font-family: var(--font-mono, monospace); font-size: 12px; }
    .actions { display: flex; gap: 8px; justify-content: flex-end; flex-wrap: wrap; }
    @media (max-width: 560px) { .uc { grid-template-columns: 1fr 1fr; } .step { grid-template-columns: 20px 1fr; }
      .step > :nth-child(3), .step > .tools { grid-column: 2; } }
  `];

  constructor() {
    super(); this.data = null; this.error = ''; this.providers = {}; this.chains = {}; this.overrides = {};
    this.dirty = {}; this.saving = ''; this.models = {};
  }

  connectedCallback() {
    super.connectedCallback();
    this.load();
    this.onHost('refresh', () => { if (!Object.values(this.dirty).some(Boolean)) this.load(); });
  }

  async load() {
    const r = await this.host.api('GET', `${API}/models`);
    if (!r.ok) { this.error = r.error || 'Oracle non raggiungibile'; return; }
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
    if (!r.ok) { this.host.toast(r.error || 'Non salvato', 'danger'); return; }
    this.host.toast('Salvato', 'success');
    this.dirty = { ...this.dirty, [part]: false };
    window.setTimeout(() => this.load(), 800);   // Themis pushes the new value back to Oracle
  }

  private async loadModels(provider: string) {
    if (!provider || this.models[provider]) return;
    const r = await this.host.api('GET', `${API}/models/list`, { query: { provider } });
    this.models = { ...this.models, [provider]: r.ok ? r.data.models || [] : [] };
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
      <hxk-button slot="actions" variant="ghost" icon="trash" @click=${() => this.removeProvider(name)}>Rimuovi</hxk-button>
      <div class="grid2">
        <hxk-field label="Nome visibile" .value=${p.label} @change=${(e: CustomEvent) => set('label', e.detail)}></hxk-field>
        <hxk-field type="enum" label="Standard" .options=${this.data?.types || []} .value=${p.type}
          @change=${(e: CustomEvent) => set('type', e.detail)}></hxk-field>
        <hxk-field label="Indirizzo" .value=${p.url} placeholder=${p.type === 'ollama' ? 'da OLLAMA_URL' : 'predefinito'}
          @change=${(e: CustomEvent) => set('url', e.detail)}></hxk-field>
      </div>
      <div class="state" style="margin-top:8px">
        <hxk-badge tone=${live.available ? 'success' : 'warning'}>${live.available ? 'pronto' : 'non pronto'}</hxk-badge>
        ${live.needs_key || live.key_set ? html`<span>Chiave in .env: <span class="key">${live.key_env}</span> ${live.key_set ? '✓' : '— manca'}</span>` : nothing}
        ${!live.available && live.detail ? html`<span class="muted">${live.detail}</span>` : nothing}
      </div>
    </hxk-card>`;
  }

  private async addProvider() {
    const raw = window.prompt('Nome del nuovo fornitore (es. openrouter). La chiave andrà in .env come ORACLE_KEY_<NOME>.');
    const name = slug(raw || '');
    if (!name || this.providers[name]) return;
    this.providers = { ...this.providers, [name]: { type: 'openai', label: raw!.trim(), url: '' } };
    this.touch('providers');
  }

  private async removeProvider(name: string) {
    const used = Object.entries<any>(this.chains).filter(([, c]) => c.steps.some((s: any) => s.provider === name)).map(([n]) => n);
    const text = used.length ? `È usato dalle catene ${used.join(', ')}: quei passi verranno saltati.` : 'Non è usato da nessuna catena.';
    if (!(await this.host.confirm(`Rimuovere ${name}?`, text, { label: 'Rimuovi', danger: true }))) return;
    const next = { ...this.providers }; delete next[name];
    this.providers = next; this.touch('providers');
  }

  // ── chains ─────────────────────────────────────────────────────────────
  private stepRow(chain: string, i: number, step: any) {
    const steps = this.chains[chain].steps as any[];
    const live = this.data?.chains?.[chain]?.steps?.find((s: any) => s.provider === step.provider && s.model === step.model);
    const provOpts: Opt[] = Object.entries<any>(this.providers).map(([n, p]) => ({ value: n, label: p.label || n }));
    const update = (patch: any) => { const next = steps.slice(); next[i] = { ...step, ...patch }; this.setSteps(chain, next); };
    const move = (d: number) => { const next = steps.slice(); const [s] = next.splice(i, 1); next.splice(i + d, 0, s); this.setSteps(chain, next); };
    const listId = `m-${chain}-${i}`;
    return html`<div class="step">
      <span class="idx">${i + 1}</span>
      <hxk-field type="enum" label="Fornitore" .options=${provOpts} .value=${step.provider}
        @change=${(e: CustomEvent) => update({ provider: e.detail })}></hxk-field>
      <div @focusin=${() => this.loadModels(step.provider)}>
        <label class="small muted">Modello</label>
        <input list=${listId} .value=${step.model} style="font:inherit;color:var(--text);background:var(--surface-2);border:1px solid var(--border-strong);border-radius:var(--radius-sm);padding:7px 10px;width:100%;box-sizing:border-box"
          @change=${(e: any) => update({ model: String(e.target.value).trim() })}>
        <datalist id=${listId}>${(this.models[step.provider] || []).map(m => html`<option value=${m}></option>`)}</datalist>
      </div>
      <div class="tools">
        <hxk-button variant="ghost" ?disabled=${i === 0} @click=${() => move(-1)} title="Prima">↑</hxk-button>
        <hxk-button variant="ghost" ?disabled=${i === steps.length - 1} @click=${() => move(1)} title="Dopo">↓</hxk-button>
        <hxk-button variant="ghost" icon="trash" @click=${() => this.setSteps(chain, steps.filter((_, j) => j !== i))} title="Togli"></hxk-button>
      </div>
      ${live && (!live.available || live.exhausted_until) ? html`<div class="state">
        ${live.exhausted_until ? html`<hxk-badge tone="warning">senza quota fino alle ${live.exhausted_until.slice(11, 16)}</hxk-badge>
          <hxk-button variant="ghost" @click=${() => this.retry(step.provider, step.model)}>Riprova adesso</hxk-button>` : nothing}
        ${!live.available ? html`<span class="muted">saltato: ${live.detail}</span>` : nothing}</div>` : nothing}
    </div>`;
  }

  private setSteps(chain: string, steps: any[]) {
    this.chains = { ...this.chains, [chain]: { ...this.chains[chain], steps } };
    this.touch('chains');
  }

  private chainCard(name: string) {
    const c = this.chains[name];
    const single = !!this.data?.chains?.[name]?.single_step;
    const firstProvider = Object.keys(this.providers)[0] || 'ollama';
    return html`<hxk-card heading=${c.label || name} subtitle=${single ? `${name} · un solo modello (i vettori devono restare confrontabili)` : name}>
      <hxk-button slot="actions" variant="ghost" icon="trash" @click=${() => this.removeChain(name)}>Elimina</hxk-button>
      <hxk-field label="Nome visibile" .value=${c.label}
        @change=${(e: CustomEvent) => { this.chains = { ...this.chains, [name]: { ...c, label: e.detail } }; this.touch('chains'); }}></hxk-field>
      ${c.steps.map((s: any, i: number) => this.stepRow(name, i, s))}
      ${single && c.steps.length >= 1 ? nothing : html`<hxk-button variant="ghost" icon="plus"
        @click=${() => this.setSteps(name, [...c.steps, { provider: firstProvider, model: '' }])}>Aggiungi un modello</hxk-button>`}
    </hxk-card>`;
  }

  private addChain() {
    const raw = window.prompt('Nome della nuova catena (es. economica)');
    const name = slug(raw || '');
    if (!name || this.chains[name]) return;
    this.chains = { ...this.chains, [name]: { label: raw!.trim(), steps: [] } };
    this.touch('chains');
  }

  private async removeChain(name: string) {
    const users = (this.data?.usecases || []).filter((u: any) => u.effective_chain === name).map((u: any) => u.label);
    const text = users.length ? `La usano: ${users.join(', ')}. Torneranno alla catena di «Uso generale».` : 'Nessun uso la sceglie.';
    if (!(await this.host.confirm(`Eliminare la catena ${name}?`, text, { label: 'Elimina', danger: true }))) return;
    const next = { ...this.chains }; delete next[name];
    this.chains = next; this.touch('chains');
  }

  // ── use cases ──────────────────────────────────────────────────────────
  private ucRow(u: any) {
    const o = this.overrides[u.id] || {};
    const chainOpts: Opt[] = [{ value: '', label: `Suggerita (${u.chain || 'generale'})` },
      ...Object.entries<any>(this.chains).map(([n, c]) => ({ value: n, label: c.label || n }))];
    const modeOpts: Opt[] = [{ value: '', label: `Suggerita (${u.mode || 'segui'})` }, ...(this.data?.modes || [])];
    const set = (k: string, v: string) => {
      const next = { ...o, [k]: v }; if (!v) delete next[k];
      const all: Record<string, any> = { ...this.overrides, [u.id]: next }; if (!Object.keys(next).length) delete all[u.id];
      this.overrides = all; this.touch('usecases');
    };
    return html`<div class="uc">
      <div><div class="truncate"><b>${u.label}</b>${u.undeclared ? html` <hxk-badge tone="warning">non dichiarato</hxk-badge>` : nothing}</div>
        <div class="small muted truncate" title=${u.help || ''}>${u.id}${u.help ? ` · ${u.help}` : ''}</div></div>
      <hxk-field type="enum" label="Catena" .options=${chainOpts} .value=${o.chain || ''} @change=${(e: CustomEvent) => set('chain', e.detail)}></hxk-field>
      <hxk-field type="enum" label="Modalità" .options=${modeOpts} .value=${o.mode || ''} @change=${(e: CustomEvent) => set('mode', e.detail)}></hxk-field>
      <hxk-field type="enum" label="Ragionamento" .options=${THINKING} .value=${o.thinking || ''} @change=${(e: CustomEvent) => set('thinking', e.detail)}></hxk-field>
    </div>`;
  }

  private usecases() {
    const groups: Record<string, any[]> = {};
    for (const u of this.data?.usecases || []) (groups[u.module || 'altro'] ||= []).push(u);
    return Object.entries(groups).map(([mod, rows]) => html`<hxk-card heading=${mod}>${rows.map(u => this.ucRow(u))}</hxk-card>`);
  }

  private saveBar(part: 'providers' | 'chains' | 'usecases') {
    if (!this.dirty[part]) return nothing;
    return html`<div class="actions"><hxk-button variant="ghost" @click=${() => this.load()}>Annulla</hxk-button>
      <hxk-button variant="primary" icon="check" ?loading=${this.saving === part} @click=${() => this.save(part)}>Salva</hxk-button></div>`;
  }

  render() {
    if (this.error) return html`<hxk-state kind="error" text=${this.error} @retry=${() => this.load()}></hxk-state>`;
    if (!this.data) return html`<hxk-state kind="loading"></hxk-state>`;
    return html`
      <div class="section"><h2>Usi dei moduli</h2>
        <div class="hint">Ogni modulo dichiara i suoi usi; qui scegli la catena e la modalità (Interna = catena di Oracle,
          Esterna = agente esterno come Claude Code). Vuoto = quello che suggerisce il modulo.</div>
        ${this.usecases()}${this.saveBar('usecases')}</div>
      <div class="section"><h2>Catene di modelli</h2>
        <div class="hint">Come una lista di font: si usa il primo modello pronto; se finisce la quota passo al successivo e lo
          salto finché non si ricarica.</div>
        ${Object.keys(this.chains).map(n => this.chainCard(n))}
        <div class="actions"><hxk-button variant="ghost" icon="plus" @click=${() => this.addChain()}>Nuova catena</hxk-button></div>
        ${this.saveBar('chains')}</div>
      <div class="section"><h2>Fornitori</h2>
        <div class="hint">Dove stanno i modelli. La chiave non si scrive qui: va nel file .env come ORACLE_KEY_&lt;NOME&gt;.</div>
        ${Object.keys(this.providers).map(n => this.providerCard(n))}
        <div class="actions"><hxk-button variant="ghost" icon="plus" @click=${() => this.addProvider()}>Nuovo fornitore</hxk-button></div>
        ${this.saveBar('providers')}</div>`;
  }
}
