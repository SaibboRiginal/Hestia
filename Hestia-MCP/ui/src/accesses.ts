/**
 * <mcp-accesses> — "Accessi AI": who may use Hestia's MCP from outside (Claude Code, Claude Desktop, Cursor…).
 * New token (shown once, with the ready `claude mcp add` line), revoke, renew, delete; per access: scope,
 * tools, expiry, last use, calls today. SPEC docs/work/2026-10-18-moduli-core-e-mcp-esterno §B6.
 */
import { HestiaElement, html, css, nothing } from '@hestia/webui-sdk';

const API = '/api/mcp';
const SCOPES = [{ value: 'read', label: 'Solo lettura' }, { value: 'write', label: 'Lettura e scrittura (task, note, branch, proposte)' }];
const EXPIRY = [{ value: '30', label: '30 giorni' }, { value: '90', label: '90 giorni' }, { value: '365', label: '1 anno' }, { value: '0', label: 'Mai' }];

function when(iso?: string | null): string {
  if (!iso) return '–';
  return new Date(iso).toLocaleString('it-IT', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}

export class McpAccesses extends HestiaElement {
  static properties = { ...HestiaElement.properties, accesses: { state: true }, tools: { state: true }, error: { state: true },
                        form: { state: true }, created: { state: true }, busy: { state: true } };
  declare accesses: any[] | null; declare tools: any[]; declare error: string; declare form: any; declare created: any; declare busy: boolean;
  static styles = [...HestiaElement.styles, css`
    .head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
    h1 { font-size: 20px; margin: 0; } .sub { color: var(--text-3); font-size: 13px; }
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
  constructor() { super(); this.accesses = null; this.tools = []; this.error = ''; this.form = null; this.created = null; this.busy = false; }

  connectedCallback() { super.connectedCallback(); this.load(); this.onHost('refresh', () => this.load()); }

  private async load() {
    const [a, t] = await Promise.all([this.host.api('GET', `${API}/accesses`), this.host.api('GET', `${API}/accesses/tools`)]);
    if (!a.ok) { this.error = a.error || 'Hestia-MCP non raggiungibile'; return; }
    this.error = ''; this.accesses = a.data.accesses || []; this.tools = t.ok ? t.data.tools || [] : [];
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
                   renew: ['Nuovo token?', `Il token attuale di ${a.name} smette subito di funzionare.`],
                   delete: ['Eliminare l\'accesso?', `${a.name} sparisce dall'elenco.`] }[what];
    if (!(await this.host.confirm(asks[0], asks[1], { label: 'Conferma', danger: what !== 'renew' }))) return;
    const r = what === 'delete' ? await this.host.api('DELETE', `${API}/accesses/${a.access_id}`)
      : await this.host.api('POST', `${API}/accesses/${a.access_id}/${what}`, { query: what === 'renew' ? { base_url: this.base() } : undefined });
    if (!r.ok) { this.host.toast(r.error || 'Non riuscito', 'danger'); return; }
    if (what === 'renew') this.created = r.data;
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

  private status(a: any) {
    if (a.revoked_at) return html`<span class="pill off">revocato</span>`;
    if (a.expires_at && Date.parse(a.expires_at) <= Date.now()) return html`<span class="pill off">scaduto</span>`;
    return html`<span class="pill">${a.scope === 'write' ? 'lettura e scrittura' : 'solo lettura'}</span>`;
  }

  render() {
    if (this.error) return html`<div class="page"><hxk-state kind="offline" text=${this.error}></hxk-state></div>`;
    if (!this.accesses) return html`<div class="page"><hxk-state kind="loading"></hxk-state></div>`;
    const list = this.accesses;
    return html`<div class="page">
      <div class="head"><h1>Accessi AI</h1><span class="sub">AI esterne che possono usare Hestia via MCP</span><span class="grow"></span>
        ${this.form ? nothing : html`<hxk-button variant="primary" icon="plus"
          @click=${() => (this.form = { name: '', scope: 'read', days: '90', all: true, tools: [] })}>Nuovo token</hxk-button>`}</div>
      ${this.renderCreated()}${this.renderForm()}
      ${list.length ? html`<div class="card">${list.map(a => html`<div class="acc"><div class="grow">
          <div><b>${a.name}</b> ${this.status(a)}</div>
          <div class="small muted">${a.tools?.length ? `${a.tools.length} strumenti` : 'tutti gli strumenti aperti'}
            · scade ${a.expires_at ? when(a.expires_at) : 'mai'} · ultimo uso ${when(a.last_used_at)} · oggi ${a.calls_today} chiamate</div></div>
          <div class="acts">${a.revoked_at ? nothing : html`<hxk-button size="sm" variant="ghost" @click=${() => this.act(a, 'revoke')}>Revoca</hxk-button>`}
            <hxk-button size="sm" variant="ghost" icon="refresh" @click=${() => this.act(a, 'renew')}>Rinnova</hxk-button>
            <hxk-button size="sm" variant="ghost" icon="trash" @click=${() => this.act(a, 'delete')}>Elimina</hxk-button></div>
        </div>`)}</div>`
        : this.form || this.created ? nothing : html`<hxk-state kind="empty" text="Nessun accesso: crea un token per collegare Claude Code o un'altra AI."></hxk-state>`}
    </div>`;
  }
}
