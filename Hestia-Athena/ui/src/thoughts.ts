/**
 * <athena-thoughts> — "Pensieri": every Athena cycle, observe → think → gate (5 factors) → act, with accepted /
 * discarded candidates and why; open commitments; «Pensa ora» runs a cycle now and the list refreshes when done.
 * Reads GET /api/athena/thinking/summary · /api/athena/commitments; POST /api/athena/think,
 * POST /api/athena/commitments/{id}/resolve.
 */
import { HestiaElement, html, css, nothing } from '@hestia/webui-sdk';
import { API, FACTORS, KINDS, OUTCOMES, ago, pct, secs, when } from './util';

export class AthenaThoughts extends HestiaElement {
  static properties = { ...HestiaElement.properties, data: { state: true }, commitments: { state: true },
                        error: { state: true }, thinking: { state: true }, open: { state: true } };
  declare data: any; declare commitments: any[] | null; declare error: string; declare thinking: boolean;
  declare open: Record<string, boolean>;
  private poll: number | undefined;

  static styles = [...HestiaElement.styles, css`
    .head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    .sub { color: var(--text-3); font-size: 13px; }
    .line { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
    .chip { font-size: 11.5px; padding: 1px 7px; border-radius: var(--radius-full); background: var(--surface-2); color: var(--text-2); white-space: nowrap; }
    .chip.bad { background: var(--danger-soft); color: var(--danger); }
    .cycle { display: flex; flex-direction: column; gap: 10px; }
    .steps { display: grid; gap: 8px; grid-template-columns: repeat(auto-fit, minmax(min(100%, 200px), 1fr)); }
    .step { background: var(--surface-2); border-radius: var(--radius-md); padding: 8px 10px; font-size: 13px; }
    .step b { display: block; font-size: 11.5px; text-transform: uppercase; letter-spacing: .04em; color: var(--text-3); margin-bottom: 2px; }
    .cand { border: 1px solid var(--border); border-radius: var(--radius-md); padding: 10px 12px; display: flex; flex-direction: column; gap: 6px; }
    .cand.ok { border-color: var(--success); }
    .title { font-weight: 600; }
    .factors { display: grid; grid-template-columns: 76px 1fr 40px; gap: 3px 8px; align-items: center; font-size: 12px; }
    .bar { height: 6px; border-radius: 3px; background: var(--surface-3, var(--surface-2)); overflow: hidden; }
    .bar i { display: block; height: 100%; background: var(--accent); border-radius: 3px; }
    .bar.inv i { background: var(--warning); }
    .score { display: flex; align-items: center; gap: 8px; font-size: 12.5px; }
    .gauge { position: relative; flex: 1; height: 8px; border-radius: 4px; background: var(--surface-2); }
    .gauge i { position: absolute; left: 0; top: 0; bottom: 0; border-radius: 4px; }
    .gauge .thr { position: absolute; top: -3px; bottom: -3px; width: 2px; background: var(--text-2); }
    .num { font-variant-numeric: tabular-nums; white-space: nowrap; }
    .muted2 { color: var(--text-2); font-size: 13px; }
    .comm { display: flex; gap: 10px; align-items: flex-start; padding: 8px 0; border-top: 1px solid var(--border); }
    .comm:first-child { border-top: 0; }
    .link { background: none; border: 0; padding: 0; color: var(--accent); cursor: pointer; font: inherit; font-size: 12.5px; }
  `];

  constructor() { super(); this.data = null; this.commitments = null; this.error = ''; this.thinking = false; this.open = {}; }

  connectedCallback() {
    super.connectedCallback();
    this.load();
    this.onHost('refresh', () => this.load());
    this.onHost('visible', () => this.load());
  }
  disconnectedCallback() { super.disconnectedCallback(); window.clearTimeout(this.poll); }

  private async load(): Promise<any> {
    const [t, c] = await Promise.all([
      this.host.api('GET', `${API}/thinking/summary`, { query: { limit: 15 } }),
      this.host.api('GET', `${API}/commitments`, { query: { limit: 20 } }),
    ]);
    if (!t.ok) { this.error = t.status === 0 ? 'Athena non raggiungibile' : t.error || 'Athena non raggiungibile'; return null; }
    this.error = '';
    this.data = t.data;
    this.commitments = c.ok ? c.data.commitments || [] : null;
    if (t.data.running && !this.thinking) this.watch(t.data.cycles?.[0]?.record_id);
    return t.data;
  }

  /** Poll until the running cycle ends, then show it. */
  private watch(before?: string, tries = 0) {
    this.thinking = true;
    window.clearTimeout(this.poll);
    this.poll = window.setTimeout(async () => {
      const d = await this.load();
      if (d && !d.running) {
        this.thinking = false;
        const fresh = d.cycles?.[0];
        if (fresh && fresh.record_id !== before) {
          const n = (fresh.candidates || []).filter((x: any) => x.accepted).length;
          this.host.toast(n ? `Athena ha pensato: ${n} ${n === 1 ? 'idea utile' : 'idee utili'}` : 'Athena ha pensato: niente da proporre ora', n ? 'success' : 'info');
          this.open = { ...this.open, [fresh.record_id]: true };
        }
        return;
      }
      if (tries < 60) this.watch(before, tries + 1); else this.thinking = false;
    }, 3000);
  }

  private async thinkNow() {
    const before = this.data?.cycles?.[0]?.record_id;
    const r = await this.host.api('POST', `${API}/think`);
    if (!r.ok) { this.host.toast(r.error || 'Athena non raggiungibile', 'danger'); return; }
    if (r.data?.status === 'busy') this.host.toast('Athena sta già pensando', 'info');
    else this.host.toast('Athena sta pensando…', 'info');
    this.watch(before);
  }

  private async resolve(c: any, status: 'resolved' | 'dismissed') {
    const r = await this.host.api('POST', `${API}/commitments/${encodeURIComponent(c.brief_id)}/resolve`, { body: { status } });
    if (!r.ok) { this.host.toast(r.error || 'Non riuscito', 'danger'); return; }
    this.load();
  }

  private factors(c: any) {
    const s = c.signals || {};
    const w = this.data?.weights || {};
    return html`<div class="factors">${FACTORS.map(f => html`
      <span title=${`peso ${Math.round((w[f.key] || 0) * 100)}%${f.inverse ? ' (conta al contrario: meno disturbo = meglio)' : ''}`}>${f.label}</span>
      <span class=${f.inverse ? 'bar inv' : 'bar'}><i style="width:${pct(s[f.key])}"></i></span>
      <span class="num muted">${pct(s[f.key])}</span>`)}</div>`;
  }

  private candidate(c: any, threshold: number) {
    const out = OUTCOMES[c.outcome] || (c.accepted ? OUTCOMES.emitted : OUTCOMES.discarded);
    const score = Number(c.score || 0);
    return html`<div class=${c.accepted ? 'cand ok' : 'cand'}>
      <div class="line"><span class="title grow">${c.title || 'Senza titolo'}</span>
        <hxk-badge tone=${c.accepted ? 'success' : 'neutral'}>${c.accepted ? 'accettata' : 'scartata'}</hxk-badge></div>
      <div class="line"><span class="chip">${KINDS[c.kind] || c.kind}</span>${c.domain ? html`<span class="chip">${c.domain}</span>` : nothing}
        ${c.priority && c.priority !== 'normal' ? html`<span class="chip">priorità ${c.priority}</span>` : nothing}
        ${c.kind === 'setting' && c.setting_key ? html`<span class="chip">${c.setting_key} → ${c.setting_value}</span>` : nothing}</div>
      ${c.summary ? html`<div class="muted2">${c.summary}</div>` : nothing}
      ${c.reasoning ? html`<div class="small muted">Perché: ${c.reasoning}</div>` : nothing}
      <div class="score"><span class="num">${score.toFixed(2)}</span>
        <span class="gauge" title="Punteggio e soglia"><i style="width:${pct(score)};background:${c.accepted ? 'var(--success)' : 'var(--text-3)'}"></i>
          <span class="thr" style="left:${pct(threshold)}"></span></span>
        <span class="num muted">soglia ${threshold.toFixed(2)}</span></div>
      ${this.factors(c)}
      <div class="line">${c.gate_reason ? html`<span class="small muted grow">${c.gate_reason}</span>` : html`<span class="grow"></span>`}
        <hxk-badge tone=${out.tone}>${out.label}</hxk-badge></div>
    </div>`;
  }

  private cycle(r: any, first: boolean) {
    const o = r.observation || {};
    const cands: any[] = r.candidates || [];
    const accepted = cands.filter(c => c.accepted).length;
    const isOpen = this.open[r.record_id] ?? first;
    const threshold = Number(r.threshold || this.data?.threshold || 0);
    const verdict = !cands.length ? 'nessuna idea' : `${accepted} accettate su ${cands.length}`;
    return html`<hxk-card>
      <div class="cycle">
        <div class="line"><b class="grow">${when(r.cycle_at)}</b>
          <hxk-badge tone=${r.trigger === 'manual' ? 'accent' : 'neutral'}>${r.trigger === 'manual' ? 'a richiesta' : 'automatico'}</hxk-badge>
          <hxk-badge tone=${accepted ? 'success' : 'neutral'}>${verdict}</hxk-badge>
          ${r.error ? html`<hxk-badge tone="danger">errore</hxk-badge>` : nothing}
          <button class="link" @click=${() => (this.open = { ...this.open, [r.record_id]: !isOpen })}>${isOpen ? 'Chiudi' : 'Dettagli'}</button></div>
        ${isOpen ? html`
          <div class="steps">
            <div class="step"><b>1 · Osserva</b>${o.services} servizi${o.unhealthy_services?.length
              ? html`, <span style="color:var(--danger)">${o.unhealthy_services.length} giù (${o.unhealthy_services.join(', ')})</span>` : ', tutti ok'}
              · ${o.recent_errors} errori nell'ultima ora${o.active_commitments ? ` · ${o.active_commitments} impegni aperti` : ''}
              ${(o.domains || []).length ? html`<div class="small muted">${o.domains.map((d: any) => `${d.domain}: ${d.recent} nuovi, ${d.pending} in sospeso`).join(' · ')}</div>` : nothing}
              ${(o.quality_issues || []).length ? html`<div class="small muted">Punti deboli: ${o.quality_issues.join(' · ')}</div>` : nothing}
              ${o.presence ? html`<div class="small muted">${o.presence}</div>` : nothing}</div>
            <div class="step"><b>2 · Pensa</b>${cands.length ? `${cands.length} ${cands.length === 1 ? 'idea' : 'idee'} dal modello` : 'Nessuna azione utile trovata'}
              <div class="small muted">${secs(r.duration_ms)}</div></div>
            <div class="step"><b>3 · Filtra</b>punteggio su 5 fattori, soglia ${threshold.toFixed(2)}
              <div class="small muted">${verdict}</div></div>
            <div class="step"><b>4 · Agisce</b>${r.emitted_count ? `${r.emitted_count} inviate` : 'niente inviato'}
              ${r.error ? html`<div class="small" style="color:var(--danger)">${r.error}</div>` : nothing}</div>
          </div>
          ${cands.map(c => this.candidate(c, threshold))}` : nothing}
      </div></hxk-card>`;
  }

  private renderCommitments() {
    const list = this.commitments;
    if (list === null) return nothing;
    return html`<hxk-card heading="Impegni aperti" subtitle="Idee inviate che Athena tiene d'occhio finché non scadono">
      ${list.length ? list.map(c => html`<div class="comm"><div class="grow">
          <div><b>${c.title}</b> <span class="chip">${KINDS[c.kind] || c.kind}</span></div>
          ${c.summary ? html`<div class="small muted">${c.summary}</div>` : nothing}
          <div class="small muted">punteggio ${Number(c.score || 0).toFixed(2)} · scade ${when(c.expires_at)}</div></div>
        <div class="line"><hxk-button size="sm" variant="ghost" icon="check" @click=${() => this.resolve(c, 'resolved')}>Fatto</hxk-button>
          <hxk-button size="sm" variant="ghost" icon="x" @click=${() => this.resolve(c, 'dismissed')}>Ignora</hxk-button></div></div>`)
        : html`<div class="small muted">Nessun impegno aperto.</div>`}
    </hxk-card>`;
  }

  render() {
    if (this.error) return html`<div class="page"><hxk-state kind="offline" text=${this.error} @retry=${() => this.load()}></hxk-state></div>`;
    const d = this.data;
    if (!d) return html`<div class="page"><hxk-state kind="loading"></hxk-state></div>`;
    const cycles: any[] = d.cycles || [];
    const last = cycles[0];
    return html`<div class="page">
      <div class="head"><h1>Pensieri</h1><span class="sub">Cosa pensa Athena quando sei libero</span><span class="grow"></span>
        <hxk-button variant="ghost" icon="refresh" @click=${() => this.load()}>Aggiorna</hxk-button>
        <hxk-button variant="primary" icon="play" ?loading=${this.thinking} @click=${() => this.thinkNow()}>${this.thinking ? 'Sta pensando…' : 'Pensa ora'}</hxk-button></div>
      <div class="line">
        <hxk-badge tone=${d.loop_enabled ? 'success' : 'warning'}>${d.loop_enabled ? `pensa da sola ogni ${Math.round(d.interval_seconds / 60)} min` : 'pensiero automatico spento'}</hxk-badge>
        ${d.strategist_enabled ? nothing : html`<hxk-badge tone="warning">ragionamento spento: nessuna idea</hxk-badge>`}
        <span class="chip">soglia ${Number(d.threshold).toFixed(2)}</span>
        ${last ? html`<span class="small muted">ultimo ciclo ${ago(last.cycle_at)}</span>` : nothing}</div>
      ${this.renderCommitments()}
      ${cycles.length ? cycles.map((r, i) => this.cycle(r, i === 0))
        : html`<hxk-state kind="empty" text="Nessun ciclo ancora da quando Athena è partita. Premi «Pensa ora»."></hxk-state>`}
      <p class="small muted">Punteggio = 30% urgenza + 25% utilità + 20% novità + 15% sicurezza + 10% (1 − disturbo). Le soglie e i tempi si cambiano in Impostazioni → Sistema → Athena.</p>
    </div>`;
  }
}
