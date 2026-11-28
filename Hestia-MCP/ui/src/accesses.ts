/**
 * <mcp-accesses> — "AI access": who may use Hestia's MCP from outside (Claude Code, Claude Desktop, Cursor…).
 * New token (shown once, with the ready `claude mcp add` line), revoke, renew, delete; per access: scope,
 * tools, expiry, last use, calls today. OAuth connections (claude.ai, ChatGPT) are in the same list (kind oauth):
 * `/oauth/authorize` sends the browser here with `?oauth=<request>` and the consent card decides scope and tools —
 * nothing is granted without it. Second list: External services (third-party MCP servers, credentials in Hecate).
 * SPEC docs/work/2026-10-18-core-modules-and-external-mcp §B3, §B6.
 */
import { HestiaElement, html, css, nothing, locale, tr } from '@hestia/webui-sdk';

// The «hestia» mod in this repo's Claude Code marketplace (claude-plugins/hestia, dossier 2026-10-30-hestia-in-claude).
const PLUGIN_INSTALL = '/plugin install hestia --marketplace SaibboRiginal/Hestia';
const API = '/api/mcp';
const SCOPES = [{ value: 'read', label: tr('Read only') }, { value: 'write', label: tr('Read and write (tasks, notes, branches, proposals)') }];
const EXPIRY = [{ value: '30', label: tr('30 days') }, { value: '90', label: tr('90 days') }, { value: '365', label: tr('1 year') }, { value: '0', label: tr('Never') }];

function when(iso?: string | null): string {
  if (!iso) return '–';
  return new Date(iso).toLocaleString(locale(), { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
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
    if (!r.ok) { this.consent = { id, error: r.error || tr('Request expired: link again from the app') }; return; }
    this.consent = { id, req: r.data, scope: r.data.scope || 'read', days: '90', all: true, tools: [], name: r.data.client_name };
  }

  private async decide(allow: boolean) {
    const c = this.consent; this.busy = true;
    const r = allow
      ? await this.host.api('POST', `${API}/oauth/requests/${encodeURIComponent(c.id)}/approve`,
          { body: { scope: c.scope, tools: c.all ? [] : c.tools, expires_days: Number(c.days) || null, name: c.name } })
      : await this.host.api('POST', `${API}/oauth/requests/${encodeURIComponent(c.id)}/deny`);
    this.busy = false;
    if (!r.ok || !r.data?.redirect) { this.host.toast(r.error || tr('alt::Failed'), 'danger'); return; }
    this.host.toast(allow ? tr('{0} linked: back to the app', c.name) : tr('Link refused'), allow ? 'success' : 'neutral');
    window.location.assign(r.data.redirect);   // back to the AI (its registered redirect_uri, checked by Hestia-MCP)
  }

  private async load() {
    const [a, t] = await Promise.all([this.host.api('GET', `${API}/accesses`), this.host.api('GET', `${API}/accesses/tools`)]);
    if (!a.ok) { this.error = a.error || tr('Hestia-MCP not reachable'); return; }
    this.error = ''; this.accesses = a.data.accesses || []; this.tools = t.ok ? t.data.tools || [] : [];
    const o = await this.host.api('GET', `${API}/outbound`);
    this.outbound = o.ok ? o.data : null;
  }

  private base(): string { return location.origin; }

  private async create() {
    const f = this.form;
    if (!String(f.name || '').trim()) { this.host.toast(tr('Name the access'), 'warning'); return; }
    this.busy = true;
    const r = await this.host.api('POST', `${API}/accesses`, { query: { base_url: this.base() },
      body: { name: f.name, scope: f.scope, tools: f.all ? [] : f.tools, expires_days: Number(f.days) || null } });
    this.busy = false;
    if (!r.ok) { this.host.toast(r.error || tr('Access not created'), 'danger'); return; }
    this.form = null; this.created = r.data; this.load();
  }

  private async act(a: any, what: 'revoke' | 'renew' | 'delete') {
    const asks = { revoke: [tr('Revoke the access?'), tr("{0} stops working right away. You can renew it later.", a.name)],
                   renew: a.kind === 'oauth' ? [tr('Turn it on again?'), tr("{0} works again for another 90 days.", a.name)]
                     : [tr('New token?'), tr("The current token of {0} stops working right away.", a.name)],
                   delete: [tr('Delete the access?'), tr('{0} disappears from the list.', a.name)] }[what];
    if (!(await this.host.confirm(asks[0], asks[1], { label: tr('Confirm'), danger: what !== 'renew' }))) return;
    const r = what === 'delete' ? await this.host.api('DELETE', `${API}/accesses/${a.access_id}`)
      : await this.host.api('POST', `${API}/accesses/${a.access_id}/${what}`, { query: what === 'renew' ? { base_url: this.base() } : undefined });
    if (!r.ok) { this.host.toast(r.error || tr('alt::Failed'), 'danger'); return; }
    if (what === 'renew' && r.data?.token) this.created = r.data;
    else if (what === 'renew') this.host.toast(tr('{0} reactivated', a.name), 'success');
    this.load();
  }

  private async copy(text: string) {
    try { await navigator.clipboard.writeText(text); this.host.toast(tr('Copied'), 'success'); }
    catch { this.host.toast(tr('Copy failed: select it by hand'), 'warning'); }
  }

  private copyRow(label: string, text: string) {
    return html`<div class="small muted">${label}</div>
      <div class="copyrow"><pre>${text}</pre><hxk-button size="sm" icon="check" @click=${() => this.copy(text)}>${tr("Copy")}</hxk-button></div>`;
  }

  private renderCreated() {
    const c = this.created; if (!c) return nothing;
    return html`<hxk-card heading="Token per ${c.access.name}" subtitle=${tr("You see it only now: copy it now.")}>
      ${this.copyRow(tr('Claude Code (terminal)'), c.setup.claude_code)}
      ${this.copyRow(tr('Claude Desktop, Cursor, VS Code, Gemini CLI… (JSON configuration)'), c.setup.json)}
      ${this.copyRow(tr('Only the token'), c.token)}
      <p class="note">${tr("Address:")} ${c.setup.url}${tr(". Outside home you need the address of the named tunnel (see README, \"Linking an external AI\").")}</p>
      <hxk-button variant="primary" @click=${() => (this.created = null)}>${tr("Done")}</hxk-button>
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
    return html`<hxk-card heading=${tr("New access")}><div class="form">
      <hxk-field label=${tr("Name")} placeholder=${tr("Claude Code PC")} .value=${f.name} @change=${set('name')}></hxk-field>
      <hxk-field label=${tr("What it can do")} type="enum" .options=${SCOPES} .value=${f.scope} @change=${set('scope')}></hxk-field>
      <hxk-field label=${tr("Expires after")} type="enum" .options=${EXPIRY} .value=${f.days} @change=${set('days')}></hxk-field>
      <hxk-field label=${tr("All tools open to external AIs")} type="bool" .value=${f.all} @change=${set('all')}></hxk-field>
      ${f.all ? nothing : html`<div class="tools">${visible.map(t => html`<label title=${t.description || ''}>
        <input type="checkbox" .checked=${f.tools.includes(t.name)} @change=${(e: any) => toggle(t.name, e.target.checked)}>
        ${t.title || t.name}${t.writes ? html` <span class="pill w">${tr("writes")}</span>` : nothing}</label>`)}</div>`}
      <p class="note">${tr("Approving, merging or undoing a development always stays with you, on {assistant}.")}</p>
      <div class="acts"><hxk-button variant="primary" ?loading=${this.busy} @click=${() => this.create()}>${tr("Create token")}</hxk-button>
        <hxk-button variant="ghost" @click=${() => (this.form = null)}>${tr("Cancel")}</hxk-button></div>
    </div></hxk-card>`;
  }

  private renderConsent() {
    const c = this.consent; if (!c) return nothing;
    if (c.error) return html`<hxk-card heading=${tr("AI link")}><p>${c.error}</p>
      <hxk-button variant="ghost" @click=${() => (this.consent = null)}>${tr("Close")}</hxk-button></hxk-card>`;
    const set = (k: string) => (e: any) => (this.consent = { ...this.consent, [k]: e.detail });
    const toggle = (name: string, on: boolean) => {
      const tools = new Set<string>(this.consent.tools); on ? tools.add(name) : tools.delete(name);
      this.consent = { ...this.consent, tools: [...tools] };
    };
    const visible = (c.req.tools || []).filter((t: any) => c.scope === 'write' || !t.writes);
    return html`<hxk-card heading=${tr("Link {0}?", c.req.client_name)} subtitle=${tr("Asks to use the assistant via MCP · back to {0}", c.req.redirect_host)}><div class="form">
      <hxk-field label=${tr("Name in the list")} .value=${c.name} @change=${set('name')}></hxk-field>
      <hxk-field label=${tr("What it can do")} type="enum" .options=${SCOPES} .value=${c.scope} @change=${set('scope')}></hxk-field>
      <hxk-field label=${tr("Expires after")} type="enum" .options=${EXPIRY} .value=${c.days} @change=${set('days')}></hxk-field>
      <hxk-field label=${tr("All tools open to external AIs")} type="bool" .value=${c.all} @change=${set('all')}></hxk-field>
      ${c.all ? nothing : html`<div class="tools">${visible.map((t: any) => html`<label title=${t.description || ''}>
        <input type="checkbox" .checked=${c.tools.includes(t.name)} @change=${(e: any) => toggle(t.name, e.target.checked)}>
        ${t.title || t.name}${t.writes ? html` <span class="pill w">${tr("writes")}</span>` : nothing}</label>`)}</div>`}
      <p class="note">${tr("If you didn't start the link, refuse. You can revoke it whenever you want from this page.")}</p>
      <div class="acts"><hxk-button variant="primary" ?loading=${this.busy} @click=${() => this.decide(true)}>${tr("Allow")}</hxk-button>
        <hxk-button variant="ghost" ?disabled=${this.busy} @click=${() => this.decide(false)}>${tr("Reject")}</hxk-button></div>
    </div></hxk-card>`;
  }

  private renderOutbound() {
    const o = this.outbound; if (!o) return nothing;
    const label: Record<string, string> = { configured: tr('configured'), invalid_url: tr('invalid address') };
    return html`<h2>${tr("External services")}</h2><p class="sub">${tr("Third-party MCP servers {assistant} can use: add and remove them in Connections.")}
        <hxk-button variant="ghost" icon="external" @click=${() => this.host.openConnection('hecate.external_mcp')}>${tr("Open in Connections")}</hxk-button></p>
      ${o.servers.length ? html`<div class="card">${o.servers.map(s => html`<div class="acc"><div class="grow">
          <div><b>${s.name}</b> <span class="pill ${s.status === 'configured' ? '' : 'off'}">${label[s.status] || s.status}</span></div>
          <div class="small muted">${s.host || '–'} · ${s.auth === 'key' ? tr('with key') : tr('without key')}</div></div></div>`)}</div>`
        : html`<p class="note">${o.how_to || tr('No external service.')}</p>`}`;
  }

  private status(a: any) {
    if (a.revoked_at) return html`<span class="pill off">${tr("revoked")}</span>`;
    if (a.expires_at && Date.parse(a.expires_at) <= Date.now()) return html`<span class="pill off">${tr("expired")}</span>`;
    return html`<span class="pill">${a.scope === 'write' ? tr('read and write') : tr('read only')}</span>`;
  }

  private kind(a: any) {
    return a.kind === 'oauth' ? html` <span class="pill">${tr("OAuth")}${a.meta?.client_name && a.meta.client_name !== a.name ? ` · ${a.meta.client_name}` : ''}</span>` : nothing;
  }

  render() {
    if (this.error) return html`<div class="page"><hxk-state kind="offline" text=${this.error}></hxk-state></div>`;
    if (!this.accesses) return html`<div class="page"><hxk-state kind="loading"></hxk-state></div>`;
    const list = this.accesses;
    return html`<div class="page">
      <hxk-page-head heading=${tr("AI access")} sub=${tr("External AIs that can use {assistant} via MCP")} ask=${tr("AI access")}>
        ${this.form ? nothing : html`<hxk-button variant="primary" icon="plus"
          @click=${() => (this.form = { name: '', scope: 'read', days: '90', all: true, tools: [] })}>${tr("New token")}</hxk-button>`}</hxk-page-head>
      ${this.renderConsent()}${this.renderCreated()}${this.renderForm()}
      ${list.length ? html`<div class="card">${list.map(a => html`<div class="acc"><div class="grow">
          <div><b>${a.name}</b> ${this.status(a)}${this.kind(a)}</div>
          <div class="small muted">${a.tools?.length ? tr('{0} tools', a.tools.length) : tr('all tools open')}
            · ${tr('expires')} ${a.expires_at ? when(a.expires_at) : tr('never')} ${tr("· last use")} ${when(a.last_used_at)} ${tr("· today")} ${a.calls_today} ${tr("calls")}</div></div>
          <div class="acts">${a.revoked_at ? nothing : html`<hxk-button size="sm" variant="ghost" @click=${() => this.act(a, 'revoke')}>${tr("Revoke")}</hxk-button>`}
            <hxk-button size="sm" variant="ghost" icon="refresh" @click=${() => this.act(a, 'renew')}>${a.kind === 'oauth' ? tr('Turn back on') : tr('Renew')}</hxk-button>
            <hxk-button size="sm" variant="ghost" icon="trash" @click=${() => this.act(a, 'delete')}>${tr("Delete")}</hxk-button></div>
        </div>`)}</div>`
        : this.form || this.created ? nothing : html`<hxk-empty icon="unlock" heading=${tr("No access yet")} example=${tr("How do I link Claude Code?")}>${tr("Create a token to link Claude Code or another AI.")}</hxk-empty>`}
      <p class="note">${tr("claude.ai (web and phone) and ChatGPT: add a custom connector with the public address")}
        ${this.base()}/mcp${tr('; the assistant asks for your consent here.')}</p>
      <hxk-card heading=${tr("{assistant} inside Claude Code")} subtitle=${tr("A bar above the prompt: turn it on only when you want")}>
        ${this.copyRow(tr('Install (Claude Code terminal)'), PLUGIN_INSTALL)}
        ${this.copyRow(tr('Address to give to the installation'), this.base())}
        <p class="note">${tr("On first start Claude opens this page for consent. Personality, instructions and memories come from {assistant}; what Claude learns about you comes back to the Memory page.")}</p>
      </hxk-card>
      ${this.renderOutbound()}
    </div>`;
  }
}
