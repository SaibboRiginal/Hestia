/**
 * <hephaestus-forge-widget> — "Forge": auto-development at a glance (active or paused, queue, running,
 * waiting for your review, Claude budget window). The only button is the existing manual brake
 * (POST /api/hephaestus/forge/pause, same switch as the Sviluppo page and Telegram), after a confirm.
 */
import { HestiaElement, html, css, nothing } from '@hestia/webui-sdk';
import { FORGE, PHASE, when } from './util';

export class HephaestusForgeWidget extends HestiaElement {
  static properties = { ...HestiaElement.properties, st: { state: true }, budget: { state: true }, counts: { state: true },
                        error: { state: true }, busy: { state: true } };
  declare st: any; declare budget: any; declare counts: Record<string, number>; declare error: string; declare busy: boolean;
  static styles = [...HestiaElement.styles, css`
    :host { display: block; height: 100%; }
    .w { display: flex; flex-direction: column; gap: 8px; height: 100%; padding: 2px; }
    .between { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
    .big { font-size: 22px; font-weight: 650; line-height: 1.1; }
    .nums { display: flex; gap: 14px; flex-wrap: wrap; }
    .n { display: flex; flex-direction: column; } .n b { font-size: 18px; font-variant-numeric: tabular-nums; }
  `];
  constructor() { super(); this.st = null; this.budget = null; this.counts = {}; this.error = ''; this.busy = false; }

  connectedCallback() {
    super.connectedCallback(); this.load();
    this.onHost('refresh', () => this.load()); this.onHost('visible', () => this.load());
  }

  private async load() {
    const [s, b, t] = await Promise.all([
      this.host.api('GET', `${FORGE}/status`),
      this.host.api('GET', `${FORGE}/claude-budget`),
      this.host.api('GET', `${FORGE}/tasks`, { query: { limit: 100 } }),
    ]);
    if (!s.ok) { this.error = s.status === 0 || !s.error ? 'Hephaestus non raggiungibile' : s.error; return; }
    this.error = ''; this.st = s.data; this.budget = b.ok ? b.data : null;
    const counts: Record<string, number> = {};
    for (const task of (t.ok ? t.data?.tasks || [] : [])) counts[task.state] = (counts[task.state] || 0) + 1;
    this.counts = counts;
  }

  private async togglePause() {
    const pause = !this.st?.paused;
    const ok = await this.host.confirm(pause ? 'Mettere in pausa lo sviluppo?' : 'Riprendere lo sviluppo?',
      pause ? 'Nessun task parte da solo finché non riprendi; quelli proposti restano lì.'
            : 'I task trattenuti durante la pausa restano da avviare a mano.', { label: pause ? 'Pausa' : 'Riprendi' });
    if (!ok) return;
    this.busy = true;
    const r = await this.host.api('POST', `${FORGE}/pause`, { body: { paused: pause, by: 'webui' } });
    this.busy = false;
    if (!r.ok) { this.host.toast(r.error || 'Non riuscito', 'danger'); return; }
    this.host.toast(pause ? 'Sviluppo in pausa' : 'Sviluppo ripreso', 'success');
    this.load();
  }

  render() {
    if (this.error) return html`<hxk-state kind="offline" text=${this.error}></hxk-state>`;
    const s = this.st;
    if (!s) return html`<hxk-state kind="loading"></hxk-state>`;
    const size = this.ctx?.size || 'm';
    const state = !s.enabled ? { label: 'Spento', tone: 'neutral' } : s.paused ? { label: 'In pausa', tone: 'warning' }
      : { label: 'Attivo', tone: 'success' };
    const queue = (s.queue || []).length;
    const running = (this.counts.running || 0) + (this.counts.merging || 0);
    const review = this.counts.awaiting_review || 0;
    const b = this.budget; const ph = b ? PHASE[b.phase] || { label: b.phase, tone: 'neutral' } : null;
    return html`<div class="w">
      <div class="between"><span class="small muted">Auto-sviluppo</span><hxk-badge tone=${state.tone}>${state.label}</hxk-badge></div>
      ${size === 's' ? html`<div class="big">${review}</div><div class="small muted">da rivedere · ${queue} in coda</div>` : html`
        <div class="nums">
          <div class="n"><b>${running}</b><span class="small muted">in corso</span></div>
          <div class="n"><b>${queue}</b><span class="small muted">in coda</span></div>
          <div class="n"><b>${review}</b><span class="small muted">da rivedere</span></div>
          ${this.counts.proposed ? html`<div class="n"><b>${this.counts.proposed}</b><span class="small muted">proposti</span></div>` : nothing}
        </div>
        ${ph ? html`<div class="small"><span class="muted">Claude:</span> <hxk-badge tone=${ph.tone}>${ph.label}</hxk-badge>
          ${size === 'l' ? html`<div class="small muted">${b.reason} · reset ${when(b.next_reset)}</div>` : nothing}</div>` : nothing}
        ${size === 'l' ? html`<div class="small muted">Motore: ${s.engine_default || '–'}${s.repo_ok ? '' : ' · repo non montato'}</div>` : nothing}
        ${s.enabled ? html`<div><hxk-button size="sm" variant="ghost" icon=${s.paused ? 'play' : 'pause'} ?loading=${this.busy}
          @click=${() => this.togglePause()}>${s.paused ? 'Riprendi' : 'Pausa'}</hxk-button></div>` : nothing}`}
    </div>`;
  }
}
