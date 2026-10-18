/**
 * <themis-log> — «Registro»: every setting change and every proposal. Who (tu, Athena, Oracle, a client, an
 * external AI «external:<name>»), when, old → new. «Annulla» = Themis' existing undo of the latest change of a
 * key (the same as «Annulla ultima» in Impostazioni); proposals still wait for your Approva / Rifiuta.
 * SPEC docs/work/2026-10-18-moduli-core-e-mcp-esterno §A2.
 */
import { HestiaElement, html, css, nothing } from '@hestia/webui-sdk';

const API = '/api/settings';
const WHO_FILTERS = [
  { id: '', label: 'Tutti' }, { id: 'user,webui,telegram', label: 'Tu' }, { id: 'athena', label: 'Athena' },
  { id: 'oracle', label: 'Oracle' }, { id: 'external', label: 'AI esterne' },
];
const KIND: Record<string, string> = { undo: 'annullata', reset: 'predefinito', approved: 'proposta approvata', preset: 'preset' };
const PROPOSAL: Record<string, { text: string; tone: string }> = {
  pending: { text: 'in attesa', tone: 'accent' }, approved: { text: 'approvata', tone: 'success' },
  rejected: { text: 'rifiutata', tone: 'danger' }, expired: { text: 'scaduta', tone: 'neutral' },
};
const SCOPE: Record<string, string> = { client: 'client', profile: 'profilo', session: 'sessione' };

export function who(actor?: string | null): string {
  const a = String(actor || '');
  if (!a) return '–';
  if (a.startsWith('external:')) return `${a.slice(9)} (AI esterna)`;
  return ({ user: 'Tu', webui: 'Tu (WebUI)', telegram: 'Tu (Telegram)', oracle: 'Oracle (chat)', athena: 'Athena',
            themis: 'Themis', cascade: 'automatico' } as Record<string, string>)[a] || a;
}

function when(iso?: string | null): string {
  if (!iso) return '–';
  return new Date(iso).toLocaleString('it-IT', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}

function val(v: unknown): string {
  if (v === null || v === undefined) return 'predefinito';
  if (typeof v === 'boolean') return v ? 'sì' : 'no';
  const s = typeof v === 'string' ? v : JSON.stringify(v);
  return s.length > 60 ? s.slice(0, 59) + '…' : s || '""';
}

export class ThemisLog extends HestiaElement {
  static properties = { ...HestiaElement.properties, tab: { state: true }, rows: { state: true }, next: { state: true },
                        props: { state: true }, error: { state: true }, actor: { state: true }, module: { state: true },
                        modules: { state: true }, busy: { state: true }, total: { state: true } };
  declare tab: 'changes' | 'proposals'; declare rows: any[] | null; declare next: number | null; declare props: any[] | null;
  declare error: string; declare actor: string; declare module: string; declare modules: string[]; declare busy: string;
  declare total: number;
  static styles = [...HestiaElement.styles, css`
    .head { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
    .sub { color: var(--text-3); font-size: 13px; }
    .chips { display: flex; gap: 6px; flex-wrap: wrap; }
    .chip { font: inherit; font-size: 13px; padding: 4px 10px; border-radius: 99px; border: 1px solid var(--border-strong);
      background: var(--surface); color: var(--text-2); cursor: pointer; }
    .chip[aria-pressed=true] { background: var(--accent-soft); color: var(--accent); border-color: var(--accent); }
    .chip:focus-visible { outline: none; box-shadow: 0 0 0 3px var(--focus-ring); }
    .r { display: flex; gap: 10px; align-items: flex-start; padding: 10px 0; border-top: 1px solid var(--border); }
    .r:first-child { border-top: 0; }
    .t { font-weight: 550; overflow-wrap: anywhere; }
    .ch { font-size: 13px; overflow-wrap: anywhere; }
    .old { color: var(--text-3); text-decoration: line-through; }
    .acts { display: flex; gap: 6px; flex-wrap: wrap; }
    select { max-width: 100%; }
  `];

  constructor() {
    super(); this.tab = 'changes'; this.rows = null; this.next = null; this.props = null; this.error = ''; this.actor = '';
    this.module = ''; this.modules = []; this.busy = ''; this.total = 0;
  }

  connectedCallback() {
    super.connectedCallback();
    this.load();
    this.onHost('refresh', () => this.load());
    this.addEventListener('retry', () => this.load());
  }

  private fail(r: any) { this.error = r.status === 0 ? 'Themis non raggiungibile' : r.error || 'Themis non raggiungibile'; }

  private async load() {
    const [h, p] = await Promise.all([this.loadChanges(0), this.host.api('GET', `${API}/proposals`, { query: { status: 'all' } })]);
    if (!h) return;
    if (!p.ok) { this.fail(p); return; }
    this.props = p.data.proposals || [];
    if (!this.modules.length) {
      const m = await this.host.api('GET', `${API}/modules`);
      if (m.ok) this.modules = (m.data.modules || []).map((x: any) => x.module).sort();
    }
  }

  private async loadChanges(offset: number): Promise<boolean> {
    const query: Record<string, any> = { limit: 50, offset };
    if (this.actor) query.actor = this.actor;
    if (this.module) query.module = this.module;
    const r = await this.host.api('GET', `${API}/history`, { query });
    if (!r.ok) {
      if (offset) { this.host.toast(r.error || 'Non caricato', 'danger'); return false; }
      this.fail(r); return false;
    }
    this.error = '';
    this.rows = offset ? [...(this.rows || []), ...r.data.items] : r.data.items;
    this.next = r.data.next_offset; this.total = r.data.total;
    return true;
  }

  private filter(k: 'actor' | 'module', v: string) { (this as any)[k] = v; this.rows = null; this.loadChanges(0); }

  private async undo(row: any) {
    const ok = await this.host.confirm('Annullare la modifica?',
      `«${row.label}» torna a ${val(row.old_value)}. Anche l'annullamento finisce nel registro.`, { label: 'Annulla modifica' });
    if (!ok) return;
    this.busy = `u${row.id}`;
    const r = await this.host.api('POST', `${API}/key/${encodeURIComponent(row.key)}/undo`,
      { body: { scope: row.scope, scope_id: row.scope_id, actor: 'user' } });
    this.busy = '';
    if (!r.ok) { this.host.toast(r.error || 'Non annullata', 'danger'); return; }
    this.host.toast(`«${row.label}» annullata`, 'success');
    this.load();
  }

  private async decide(p: any, approve: boolean) {
    this.busy = `p${p.proposal_id}`;
    const r = await this.host.api('POST', `${API}/proposals/${encodeURIComponent(p.proposal_id)}/${approve ? 'approve' : 'reject'}`,
      { body: { by: 'webui' } });
    this.busy = '';
    if (!r.ok) { this.host.toast(r.error || 'Non riuscito', 'danger'); this.load(); return; }
    this.host.toast(approve ? 'Proposta approvata' : 'Proposta rifiutata', approve ? 'success' : 'neutral');
    this.load();
  }

  private renderChange(r: any) {
    return html`<div class="r"><div class="grow col" style="gap:3px">
        <div class="row wrap"><span class="t">${r.label}</span><span class="small muted">${r.module}</span>
          ${KIND[r.kind] ? html`<hxk-badge tone=${r.kind === 'approved' ? 'success' : 'neutral'}>${KIND[r.kind]}</hxk-badge>` : nothing}
          ${r.scope !== 'system' ? html`<hxk-badge tone="info">${SCOPE[r.scope] || r.scope}${r.scope_id && r.scope !== 'profile' ? ` ${r.scope_id}` : ''}</hxk-badge>` : nothing}</div>
        <div class="ch"><span class="old">${val(r.old_value)}</span> → <b>${val(r.new_value)}</b></div>
        <div class="small muted">${when(r.created_at)} · ${who(r.actor)}${r.reason && r.kind !== 'undo' ? ` · ${r.reason}` : ''}</div>
      </div>
      ${r.undoable ? html`<hxk-button size="sm" variant="ghost" icon="undo" ?loading=${this.busy === `u${r.id}`} @click=${() => this.undo(r)}>Annulla</hxk-button>` : nothing}
    </div>`;
  }

  private renderProposal(p: any) {
    const st = PROPOSAL[p.status] || { text: p.status, tone: 'neutral' };
    const pending = p.status === 'pending';
    return html`<div class="r"><div class="grow col" style="gap:3px">
        <div class="row wrap"><span class="t">${p.label || p.key}</span><hxk-badge tone=${st.tone}>${st.text}</hxk-badge></div>
        <div class="ch">→ <b>${val(p.value)}</b></div>
        ${p.reason ? html`<div class="small">${p.reason}</div>` : nothing}
        <div class="small muted">${when(p.created_at)} · proposta da ${who(p.proposer)}
          ${p.decided_at ? html` · ${st.text} ${when(p.decided_at)}${p.decided_by ? ` (${who(p.decided_by)})` : ''}` : nothing}</div>
      </div>
      ${pending ? html`<div class="acts">
        <hxk-button size="sm" variant="primary" icon="check" ?loading=${this.busy === `p${p.proposal_id}`} @click=${() => this.decide(p, true)}>Approva</hxk-button>
        <hxk-button size="sm" variant="ghost" @click=${() => this.decide(p, false)}>Rifiuta</hxk-button></div>` : nothing}
    </div>`;
  }

  render() {
    if (this.error) return html`<div class="page"><h1>Registro</h1><hxk-state kind="offline" text=${this.error}></hxk-state></div>`;
    const pending = (this.props || []).filter(p => p.status === 'pending');
    const props = (this.props || []).filter(p => !this.module || String(p.key || '').startsWith(`${this.module}.`));
    return html`<div class="page">
      <div class="head"><h1>Registro</h1><span class="sub">Chi ha cambiato le impostazioni, quando e come</span></div>
      ${pending.length ? html`<hxk-card heading="Da confermare" subtitle="Nessuna proposta cambia qualcosa senza il tuo sì">
        ${pending.map(p => this.renderProposal(p))}</hxk-card>` : nothing}
      <div class="row wrap">
        <div class="chips grow">
          <button class="chip" aria-pressed=${this.tab === 'changes'} @click=${() => (this.tab = 'changes')}>Modifiche</button>
          <button class="chip" aria-pressed=${this.tab === 'proposals'} @click=${() => (this.tab = 'proposals')}>Proposte</button>
        </div>
        ${this.modules.length ? html`<select aria-label="Modulo" @change=${(e: any) => this.filter('module', e.target.value)}>
          <option value="">Tutti i moduli</option>${this.modules.map(m => html`<option value=${m} ?selected=${this.module === m}>${m}</option>`)}</select>` : nothing}
      </div>
      ${this.tab === 'changes' ? html`
        <div class="chips">${WHO_FILTERS.map(f => html`<button class="chip" aria-pressed=${this.actor === f.id} @click=${() => this.filter('actor', f.id)}>${f.label}</button>`)}</div>
        ${this.rows === null ? html`<hxk-state kind="loading"></hxk-state>`
          : this.rows.length ? html`<div class="card">${this.rows.map(r => this.renderChange(r))}
              ${this.next !== null ? html`<div style="padding-top:8px"><hxk-button size="sm" @click=${() => this.loadChanges(this.next!)}>Carica altre (${this.total - this.rows.length})</hxk-button></div>` : nothing}</div>`
          : html`<hxk-state kind="empty" text="Nessuna modifica registrata con questo filtro"></hxk-state>`}
        <p class="small muted">Per ogni impostazione restano le ultime modifiche. «Annulla» riporta il valore di prima, come «Annulla ultima» in Impostazioni.</p>`
      : this.props === null ? html`<hxk-state kind="loading"></hxk-state>`
        : props.length ? html`<div class="card">${props.map(p => this.renderProposal(p))}</div>`
        : html`<hxk-state kind="empty" text="Nessuna proposta"></hxk-state>`}
    </div>`;
  }
}
