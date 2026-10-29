/**
 * <mcp-commands> — "Comandi & MCP": every tool the WebUI sees (the same ones chat, Telegram and external AIs use),
 * grouped by module; pick one, fill its arguments (from its JSON schema) and run it like Hestia would.
 * Reads GET /api/mcp/ui/tools · POST /api/mcp/ui/tools/call · POST /api/mcp/ui/tools/format (Oracle natural text).
 * Ported from the built-in WebUI page (SPEC docs/work/2026-10-18-moduli-core-e-mcp-esterno §A4).
 * `?command=<tool>` opens that tool's form (Adesso, Scopri, notification buttons); `&args=<json>` fills it and
 * `&run=1` runs it at once when nothing required is missing (brainstorm W7).
 */
import { HestiaElement, html, css, nothing } from '@hestia/webui-sdk';

const API = '/api/mcp/ui';

interface Prop { type?: string; description?: string; enum?: string[] }
interface Cmd {
  command: string; title: string; description: string; service: string; method: string; path: string;
  response_mode: string; response_prompt: string; writes: boolean;
  arguments_schema: { properties?: Record<string, Prop>; required?: string[] };
}
interface Result { ok: boolean; json: string; text?: string; formatting?: boolean }

/** Turns the typed strings into the schema's types (numbers, booleans, JSON/list for arrays and objects). */
export function coerceArgs(cmd: Cmd, raw: Record<string, any>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  const props = cmd.arguments_schema?.properties ?? {};
  for (const [k, v] of Object.entries(raw)) {
    if (v === null || v === undefined || !String(v).trim()) continue;
    const t = props[k]?.type ?? 'string';
    if (t === 'integer' || t === 'number') out[k] = Number(v);
    else if (t === 'boolean') out[k] = v === true || v === 'true';
    else if (t === 'array' || t === 'object') {
      try { out[k] = JSON.parse(String(v)); } catch { out[k] = String(v).split(',').map(s => s.trim()).filter(Boolean); }
    } else out[k] = String(v);
  }
  return out;
}

export class McpCommands extends HestiaElement {
  static properties = { ...HestiaElement.properties, all: { state: true }, error: { state: true }, q: { state: true },
                        sel: { state: true }, args: { state: true }, running: { state: true }, result: { state: true } };
  declare all: Cmd[] | null; declare error: string; declare q: string; declare sel: Cmd | null;
  declare args: Record<string, any>; declare running: boolean; declare result: Result | null;

  static styles = [...HestiaElement.styles, css`
    .head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    .sub { color: var(--text-3); font-size: 13px; }
    .search { width: min(100%, 260px); }
    .head > .grow { min-width: min(100%, 240px); }   /* on a phone the title takes its line, search wraps below */
    .body { display: grid; grid-template-columns: minmax(0, 320px) minmax(0, 1fr); gap: 16px; align-items: start; }
    .list { max-height: calc(100vh - 190px); overflow-y: auto; padding: 6px; }
    h4 { font-size: 11.5px; text-transform: uppercase; letter-spacing: .05em; color: var(--text-3); margin: 12px 6px 4px;
      display: flex; justify-content: space-between; font-weight: 600; }
    h4:first-child { margin-top: 4px; }
    .it { width: 100%; display: flex; align-items: center; gap: 8px; padding: 7px 8px; border-radius: var(--radius-sm);
      font: inherit; font-size: 13.5px; text-align: left; background: transparent; border: 0; color: var(--text); cursor: pointer; }
    .it:hover { background: var(--surface-2); }
    .it.on { background: var(--accent-soft); color: var(--accent); }
    .m { font-size: 10.5px; color: var(--text-3); font-family: var(--font-mono); }
    .detail { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
    .desc { color: var(--text-2); white-space: pre-wrap; margin: 0; }
    .meta { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 12.5px; }
    code { font-family: var(--font-mono); font-size: 12px; color: var(--text-2); word-break: break-all; }
    .args { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 240px), 1fr)); gap: 12px; }
    .result { border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 14px 16px; background: var(--surface); }
    .result.err { border-color: var(--danger); }
    .text { white-space: pre-wrap; margin: 0 0 10px; }
    pre { margin: 0; max-height: 420px; overflow: auto; font-size: 12px; white-space: pre-wrap; word-break: break-word; }
    details summary { cursor: pointer; color: var(--text-3); font-size: 12px; }
    .acts { display: flex; gap: 8px; flex-wrap: wrap; }
    @media (max-width: 860px) { .body { grid-template-columns: 1fr; } .list { max-height: 40vh; } }
  `];

  constructor() {
    super(); this.all = null; this.error = ''; this.q = ''; this.sel = null; this.args = {}; this.running = false; this.result = null;
  }

  connectedCallback() { super.connectedCallback(); this.load(); this.onHost('refresh', () => this.load()); }

  private async load() {
    const r = await this.host.api('GET', `${API}/tools`);
    if (!r.ok) { this.error = r.status === 0 || !r.error ? 'Hestia-MCP non raggiungibile' : r.error; return; }
    this.error = '';
    this.all = r.data.commands || [];
    if (this.sel) this.sel = this.all!.find(c => c.command === this.sel!.command) ?? null;
    this.fromQuery();
  }

  private applied = '';

  /** Opens (and maybe runs) the tool named in the page link; once per distinct link. */
  private fromQuery() {
    const q = this.ctx?.query || {};
    const key = `${q.command || ''}|${q.args || ''}|${q.run || ''}`;
    if (!q.command || !this.all || key === this.applied) return;
    this.applied = key;
    const c = this.all.find(x => x.command === q.command);
    if (!c) { this.host.toast('Questo comando non è disponibile ora', 'warning'); return; }
    this.select(c);
    if (q.args) {
      try {
        const a = JSON.parse(q.args);
        if (a && typeof a === 'object') this.args = Object.fromEntries(Object.entries(a).map(([k, v]) =>
          [k, typeof v === 'object' ? JSON.stringify(v) : String(v)]));
      } catch { /* bad link: open the empty form */ }
    }
    const props = c.arguments_schema?.properties ?? {};
    const missing = (c.arguments_schema?.required ?? []).filter(a => a in props && !String(this.args[a] ?? '').trim());
    if (q.run === '1' && !missing.length) void this.run(c);
  }

  updated(changed: Map<string, unknown>) {
    super.updated?.(changed);
    if (changed.has('ctx')) this.fromQuery();
  }

  private groups() {
    const q = this.q.toLowerCase();
    const map = new Map<string, Cmd[]>();
    for (const c of this.all || []) {
      if (q && !`${c.title} ${c.command} ${c.description} ${c.service}`.toLowerCase().includes(q)) continue;
      const key = c.service || 'altro';
      (map.get(key) ?? map.set(key, []).get(key)!).push(c);
    }
    return [...map.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([service, items]) => ({ service, items }));
  }

  private select(c: Cmd) { this.sel = c; this.args = {}; this.result = null; }

  private async run(c: Cmd) {
    const props = c.arguments_schema?.properties ?? {};
    const missing = (c.arguments_schema?.required ?? []).filter(a => a in props && !String(this.args[a] ?? '').trim());
    if (missing.length) { this.host.toast(`Manca: ${missing.join(', ')}`, 'warning'); return; }
    if (c.writes && !(await this.host.confirm('Eseguire il comando?', `${c.title || c.command} cambia qualcosa in Hestia.`,
      { label: 'Esegui' }))) return;
    this.running = true; this.result = null;
    const r = await this.host.api('POST', `${API}/tools/call`, { body: { command: c.command, args: coerceArgs(c, this.args) } });
    this.running = false;
    if (!r.ok) { this.result = { ok: false, json: r.status === 0 ? 'Hestia-MCP non raggiungibile' : r.error || 'Errore' }; return; }
    const d = r.data;
    if (!d.ok) { this.result = { ok: false, json: typeof d.error === 'string' ? d.error : JSON.stringify(d.result, null, 2) }; return; }
    const json = typeof d.result === 'string' ? d.result : JSON.stringify(d.result, null, 2);
    const natural = d.response_mode === 'oracle_natural';
    this.result = { ok: true, json, formatting: natural };
    if (natural) this.format(c, d.result, json);
  }

  /** Oracle writes the raw answer as readable text (as in chat/Telegram); the raw JSON stays one tap away. */
  private async format(c: Cmd, result: unknown, json: string) {
    const r = await this.host.api('POST', `${API}/tools/format`,
      { body: { command: c.command, result, response_prompt: c.response_prompt || '' } });
    if (this.sel?.command !== c.command || this.result?.json !== json) return;   // another run started meanwhile
    this.result = { ok: true, json, text: r.ok && r.data?.ok ? r.data.text : undefined, formatting: false };
  }

  private askHestia() {
    const c = this.sel;
    this.host.assistant(c ? {
      label: `Comando · ${c.title || c.command}`,
      hints: { comando: c.command, servizio: c.service, metodo: c.method, path: c.path },
      suggestions: ['Eseguilo per me', 'Spiegami quando usarlo', 'Mi serve una variante che…'],
    } : { label: 'Comandi & MCP', suggestions: ['Mi serve uno strumento che…', 'Quale comando uso per…?'] });
  }

  private field(c: Cmd, a: string) {
    const p = c.arguments_schema?.properties?.[a] ?? {};
    const req = (c.arguments_schema?.required ?? []).includes(a);
    const label = `${a}${req ? ' *' : ''}`;
    const set = (e: any) => (this.args = { ...this.args, [a]: e.detail });
    const help = p.description && p.description !== a ? p.description : '';
    if (p.enum?.length) return html`<hxk-field label=${label} type="enum" .options=${['', ...p.enum]} .value=${this.args[a] ?? ''}
      help=${help} @change=${set}></hxk-field>`;
    if (p.type === 'boolean') return html`<hxk-field label=${label} type="enum"
      .options=${[{ value: '', label: '' }, { value: 'true', label: 'sì' }, { value: 'false', label: 'no' }]}
      .value=${this.args[a] ?? ''} help=${help} @change=${set}></hxk-field>`;
    const type = p.type === 'integer' ? 'int' : p.type === 'number' ? 'float' : 'text';
    return html`<hxk-field label=${label} type=${type} placeholder=${p.type === 'array' || p.type === 'object' ? 'JSON o a, b, c' : p.type || ''}
      .value=${this.args[a] ?? ''} help=${help} @change=${set}></hxk-field>`;
  }

  private renderResult() {
    const r = this.result; if (!r) return nothing;
    if (!r.ok) return html`<div class="result err"><pre>${r.json}</pre></div>`;
    if (r.text) return html`<div class="result"><p class="text">${r.text}</p>
      <details><summary>Risposta grezza</summary><pre>${r.json}</pre></details></div>`;
    return html`<div class="result">${r.formatting ? html`<div class="small muted" style="margin-bottom:8px">Hestia sta scrivendo la risposta…</div>` : nothing}
      <pre>${r.json}</pre></div>`;
  }

  private renderDetail() {
    const c = this.sel;
    if (!c) return html`<div class="card"><hxk-state kind="empty" text="Seleziona un comando: vedi descrizione e parametri ed eseguilo come farebbe Hestia."></hxk-state></div>`;
    const names = Object.keys(c.arguments_schema?.properties ?? {});
    return html`<div class="card detail">
      <h2>${c.title || c.command}</h2>
      ${c.description ? html`<p class="desc">${c.description}</p>` : nothing}
      <div class="meta"><hxk-badge>${c.service || 'altro'}</hxk-badge><code>${c.method} ${c.path}</code>
        ${c.writes ? html`<hxk-badge tone="warning">cambia qualcosa</hxk-badge>` : nothing}
        ${c.response_mode === 'oracle_natural' ? html`<hxk-badge tone="accent">risposta in linguaggio naturale</hxk-badge>` : nothing}</div>
      <div class="small muted">Nome dello strumento: <code>${c.command}</code></div>
      ${names.length ? html`<div class="args">${names.map(a => this.field(c, a))}</div>` : nothing}
      <div class="acts"><hxk-button variant="primary" icon="play" ?loading=${this.running} @click=${() => this.run(c)}>Esegui</hxk-button></div>
      ${this.renderResult()}
    </div>`;
  }

  render() {
    if (this.error) return html`<div class="page"><hxk-state kind="offline" text=${this.error} @retry=${() => this.load()}></hxk-state></div>`;
    if (!this.all) return html`<div class="page"><hxk-state kind="loading"></hxk-state></div>`;
    const groups = this.groups();
    const services = new Set(this.all.map(c => c.service)).size;
    return html`<div class="page">
      <div class="head"><div class="grow"><h1>Comandi & MCP</h1>
        <div class="sub">${this.all.length} strumenti da ${services} moduli: gli stessi di chat, Telegram e AI esterne</div></div>
        <input class="search" type="search" placeholder="Cerca comando…" .value=${this.q} @input=${(e: any) => (this.q = e.target.value)}>
        <hxk-button variant="ghost" icon="refresh" @click=${() => this.load()} title="Aggiorna"></hxk-button>
        <hxk-button variant="ghost" icon="sparkle" @click=${() => this.askHestia()}
          title="Usa un comando a parole, o fatti proporre uno strumento nuovo">Chiedi a Hestia</hxk-button></div>
      <div class="body">
        <div class="card list">
          ${groups.length ? groups.map(g => html`<h4>${g.service} <span>${g.items.length}</span></h4>
            ${g.items.map(c => html`<button class="it ${this.sel?.command === c.command ? 'on' : ''}" @click=${() => this.select(c)}>
              <span class="grow truncate">${c.title || c.command}</span><span class="m">${c.method}</span></button>`)}`)
            : html`<hxk-state kind="empty" text=${this.q ? 'Nessun comando trovato' : 'Nessuno strumento disponibile'}></hxk-state>`}
        </div>
        ${this.renderDetail()}
      </div>
    </div>`;
  }
}
