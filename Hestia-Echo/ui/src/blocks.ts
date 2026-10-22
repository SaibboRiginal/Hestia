/**
 * <echo-blocks> — Voce, tab «Motori» (dossier docs/work/2026-10-20-modulo-voce §5): named providers (keys stay in
 * .env as ECHO_KEY_<NAME>), chains of ascolto or voce (order = fallback, quota state per step), every use declared by
 * a module → chain / mode. Built like Oracle's «Modelli». Saves through Themis (PUT /api/voice/blocks/<part>).
 */
import { HestiaElement, html, css, nothing } from '@hestia/webui-sdk';
import { API, DIRECTIONS, STATES, clone, slug } from './util';

type Opt = { value: string; label: string };
type Part = 'providers' | 'chains' | 'usecases';
const MODES: Opt[] = [{ value: 'interna', label: 'Interna' }, { value: 'esterna', label: 'Esterna' }];

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
    .step { display: grid; grid-template-columns: 24px minmax(0, 1fr) minmax(0, 1.4fr) auto; gap: 8px; align-items: end;
      padding: 8px 0; border-top: 1px solid var(--border); }
    .idx { font-variant-numeric: tabular-nums; color: var(--text-3); padding-bottom: 8px; }
    .tools { display: flex; gap: 2px; }
    .state { grid-column: 2 / -1; font-size: 12px; display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
    .uc { display: grid; grid-template-columns: minmax(0, 1.4fr) repeat(2, minmax(0, 1fr)); gap: 8px; align-items: end;
      padding: 8px 0; border-top: 1px solid var(--border); }
    .uc:first-of-type { border-top: 0; }
    .key { font-family: var(--font-mono, monospace); font-size: 12px; }
    .actions { display: flex; gap: 8px; justify-content: flex-end; flex-wrap: wrap; }
    input.pick { font: inherit; color: var(--text); background: var(--surface-2); border: 1px solid var(--border-strong);
      border-radius: var(--radius-sm); padding: 7px 10px; width: 100%; box-sizing: border-box; }
    @media (max-width: 560px) { .uc { grid-template-columns: 1fr 1fr; } .uc > :first-child { grid-column: 1 / -1; }
      .step { grid-template-columns: 20px 1fr; } .step > :nth-child(3), .step > .tools { grid-column: 2; } }
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
    if (!p.ok) { this.error = p.error || 'Non raggiungibile'; return; }
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
    for (const x of this.live.usecases) if (x.overridden) ov[x.id] = { ...(x.chain !== x.suggested_chain ? { chain: x.chain } : {}), ...(x.mode !== 'segui' ? { mode: x.mode } : {}) };
    this.overrides = clone(ov);
    this.dirty = {};
  }

  private touch(part: Part) { this.dirty = { ...this.dirty, [part]: true }; this.requestUpdate(); }

  private async save(part: Part) {
    const value = part === 'providers' ? this.providers : part === 'chains' ? this.chains : this.overrides;
    this.saving = part;
    const r = await this.host.api('PUT', `${API}/blocks/${part}`, { body: { value } });
    this.saving = '';
    if (!r.ok) { this.host.toast(r.error || 'Non salvato', 'danger'); return; }
    this.host.toast('Salvato', 'success');
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
    return html`<hxk-card heading=${p.label || name} subtitle=${`${name} · ${(std.directions || []).join(' e ')}`}>
      <hxk-button slot="actions" variant="ghost" icon="trash" @click=${() => this.removeProvider(name)}>Rimuovi</hxk-button>
      <div class="grid2">
        <hxk-field label="Nome visibile" .value=${p.label} @change=${(e: CustomEvent) => set('label', e.detail)}></hxk-field>
        <hxk-field type="enum" label="Standard" .options=${types} .value=${p.type} @change=${(e: CustomEvent) => set('type', e.detail)}></hxk-field>
        ${std.needs_url || std.default_url ? html`<hxk-field label="Indirizzo" .value=${p.url} placeholder=${std.default_url || ''}
          @change=${(e: CustomEvent) => set('url', e.detail)}></hxk-field>` : nothing}
        ${(std.options || []).map((o: any) => html`<hxk-field type=${o.type === 'string' ? 'text' : o.type} label=${o.label}
          .options=${o.options || []} help=${o.help || ''} .value=${p.options?.[o.key] ?? o.default}
          @change=${(e: CustomEvent) => setOpt(o.key, e.detail)}></hxk-field>`)}
      </div>
      <div class="state" style="margin-top:8px">
        <hxk-badge tone=${st.tone}>${st.label}</hxk-badge>
        ${live.needs_key ? html`<span>Chiave in .env: <span class="key">${live.key_env}</span>
          ${live.key ? html`<hxk-icon name="check" size=${13} tone="success" title="impostata"></hxk-icon>` : ' — manca'}</span>` : nothing}
        ${Object.keys(live.quota || {}).length ? html`<hxk-badge tone="warning">senza quota</hxk-badge>
          <hxk-button variant="ghost" @click=${() => this.retry(name)}>Riprova adesso</hxk-button>` : nothing}
      </div>
    </hxk-card>`;
  }

  private async retry(name: string) {
    await this.host.api('POST', `${API}/providers/${name}/retry`);
    this.load();
  }

  private addProvider() {
    const raw = window.prompt('Nome del nuovo fornitore (es. deepgram). La chiave andrà in .env come ECHO_KEY_<NOME>.');
    const name = slug(raw || '');
    if (!name || this.providers[name]) return;
    this.providers = { ...this.providers, [name]: { type: 'openai', label: raw!.trim(), url: '', options: {} } };
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
    const c = this.chains[chain];
    const steps = c.steps as any[];
    const live = this.live?.chains?.[chain]?.steps?.[i];
    const provOpts: Opt[] = Object.entries<any>(this.providers)
      .filter(([, p]) => (this.std(p.type).directions || []).includes(c.direction))
      .map(([n, p]) => ({ value: n, label: p.label || n }));
    const lp = this.liveProvider(step.provider);
    const speaking = c.direction === 'voce';
    const choices: any[] = speaking ? lp.voices || [] : lp.models || [];
    const update = (patch: any) => { const next = steps.slice(); next[i] = { ...step, ...patch }; this.setSteps(chain, next); };
    const move = (d: number) => { const next = steps.slice(); const [s] = next.splice(i, 1); next.splice(i + d, 0, s); this.setSteps(chain, next); };
    const listId = `l-${chain}-${i}`;
    const st = live ? STATES[live.state] : null;
    return html`<div class="step">
      <span class="idx">${i + 1}</span>
      <hxk-field type="enum" label="Fornitore" .options=${provOpts} .value=${step.provider}
        @change=${(e: CustomEvent) => update({ provider: e.detail })}></hxk-field>
      <div>
        <label class="small muted">${speaking ? 'Voce' : 'Modello'}</label>
        <input class="pick" list=${listId} .value=${speaking ? step.voice : step.model}
          @change=${(e: any) => update(speaking ? { voice: String(e.target.value).trim() } : { model: String(e.target.value).trim() })}>
        <datalist id=${listId}>${choices.map((m: any) => html`<option value=${m.id}>${m.label || m.id}</option>`)}</datalist>
      </div>
      <div class="tools">
        <hxk-button variant="ghost" ?disabled=${i === 0} @click=${() => move(-1)} title="Prima">↑</hxk-button>
        <hxk-button variant="ghost" ?disabled=${i === steps.length - 1} @click=${() => move(1)} title="Dopo">↓</hxk-button>
        <hxk-button variant="ghost" icon="trash" @click=${() => this.setSteps(chain, steps.filter((_, j) => j !== i))} title="Togli"></hxk-button>
      </div>
      ${live && live.state !== 'ready' && st ? html`<div class="state"><hxk-badge tone=${st.tone}>${st.label}${live.until ? ` fino alle ${String(live.until).slice(11, 16)}` : ''}</hxk-badge>
        ${live.state === 'quota' ? html`<hxk-button variant="ghost" @click=${() => this.retry(step.provider)}>Riprova adesso</hxk-button>` : nothing}</div>` : nothing}
    </div>`;
  }

  private setSteps(chain: string, steps: any[]) {
    this.chains = { ...this.chains, [chain]: { ...this.chains[chain], steps } };
    this.touch('chains');
  }

  private chainCard(name: string) {
    const c = this.chains[name];
    const first = Object.entries<any>(this.providers).find(([, p]) => (this.std(p.type).directions || []).includes(c.direction));
    return html`<hxk-card heading=${c.label || name} subtitle=${`${name} · ${c.direction === 'voce' ? 'voce' : 'ascolto'}`}>
      <hxk-button slot="actions" variant="ghost" icon="trash" @click=${() => this.removeChain(name)}>Elimina</hxk-button>
      <hxk-field label="Nome visibile" .value=${c.label}
        @change=${(e: CustomEvent) => { this.chains = { ...this.chains, [name]: { ...c, label: e.detail } }; this.touch('chains'); }}></hxk-field>
      ${c.steps.map((s: any, i: number) => this.stepRow(name, i, s))}
      <hxk-button variant="ghost" icon="plus" ?disabled=${!first}
        @click=${() => this.setSteps(name, [...c.steps, { provider: first?.[0] || '', model: '', voice: '', options: {} }])}>Aggiungi un passo</hxk-button>
    </hxk-card>`;
  }

  private addChain() {
    const raw = window.prompt('Nome della nuova catena (es. voce-calda)');
    const name = slug(raw || '');
    if (!name || this.chains[name]) return;
    const voice = window.confirm('È una catena di voce (testo → voce)? Annulla = di ascolto.');
    this.chains = { ...this.chains, [name]: { label: raw!.trim(), direction: voice ? 'voce' : 'ascolto', steps: [] } };
    this.touch('chains');
  }

  private async removeChain(name: string) {
    const users = (this.live?.usecases || []).filter((u: any) => u.chain === name).map((u: any) => u.label);
    const text = users.length ? `La usano: ${users.join(', ')}. Torneranno alla catena predefinita.` : 'Nessun uso la sceglie.';
    if (!(await this.host.confirm(`Eliminare la catena ${name}?`, text, { label: 'Elimina', danger: true }))) return;
    const next = { ...this.chains }; delete next[name];
    this.chains = next; this.touch('chains');
  }

  // ── use cases ──────────────────────────────────────────────────────────
  private ucRow(u: any) {
    const o = this.overrides[u.id] || {};
    const chainOpts: Opt[] = [{ value: '', label: `Suggerita (${u.suggested_chain || u.direction})` },
      ...Object.entries<any>(this.chains).filter(([, c]) => c.direction === u.direction).map(([n, c]) => ({ value: n, label: c.label || n }))];
    const modeOpts: Opt[] = [{ value: '', label: 'Come tutta la voce' }, ...MODES];
    const set = (k: string, v: string) => {
      const next = { ...o, [k]: v }; if (!v) delete next[k];
      const all: Record<string, any> = { ...this.overrides, [u.id]: next }; if (!Object.keys(next).length) delete all[u.id];
      this.overrides = all; this.touch('usecases');
    };
    return html`<div class="uc">
      <div><div class="truncate"><b>${u.label}</b>${u.undeclared ? html` <hxk-badge tone="warning">non dichiarato</hxk-badge>` : nothing}</div>
        <div class="small muted truncate" title=${u.help || ''}>${u.direction} · ${u.id}${u.help ? ` · ${u.help}` : ''}</div></div>
      <hxk-field type="enum" label="Catena" .options=${chainOpts} .value=${o.chain || ''} @change=${(e: CustomEvent) => set('chain', e.detail)}></hxk-field>
      <hxk-field type="enum" label="Modalità" .options=${modeOpts} .value=${o.mode && o.mode !== 'segui' ? o.mode : ''}
        @change=${(e: CustomEvent) => set('mode', e.detail)}></hxk-field>
    </div>`;
  }

  private usecases() {
    const groups: Record<string, any[]> = {};
    for (const u of this.live?.usecases || []) (groups[u.module || 'altro'] ||= []).push(u);
    return Object.entries(groups).map(([mod, rows]) => html`<hxk-card heading=${mod}>${rows.map(u => this.ucRow(u))}</hxk-card>`);
  }

  private saveBar(part: Part) {
    if (!this.dirty[part]) return nothing;
    return html`<div class="actions"><hxk-button variant="ghost" @click=${() => this.load()}>Annulla</hxk-button>
      <hxk-button variant="primary" icon="check" ?loading=${this.saving === part} @click=${() => this.save(part)}>Salva</hxk-button></div>`;
  }

  render() {
    if (this.error) return html`<hxk-state kind="error" text=${this.error} @retry=${() => this.load()}></hxk-state>`;
    if (!this.live) return html`<hxk-state kind="loading"></hxk-state>`;
    const byDir = (d: string) => Object.keys(this.chains).filter(n => this.chains[n].direction === d);
    return html`
      <div class="section"><h2>Usi dei moduli</h2>
        <div class="hint">Ogni modulo dichiara dove ascolta o parla; qui scegli la catena e la modalità (Interna = catene di
          questa pagina, Esterna = il motore scelto in Impostazioni fa tutto). Vuoto = la scelta suggerita.</div>
        ${this.usecases()}${this.saveBar('usecases')}</div>
      ${DIRECTIONS.map(d => html`<div class="section"><h2>Catene di ${d.value}</h2>
        <div class="hint">${d.label}. Si usa il primo passo pronto; se un motore non va o finisce la quota passo al successivo.</div>
        ${byDir(d.value).map(n => this.chainCard(n))}</div>`)}
      <div class="actions"><hxk-button variant="ghost" icon="plus" @click=${() => this.addChain()}>Nuova catena</hxk-button></div>
      ${this.saveBar('chains')}
      <div class="section"><h2>Fornitori</h2>
        <div class="hint">Dove stanno i motori della voce. La chiave non si scrive qui: va nel file .env come ECHO_KEY_&lt;NOME&gt;.</div>
        ${Object.keys(this.providers).map(n => this.providerCard(n))}
        <div class="actions"><hxk-button variant="ghost" icon="plus" @click=${() => this.addProvider()}>Nuovo fornitore</hxk-button></div>
        ${this.saveBar('providers')}</div>`;
  }
}
