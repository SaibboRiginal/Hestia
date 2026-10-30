/**
 * <mcp-accesses> — "Accessi AI": who may use Hestia's MCP from outside (Claude Code, Claude Desktop, Cursor…).
 * New token (shown once, with the ready `claude mcp add` line), revoke, renew, delete; per access: scope,
 * tools, expiry, last use, calls today. OAuth connections (claude.ai, ChatGPT) are in the same list (kind oauth):
 * `/oauth/authorize` sends the browser here with `?oauth=<request>` and the consent card decides scope and tools —
 * nothing is granted without it. Second list: Servizi esterni (third-party MCP servers, credentials in Hecate).
 * SPEC docs/work/2026-10-18-moduli-core-e-mcp-esterno §B3, §B6.
 */
import { HestiaElement, html, css, nothing } from '@hestia/webui-sdk';

// The «hestia» mod in this repo's Claude Code marketplace (claude-plugins/hestia, dossier 2026-10-30-hestia-in-claude).
const PLUGIN_INSTALL = '/plugin install hestia --marketplace SaibboRiginal/Hestia';
const API = '/api/mcp';
const SCOPES = [{ value: 'read', label: 'Solo lettura' }, { value: 'write', label: 'Lettura e scrittura (task, note, branch, proposte)' }];
const EXPIRY = [{ value: '30', label: '30 giorni' }, { value: '90', label: '90 giorni' }, { value: '365', label: '1 anno' }, { value: '0', label: 'Mai' }];

function when(iso?: string | null): string {
  if (!iso) return '–';
  return new Date(iso).toLocaleString('it-IT', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}

export class McpAccesses extends HestiaElement {
  static properties = { ...HestiaElement.properties, accesses: { state: true }, tools: { state: true }, error: { state: true },
                        form: { state: true }, created: { state: true }, busy: { state: true },
                        consent: { state: true }, outbound: { state: true } };
  declare accesses: any[] | null; declare tools: any[]; declare error: string; declare form: any; declare created: any; declare busy: boolean;
  declare consent: any; declare outbound: { servers: any[]; how_to?: string } | null;
  static styles = [...HestiaElement.styles, css`
    .head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
    h1 { font-size: 20px; margin: 0; } h2 { font-size: 16px; margin: 20px 0 2px; } .sub { color: var(--text-3); font-size: 13px; }
    .acc { display: flex; gap: 10px; align-items: flex-start; padding: 12px 0; border-top: 1px solid var(--border); }
    .acc:first-child { border-top: 0; }
    .acts { display: flex; gap: 6px; flex-wrap: wrap; }
    .pill { font-size: 11px; padding: 1px 7px; border-radius: 99px; background: var(--surface-2); color: var(--text-2); }
    .pill.off { background: var(--danger-soft, #fde8e8); color: var(--danger, #b42318); }
    .pill.w { background: var(--warning-soft, #fff4e5); color: var(--warning, #b54708); }
    pre { white-space: pre-wrap; word-break: break-all; background: var(--surface-2); border-radius: var(--radius-sm); padding: 8px 10px;
      font-size: 12px; margin: 4px 0 0; }
    .copyrow { display: flex; gap: 6px; align-items: flex-start; margin-top: 8px; } .copyrow pre { flex: 1; }
    .tools { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 4px 12px; margin-top: 4px; }
    .tools label { display: flex; gap: 6px; align-items: center; font-size: 13px; }
    .form { display: flex; flex-direction: column; gap: 10px; }
    .note { font-size: 12px; color: var(--text-3); }
  `];
  constructor() { super(); this.accesses = null; this.tools = []; this.error = ''; this.form = null; this.created = null; this.busy = false;
    this.consent = null; this.outbound = null; }

  connectedCallback() {
    super.connectedCallback(); this.load(); this.onHost('refresh', () => this.load());
    const request = this.ctx?.query?.oauth; if (request) this.loadConsent(request);
  }

  /** OAuth: the request parked by /oauth/authorize (who asks, which tools there are). */
  private async loadConsent(id: string) {
    const r = await this.host.api('GET', `${API}/oauth/requests/${encodeURIComponent(id)}`);
    if (!r.ok) { this.consent = { id, error: r.error || 'Richiesta scaduta: ricollega dall\'app' }; return; }
    this.consent = { id, req: r.data, scope: r.data.scope || 'read', days: '90', all: true, tools: [], name: r.data.client_name };
  }

  private async decide(allow: boolean) {
    const c = this.consent; this.busy = true;
    const r = allow
      ? await this.host.api('POST', `${API}/oauth/requests/${encodeURIComponent(c.id)}/approve`,
          { body: { scope: c.scope, tools: c.all ? [] : c.tools, expires_days: Number(c.days) || null, name: c.name } })
      : await this.host.api('POST', `${API}/oauth/requests/${encodeURIComponent(c.id)}/deny`);
    this.busy = false;
    if (!r.ok || !r.data?.redirect) { this.host.toast(r.error || 'Non riuscito', 'danger'); return; }
    this.host.toast(allow ? `${c.name} collegato: torno all'app` : 'Collegamento rifiutato', allow ? 'success' : 'neutral');
    window.location.assign(r.data.redirect);   // back to the AI (its registered redirect_uri, checked by Hestia-MCP)
  }

  private async load() {
    const [a, t] = await Promise.all([this.host.api('GET', `${API}/accesses`), this.host.api('GET', `${API}/accesses/tools`)]);
    if (!a.ok) { this.error = a.error || 'Hestia-MCP non raggiungibile'; return; }
    this.error = ''; this.accesses = a.data.accesses || []; this.tools = t.ok ? t.data.tools || [] : [];
    const o = await this.host.api('GET', `${API}/outbound`);
    this.outbound = o.ok ? o.data : null;
  }

  private base(): string { return location.origin; }

  private async create() {
    const f = this.form;
    if (!String(f.name || '').trim()) { this.host.toast('Dai un nome all\'accesso', 'warning'); return; }
    this.busy = true;
    const r = await this.host.api('POST', `${API}/accesses`, { query: { base_url: this.base() },
      body: { name: f.name, scope: f.scope, tools: f.all ? [] : f.tools, expires_days: Number(f.days) || null } });
    this.busy = false;
    if (!r.ok) { this.host.toast(r.error || 'Accesso non creato', 'danger'); return; }
    this.form = null; this.created = r.data; this.load();
  }

  private async act(a: any, what: 'revoke' | 'renew' | 'delete') {
    const asks = { revoke: ['Revocare l\'accesso?', `${a.name} smette subito di funzionare. Puoi rinnovarlo dopo.`],
                   renew: a.kind === 'oauth' ? ['Riattivare?', `${a.name} torna a funzionare per altri 90 giorni.`]
                     : ['Nuovo token?', `Il token attuale di ${a.name} smette subito di funzionare.`],
                   delete: ['Eliminare l\'accesso?', `${a.name} sparisce dall'elenco.`] }[what];
    if (!(await this.host.confirm(asks[0], asks[1], { label: 'Conferma', danger: what !== 'renew' }))) return;
    const r = what === 'delete' ? await this.host.api('DELETE', `${API}/accesses/${a.access_id}`)
      : await this.host.api('POST', `${API}/accesses/${a.access_id}/${what}`, { query: what === 'renew' ? { base_url: this.base() } : undefined });
    if (!r.ok) { this.host.toast(r.error || 'Non riuscito', 'danger'); return; }
    if (what === 'renew' && r.data?.token) this.created = r.data;
    else if (what === 'renew') this.host.toast(`${a.name} riattivato`, 'success');
    this.load();
  }

  private async copy(text: string) {
    try { await navigator.clipboard.writeText(text); this.host.toast('Copiato', 'success'); }
    catch { this.host.toast('Copia non riuscita: selezionalo a mano', 'warning'); }
  }

  private copyRow(label: string, text: string) {
    return html`<div class="small muted">${label}</div>
      <div class="copyrow"><pre>${text}</pre><hxk-button size="sm" icon="check" @click=${() => this.copy(text)}>Copia</hxk-button></div>`;
  }

  private renderCreated() {
    const c = this.created; if (!c) return nothing;
    return html`<hxk-card heading="Token per ${c.access.name}" subtitle="Lo vedi solo ora: copialo adesso.">
      ${this.copyRow('Claude Code (terminale)', c.setup.claude_code)}
      ${this.copyRow('Claude Desktop, Cursor, VS Code, Gemini CLI… (configurazione JSON)', c.setup.json)}
      ${this.copyRow('Solo il token', c.token)}
      <p class="note">Indirizzo: ${c.setup.url}. Fuori casa serve l'indirizzo del tunnel con nome (vedi README, "Collegare un'AI esterna").</p>
      <hxk-button variant="primary" @click=${() => (this.created = null)}>Fatto</hxk-button>
    </hxk-card>`;
  }

  private renderForm() {
    const f = this.form; if (!f) return nothing;
    const set = (k: string) => (e: any) => (this.form = { ...this.form, [k]: e.detail });
    const toggle = (name: string, on: boolean) => {
      const tools = new Set<string>(this.form.tools); on ? tools.add(name) : tools.delete(name);
      this.form = { ...this.form, tools: [...tools] };
    };
    const visible = this.tools.filter(t => f.scope === 'write' || !t.writes);
    return html`<hxk-card heading="Nuovo accesso"><div class="form">
      <hxk-field label="Nome" placeholder="Claude Code PC" .value=${f.name} @change=${set('name')}></hxk-field>
      <hxk-field label="Cosa può fare" type="enum" .options=${SCOPES} .value=${f.scope} @change=${set('scope')}></hxk-field>
      <hxk-field label="Scade dopo" type="enum" .options=${EXPIRY} .value=${f.days} @change=${set('days')}></hxk-field>
      <hxk-field label="Tutti gli strumenti aperti alle AI esterne" type="bool" .value=${f.all} @change=${set('all')}></hxk-field>
      ${f.all ? nothing : html`<div class="tools">${visible.map(t => html`<label title=${t.description || ''}>
        <input type="checkbox" .checked=${f.tools.includes(t.name)} @change=${(e: any) => toggle(t.name, e.target.checked)}>
        ${t.title || t.name}${t.writes ? html` <span class="pill w">scrive</span>` : nothing}</label>`)}</div>`}
      <p class="note">Approvare, unire o annullare uno sviluppo resta sempre a te, su Hestia.</p>
      <div class="acts"><hxk-button variant="primary" ?loading=${this.busy} @click=${() => this.create()}>Crea token</hxk-button>
        <hxk-button variant="ghost" @click=${() => (this.form = null)}>Annulla</hxk-button></div>
    </div></hxk-card>`;
  }

  private renderConsent() {
    const c = this.consent; if (!c) return nothing;
    if (c.error) return html`<hxk-card heading="Collegamento AI"><p>${c.error}</p>
      <hxk-button variant="ghost" @click=${() => (this.consent = null)}>Chiudi</hxk-button></hxk-card>`;
    const set = (k: string) => (e: any) => (this.consent = { ...this.consent, [k]: e.detail });
    const toggle = (name: string, on: boolean) => {
      const tools = new Set<string>(this.consent.tools); on ? tools.add(name) : tools.delete(name);
      this.consent = { ...this.consent, tools: [...tools] };
    };
    const visible = (c.req.tools || []).filter((t: any) => c.scope === 'write' || !t.writes);
    return html`<hxk-card heading="Collegare ${c.req.client_name}?" subtitle="Chiede di usare Hestia via MCP · torna a ${c.req.redirect_host}"><div class="form">
      <hxk-field label="Nome nell'elenco" .value=${c.name} @change=${set('name')}></hxk-field>
      <hxk-field label="Cosa può fare" type="enum" .options=${SCOPES} .value=${c.scope} @change=${set('scope')}></hxk-field>
      <hxk-field label="Scade dopo" type="enum" .options=${EXPIRY} .value=${c.days} @change=${set('days')}></hxk-field>
      <hxk-field label="Tutti gli strumenti aperti alle AI esterne" type="bool" .value=${c.all} @change=${set('all')}></hxk-field>
      ${c.all ? nothing : html`<div class="tools">${visible.map((t: any) => html`<label title=${t.description || ''}>
        <input type="checkbox" .checked=${c.tools.includes(t.name)} @change=${(e: any) => toggle(t.name, e.target.checked)}>
        ${t.title || t.name}${t.writes ? html` <span class="pill w">scrive</span>` : nothing}</label>`)}</div>`}
      <p class="note">Se non hai avviato tu il collegamento, rifiuta. Puoi revocarlo quando vuoi da questa pagina.</p>
      <div class="acts"><hxk-button variant="primary" ?loading=${this.busy} @click=${() => this.decide(true)}>Consenti</hxk-button>
        <hxk-button variant="ghost" ?disabled=${this.busy} @click=${() => this.decide(false)}>Rifiuta</hxk-button></div>
    </div></hxk-card>`;
  }

  private renderOutbound() {
    const o = this.outbound; if (!o) return nothing;
    const label: Record<string, string> = { configured: 'configurato', invalid_url: 'indirizzo non valido' };
    return html`<h2>Servizi esterni</h2><p class="sub">Server MCP di terzi che Hestia può usare. Le chiavi restano nel .env (Hecate).</p>
      ${o.servers.length ? html`<div class="card">${o.servers.map(s => html`<div class="acc"><div class="grow">
          <div><b>${s.name}</b> <span class="pill ${s.status === 'configured' ? '' : 'off'}">${label[s.status] || s.status}</span></div>
          <div class="small muted">${s.host || '–'} · ${s.auth === 'key' ? 'con chiave' : 'senza chiave'}</div></div></div>`)}</div>`
        : html`<p class="note">${o.how_to || 'Nessun servizio esterno.'}</p>`}`;
  }

  private status(a: any) {
    if (a.revoked_at) return html`<span class="pill off">revocato</span>`;
    if (a.expires_at && Date.parse(a.expires_at) <= Date.now()) return html`<span class="pill off">scaduto</span>`;
    return html`<span class="pill">${a.scope === 'write' ? 'lettura e scrittura' : 'solo lettura'}</span>`;
  }

  private kind(a: any) {
    return a.kind === 'oauth' ? html` <span class="pill">OAuth${a.meta?.client_name && a.meta.client_name !== a.name ? ` · ${a.meta.client_name}` : ''}</span>` : nothing;
  }

  render() {
    if (this.error) return html`<div class="page"><hxk-state kind="offline" text=${this.error}></hxk-state></div>`;
    if (!this.accesses) return html`<div class="page"><hxk-state kind="loading"></hxk-state></div>`;
    const list = this.accesses;
    return html`<div class="page">
      <div class="head"><h1>Accessi AI</h1><span class="sub">AI esterne che possono usare Hestia via MCP</span><span class="grow"></span>
        ${this.form ? nothing : html`<hxk-button variant="primary" icon="plus"
          @click=${() => (this.form = { name: '', scope: 'read', days: '90', all: true, tools: [] })}>Nuovo token</hxk-button>`}</div>
      ${this.renderConsent()}${this.renderCreated()}${this.renderForm()}
      ${list.length ? html`<div class="card">${list.map(a => html`<div class="acc"><div class="grow">
          <div><b>${a.name}</b> ${this.status(a)}${this.kind(a)}</div>
          <div class="small muted">${a.tools?.length ? `${a.tools.length} strumenti` : 'tutti gli strumenti aperti'}
            · scade ${a.expires_at ? when(a.expires_at) : 'mai'} · ultimo uso ${when(a.last_used_at)} · oggi ${a.calls_today} chiamate</div></div>
          <div class="acts">${a.revoked_at ? nothing : html`<hxk-button size="sm" variant="ghost" @click=${() => this.act(a, 'revoke')}>Revoca</hxk-button>`}
            <hxk-button size="sm" variant="ghost" icon="refresh" @click=${() => this.act(a, 'renew')}>${a.kind === 'oauth' ? 'Riattiva' : 'Rinnova'}</hxk-button>
            <hxk-button size="sm" variant="ghost" icon="trash" @click=${() => this.act(a, 'delete')}>Elimina</hxk-button></div>
        </div>`)}</div>`
        : this.form || this.created ? nothing : html`<hxk-state kind="empty" text="Nessun accesso: crea un token per collegare Claude Code o un'altra AI."></hxk-state>`}
      <p class="note">claude.ai (web e telefono) e ChatGPT: aggiungi un connettore personalizzato con l'indirizzo pubblico
        ${this.base()}/mcp; Hestia ti chiede qui il consenso.</p>
      <hxk-card heading="Hestia dentro Claude Code" subtitle="Una barra sopra il prompt: la accendi solo quando vuoi">
        ${this.copyRow('Installa (terminale di Claude Code)', PLUGIN_INSTALL)}
        ${this.copyRow('Indirizzo da dare all\'installazione', this.base())}
        <p class="note">Alla prima accensione Claude apre questa pagina per il consenso. Personalità, istruzioni e ricordi
          arrivano da Hestia; quello che Claude impara di te torna nella pagina Memoria.</p>
      </hxk-card>
      ${this.renderOutbound()}
    </div>`;
  }
}
