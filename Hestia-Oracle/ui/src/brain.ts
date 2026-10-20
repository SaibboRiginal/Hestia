/**
 * <oracle-brain> — "Cervello": what Oracle does inside. Recent turns (route, domains, tools, model/provider, ms,
 * tokens), LLM use today per use case/model, tokens and cost per day, rolling stats per use case, Claude Code.
 * Reads GET /api/ui/activity · /api/ui/stats · /api/ui/code. Numbers are counted since Oracle started (in memory).
 * Tabs «Uso» (<oracle-usage>, calls kept in Archive) and «Modelli» (<oracle-models>, providers/chains/use cases).
 */
import { HestiaElement, html, css, nothing } from '@hestia/webui-sdk';
import { API, ROUTES, ago, cost, dayLabel, ms, num, when } from './util';

export class OracleBrain extends HestiaElement {
  static properties = { ...HestiaElement.properties, activity: { state: true }, stats: { state: true },
                        code: { state: true }, error: { state: true }, loading: { state: true }, tab: { state: true } };
  declare activity: any; declare stats: any; declare code: any; declare error: string; declare loading: boolean;
  declare tab: string;
  private timer: number | undefined;

  static styles = [...HestiaElement.styles, css`
    .head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    .sub { color: var(--text-3); font-size: 13px; }
    .cols { display: grid; gap: 16px; grid-template-columns: repeat(auto-fit, minmax(min(100%, 360px), 1fr)); }
    .turn { display: flex; flex-direction: column; gap: 4px; padding: 10px 0; border-top: 1px solid var(--border); }
    .turn:first-child { border-top: 0; padding-top: 0; }
    .line { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
    .chip { font-size: 11.5px; padding: 1px 7px; border-radius: var(--radius-full); background: var(--surface-2); color: var(--text-2);
      white-space: nowrap; }
    .chip.ko { background: var(--danger-soft); color: var(--danger); }
    .chip.w { background: var(--warning-soft); color: var(--warning); }
    .row2 { display: flex; justify-content: space-between; gap: 10px; padding: 7px 0; border-top: 1px solid var(--border); }
    .row2:first-child { border-top: 0; }
    .num { font-variant-numeric: tabular-nums; white-space: nowrap; text-align: right; }
    .preview { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .note { font-size: 12px; color: var(--text-3); }
    .tabs { display: flex; gap: 4px; margin: 4px 0 14px; border-bottom: 1px solid var(--border); overflow-x: auto; }
    .tabs button { font: inherit; background: none; border: 0; padding: 8px 12px; color: var(--text-2); cursor: pointer;
      border-bottom: 2px solid transparent; white-space: nowrap; }
    .tabs button[aria-selected=true] { color: var(--text); border-bottom-color: var(--accent); font-weight: 600; }
  `];

  constructor() { super(); this.activity = null; this.stats = null; this.code = null; this.error = ''; this.loading = false; this.tab = 'attivita'; }

  connectedCallback() {
    super.connectedCallback();
    this.load();
    this.onHost('refresh', () => this.load());
    this.onHost('visible', () => this.load());
    this.timer = window.setInterval(() => { if (!document.hidden && this.tab === 'attivita') this.load(); }, 30000);
  }
  disconnectedCallback() { super.disconnectedCallback(); window.clearInterval(this.timer); }

  private async load() {
    this.loading = true;
    const [a, s, c] = await Promise.all([
      this.host.api('GET', `${API}/activity`, { query: { limit: 40 } }),
      this.host.api('GET', `${API}/stats`, { query: { days: 14 } }),
      this.host.api('GET', `${API}/code`),
    ]);
    this.loading = false;
    if (!a.ok && !s.ok) { this.error = a.status === 0 ? 'Oracle non raggiungibile' : a.error || 'Oracle non raggiungibile'; return; }
    this.error = '';
    this.activity = a.ok ? a.data : null;
    this.stats = s.ok ? s.data : null;
    this.code = c.ok ? c.data : null;
  }

  private kpis() {
    const t = this.stats?.today || {};
    const turnsToday = (this.activity?.turns || []).filter((r: any) => new Date(r.at * 1000).toDateString() === new Date().toDateString()).length;
    return html`<hxk-stat .items=${[
      { label: 'Richieste oggi', value: turnsToday, hint: 'Chat concluse oggi (ultime 40 viste)' },
      { label: 'Chiamate ai modelli', value: num(t.calls) },
      { label: 'Token in / out', value: `${num(t.input_tokens)} / ${num(t.output_tokens)}` },
      { label: 'Costo oggi', value: cost(t.cost_usd), hint: 'Solo provider cloud che riportano il costo' },
    ]}></hxk-stat>`;
  }

  private renderDays() {
    const days: any[] = this.stats?.days || [];
    if (!days.length) return nothing;
    const labels = days.map(d => dayLabel(d.day));
    const anyCost = days.some(d => d.cost_usd > 0);
    return html`<hxk-card heading="Token per giorno" subtitle="Ultimi 14 giorni · da quando Oracle è partito il ${when(this.stats.since)}">
      <hxk-chart type="bar" unit="token" .labels=${labels} .series=${[
        { name: 'In ingresso', values: days.map(d => d.input_tokens) },
        { name: 'In uscita', values: days.map(d => d.output_tokens) },
      ]}></hxk-chart>
      ${anyCost ? html`<div style="margin-top:10px"><div class="small muted">Costo ($)</div>
        <hxk-chart type="line" unit="$" .height=${110} .labels=${labels} .series=${[{ name: 'Costo', values: days.map(d => d.cost_usd) }]}></hxk-chart></div>` : nothing}
    </hxk-card>`;
  }

  private renderToday() {
    const rows: any[] = this.stats?.today_by_model || [];
    return html`<hxk-card heading="Oggi per caso d'uso e modello">
      ${rows.length ? rows.map(r => html`<div class="row2"><div class="grow">
          <div class="truncate"><b>${r.label || r.use_case}</b></div>
          <div class="small muted truncate">${r.provider} · ${r.model}</div></div>
        <div class="num"><div>${num(r.calls)} chiamate</div>
          <div class="small muted">${num(r.input_tokens)} / ${num(r.output_tokens)} token${r.cost_usd ? ` · ${cost(r.cost_usd)}` : ''}</div></div></div>`)
        : html`<hxk-state kind="empty" text="Nessuna chiamata ai modelli oggi."></hxk-state>`}
    </hxk-card>`;
  }

  private renderUseCases() {
    const rows: any[] = this.stats?.use_cases || [];
    if (!rows.length) return nothing;
    return html`<hxk-card heading="Come rispondono i modelli" subtitle="Media delle ultime chiamate per caso d'uso">
      ${rows.map(r => html`<div class="row2"><div class="grow">
          <div class="truncate"><b>${r.label || r.use_case}</b> <span class="small muted">${r.calls} chiamate</span></div>
          <div class="small muted truncate">${r.provider} · ${r.model}</div></div>
        <div class="num small"><div>prompt ~${num(r.avg_prompt_tokens)} token · cache ${r.cache_hit_pct}%${r.cache_estimated ? '≈' : ''}</div>
          <div class="muted">${r.tokens_per_second ? `${r.tokens_per_second} token/s · ` : ''}${r.avg_load_ms ? `caricamento ${ms(r.avg_load_ms)} · ` : ''}ultima ${when(r.last_at)}</div></div></div>`)}
    </hxk-card>`;
  }

  private renderTurn(t: any) {
    const route = ROUTES[t.route] || { label: t.route, tone: 'neutral' };
    return html`<div class="turn">
      <div class="line"><span class="small muted">${when(t.at)}</span>
        <hxk-badge tone=${route.tone}>${route.label}</hxk-badge>
        ${t.client ? html`<span class="chip">${t.client}</span>` : nothing}
        ${(t.domains || []).map((d: string) => html`<span class="chip">${d}</span>`)}
        <span class="grow"></span><span class="small muted num">${ms(t.ms)}</span></div>
      ${t.preview ? html`<div class="preview" title=${t.preview}>${t.preview}</div>` : nothing}
      ${(t.tools || []).length ? html`<div class="line">${t.tools.map((x: any) => html`<span class=${x.ok ? (x.writes ? 'chip w' : 'chip') : 'chip ko'}
          title=${x.ok ? (x.writes ? 'ha modificato qualcosa' : 'lettura') : 'non riuscito'}>${x.ok ? '' : '✕ '}${x.tool}</span>`)}</div>` : nothing}
      <div class="small muted">${t.provider} · ${t.model}${t.usage?.calls ? ` · ${t.usage.calls} chiamate · ${num(t.usage.input_tokens)} / ${num(t.usage.output_tokens)} token` : ''}${t.usage?.cost_usd ? ` · ${cost(t.usage.cost_usd)}` : ''}</div>
    </div>`;
  }

  private renderActivity() {
    const a = this.activity;
    if (!a) return html`<hxk-card heading="Ultime richieste"><hxk-state kind="error" text="Attività non disponibile"></hxk-state></hxk-card>`;
    const turns: any[] = a.turns || [];
    return html`<hxk-card heading="Ultime richieste" subtitle="Ultima chat dell'utente: ${ago(a.idle_seconds)}">
      ${turns.length ? turns.map(t => this.renderTurn(t))
        : html`<hxk-state kind="empty" text="Nessuna richiesta da quando Oracle è partito."></hxk-state>`}
    </hxk-card>`;
  }

  private renderCode() {
    const c = this.code;
    if (!c) return html`<hxk-card heading="Claude Code"><hxk-state kind="error" text="Stato non disponibile"></hxk-state></hxk-card>`;
    const runs: any[] = c.runs || [];
    return html`<hxk-card heading="Claude Code" subtitle="Motore di sviluppo di Forge (abbonamento Claude)">
      <div class="line" style="margin-bottom:8px">
        <hxk-badge tone=${c.available ? 'success' : 'warning'}>${c.available ? 'pronto' : 'non pronto'}</hxk-badge>
        ${c.available && c.model ? html`<span class="chip">modello ${c.model}</span>` : nothing}
        ${c.running ? html`<hxk-badge tone="info">${c.running} in corso</hxk-badge>` : nothing}</div>
      ${c.available ? nothing : html`<div class="note">${c.detail}</div>`}
      ${runs.map(r => html`<div class="row2"><div class="grow"><div class="truncate">${r.task || 'task'}</div>
          <div class="small muted">${when(r.started_at)}${r.error ? ` · ${r.error}` : ''}</div></div>
        <div class="num small">${r.state === 'running' ? html`<hxk-badge tone="info">in corso</hxk-badge>`
          : html`<hxk-badge tone=${r.ok ? 'success' : 'danger'}>${r.ok ? 'ok' : 'fallito'}</hxk-badge>`}
          <div class="muted">${r.state === 'running' ? '' : `${ms(r.ms)} · ${r.turns} turni${r.cost_usd ? ` · ${cost(r.cost_usd)}` : ''}`}</div></div></div>`)}
      ${!runs.length && c.available ? html`<div class="note">Nessun lavoro da quando Oracle è partito.</div>` : nothing}
    </hxk-card>`;
  }

  private tabs() {
    const items = [['attivita', 'Attività'], ['uso', 'Uso'], ['modelli', 'Modelli']];
    return html`<div class="tabs" role="tablist">${items.map(([id, label]) => html`<button role="tab" aria-selected=${this.tab === id}
      @click=${() => { this.tab = id; }}>${label}</button>`)}</div>`;
  }

  private activityTab() {
    if (this.error) return html`<hxk-state kind="offline" text=${this.error} @retry=${() => this.load()}></hxk-state>`;
    if (!this.activity && !this.stats) return html`<hxk-state kind="loading"></hxk-state>`;
    return html`${this.stats ? this.kpis() : nothing}
      <div class="cols">
        <div class="col" style="gap:16px">${this.renderActivity()}</div>
        <div class="col" style="gap:16px">${this.renderDays()}${this.stats ? this.renderToday() : nothing}${this.renderUseCases()}${this.renderCode()}</div>
      </div>
      <p class="note">I numeri di questa scheda sono in memoria: si azzerano quando Oracle riparte. La scheda Uso li conserva.</p>`;
  }

  render() {
    return html`<div class="page">
      <div class="head"><h1>Cervello</h1><span class="sub">Cosa fa Oracle: richieste, modelli, token</span><span class="grow"></span>
        ${this.tab === 'attivita' ? html`<hxk-button variant="ghost" icon="refresh" ?loading=${this.loading} @click=${() => this.load()}>Aggiorna</hxk-button>` : nothing}</div>
      ${this.tabs()}
      ${this.tab === 'uso' ? html`<oracle-usage .host=${this.host}></oracle-usage>`
        : this.tab === 'modelli' ? html`<oracle-models .host=${this.host}></oracle-models>` : this.activityTab()}
    </div>`;
  }
}
