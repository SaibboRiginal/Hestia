/**
 * <oracle-usage> — Cervello tab «Uso»: every LLM call kept in Archive (dossier 2026-10-19-oracle-a-blocchi §E).
 * Cards per module (calls, calls/hour, tokens, cache, cost, fallbacks), calls per day, sessions (tap → their calls),
 * which chain step answered. Reads GET /api/ui/usage?group=…&days=… and /api/ui/usage/calls.
 */
import { HestiaElement, html, css, nothing } from '@hestia/webui-sdk';
import { API, cost, dayLabel, ms, num } from './util';

const PERIODS = [{ value: '1', label: 'Oggi' }, { value: '7', label: '7 giorni' }, { value: '30', label: '30 giorni' }];

function pct(part: number, whole: number): string {
  return whole ? `${Math.round((100 * part) / whole)}%` : '–';
}

function at(iso: string | null | undefined): string {
  if (!iso) return '–';
  const d = new Date(iso);
  return d.toLocaleString('it-IT', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}

export class OracleUsage extends HestiaElement {
  static properties = { ...HestiaElement.properties, days: { state: true }, data: { state: true }, error: { state: true },
                        session: { state: true }, calls: { state: true } };
  declare days: string; declare data: any; declare error: string; declare session: string; declare calls: any[] | null;

  static styles = [...HestiaElement.styles, css`
    .bar { display: flex; gap: 8px; align-items: end; flex-wrap: wrap; margin-bottom: 12px; }
    .mods { display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(min(100%, 260px), 1fr)); }
    .kv { display: flex; justify-content: space-between; gap: 8px; font-size: 13px; padding: 2px 0; }
    .kv span:last-child { font-variant-numeric: tabular-nums; }
    .row2 { display: flex; justify-content: space-between; gap: 10px; padding: 7px 0; border-top: 1px solid var(--border); }
    .row2:first-child { border-top: 0; }
    .row2.click { cursor: pointer; }
    .num { font-variant-numeric: tabular-nums; white-space: nowrap; text-align: right; }
    .cols { display: grid; gap: 16px; grid-template-columns: repeat(auto-fit, minmax(min(100%, 360px), 1fr)); margin-top: 16px; }
  `];

  constructor() { super(); this.days = '7'; this.data = null; this.error = ''; this.session = ''; this.calls = null; }

  connectedCallback() {
    super.connectedCallback();
    this.load();
    this.onHost('refresh', () => this.load());
  }

  async load() {
    const q = (group: string) => this.host.api('GET', `${API}/usage`, { query: { group, days: this.days } });
    const [mod, day, ses, step] = await Promise.all([q('module'), q('day'), q('session'), q('step')]);
    if (!mod.ok) { this.error = mod.error || 'Uso non disponibile (Archive)'; return; }
    this.error = '';
    this.data = { modules: mod.data.rows || [], days: day.ok ? day.data.rows : [], sessions: ses.ok ? ses.data.rows : [],
                  steps: step.ok ? step.data.rows : [] };
  }

  private async openSession(id: string) {
    this.session = id; this.calls = null;
    const r = await this.host.api('GET', `${API}/usage/calls`, { query: { session_id: id, days: this.days, limit: 200 } });
    this.calls = r.ok ? r.data.rows || [] : [];
  }

  private totals() {
    const rows: any[] = this.data?.modules || [];
    const sum = (k: string) => rows.reduce((a, r) => a + (r[k] || 0), 0);
    const calls = sum('calls');
    return html`<hxk-stat .items=${[
      { label: 'Chiamate', value: num(calls), hint: `${num(calls / (Number(this.days) * 24))} all'ora in media` },
      { label: 'Token in / out', value: `${num(sum('input_tokens'))} / ${num(sum('output_tokens'))}` },
      { label: 'Dalla cache', value: pct(sum('cached_tokens'), sum('input_tokens')), hint: 'Parte del prompt già in cache' },
      { label: 'Costo', value: cost(sum('cost_usd')), hint: 'Riportato dal fornitore o dai Prezzi dei modelli' },
      { label: 'Ripieghi', value: num(sum('fallbacks')), hint: 'Risposte date da un modello dopo il primo della catena' },
    ]}></hxk-stat>`;
  }

  private module(r: any) {
    const hours = Number(this.days) * 24;
    return html`<hxk-card heading=${r.module}>
      <div class="kv"><span class="muted">Chiamate</span><span>${num(r.calls)} · ${num(r.calls / hours)}/ora</span></div>
      <div class="kv"><span class="muted">Token in / out</span><span>${num(r.input_tokens)} / ${num(r.output_tokens)}</span></div>
      <div class="kv"><span class="muted">Dalla cache</span><span>${pct(r.cached_tokens, r.input_tokens)}</span></div>
      <div class="kv"><span class="muted">Prompt più grande</span><span>${num(r.max_input_tokens)}${r.context_window ? ` su ${num(r.context_window)}` : ''}</span></div>
      <div class="kv"><span class="muted">Tempo medio</span><span>${ms(r.avg_duration_ms)}</span></div>
      <div class="kv"><span class="muted">Costo</span><span>${cost(r.cost_usd)}</span></div>
      ${r.fallbacks || r.errors ? html`<div class="kv"><span class="muted">Ripieghi · errori · quota</span>
        <span>${num(r.fallbacks)} · ${num(r.errors)} · ${num(r.quota)}</span></div>` : nothing}
    </hxk-card>`;
  }

  private daysChart() {
    const rows: any[] = this.data?.days || [];
    if (rows.length < 2) return nothing;
    return html`<hxk-card heading="Chiamate per giorno">
      <hxk-chart type="bar" unit="chiamate" .labels=${rows.map(r => dayLabel(r.day))} .series=${[
        { name: 'Riuscite', values: rows.map(r => r.ok) }, { name: 'Non riuscite', values: rows.map(r => r.errors) }]}></hxk-chart>
    </hxk-card>`;
  }

  private sessions() {
    const rows: any[] = (this.data?.sessions || []).filter((r: any) => r.session_id).slice(0, 30);
    return html`<hxk-card heading="Conversazioni" subtitle="Tocca una conversazione per vedere le sue chiamate">
      ${rows.length ? rows.map(r => html`<div class="row2 click" @click=${() => this.openSession(r.session_id)}>
          <div class="grow"><div class="truncate"><b>${r.client || 'chat'}</b> <span class="small muted">${r.session_id}</span></div>
            <div class="small muted">ultima ${at(r.last_at)}</div></div>
          <div class="num small"><div>${num(r.calls)} chiamate · ${cost(r.cost_usd)}</div>
            <div class="muted">${num(r.input_tokens)} / ${num(r.output_tokens)} token · cache ${pct(r.cached_tokens, r.input_tokens)}</div></div></div>`)
        : html`<hxk-state kind="empty" text="Nessuna conversazione nel periodo."></hxk-state>`}
    </hxk-card>`;
  }

  private sessionCalls() {
    if (!this.session) return nothing;
    return html`<hxk-card heading="Chiamate della conversazione" subtitle=${this.session}>
      <hxk-button slot="actions" variant="ghost" icon="x" @click=${() => { this.session = ''; this.calls = null; }}>Chiudi</hxk-button>
      ${this.calls === null ? html`<hxk-state kind="loading"></hxk-state>` : this.calls.map(c => html`<div class="row2">
          <div class="grow"><div class="truncate"><b>${c.use_case}</b> <span class="small muted">${c.chain || ''}${c.step ? ` · passo ${c.step + 1}` : ''}</span></div>
            <div class="small muted truncate">${at(c.at)} · ${c.provider} · ${c.model}</div></div>
          <div class="num small"><div>${c.outcome === 'ok' ? `${num(c.input_tokens)} / ${num(c.output_tokens)} token` : html`<hxk-badge tone="danger">${c.outcome}</hxk-badge>`}</div>
            <div class="muted">${ms(c.duration_ms)}${c.cost_usd ? ` · ${cost(c.cost_usd)}` : ''}${c.cost_kind === 'abbonamento' ? ' abbonamento' : ''}</div></div></div>`)}
    </hxk-card>`;
  }

  private steps() {
    const rows: any[] = this.data?.steps || [];
    if (!rows.length) return nothing;
    return html`<hxk-card heading="Chi ha risposto" subtitle="Per uso: quale passo della catena e quante volte">
      ${rows.slice(0, 40).map(r => html`<div class="row2"><div class="grow">
          <div class="truncate"><b>${r.use_case}</b> <span class="small muted">${r.chain || ''} · passo ${(r.step || 0) + 1}</span></div>
          <div class="small muted truncate">${r.provider} · ${r.model}</div></div>
        <div class="num small"><div>${num(r.ok)} risposte</div>
          <div class="muted">${r.quota ? `${num(r.quota)} senza quota · ` : ''}${r.errors - r.quota > 0 ? `${num(r.errors - r.quota)} errori` : ''}</div></div></div>`)}
    </hxk-card>`;
  }

  render() {
    return html`<div class="bar">
        <hxk-field type="enum" label="Periodo" .options=${PERIODS} .value=${this.days}
          @change=${(e: CustomEvent) => { this.days = String(e.detail); this.load(); }}></hxk-field></div>
      ${this.error ? html`<hxk-state kind="error" text=${this.error} @retry=${() => this.load()}></hxk-state>`
        : !this.data ? html`<hxk-state kind="loading"></hxk-state>`
        : html`${this.totals()}
          <div class="mods" style="margin-top:12px">${this.data.modules.length ? this.data.modules.map((r: any) => this.module(r))
            : html`<hxk-state kind="empty" text="Nessuna chiamata ai modelli nel periodo."></hxk-state>`}</div>
          <div class="cols"><div class="col" style="gap:16px">${this.sessionCalls()}${this.sessions()}</div>
            <div class="col" style="gap:16px">${this.daysChart()}${this.steps()}</div></div>`}`;
  }
}
