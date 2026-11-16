/**
 * <athena-learning> — «Cosa ho imparato»: the learning log of the memory (added, merged, let go, weaker), each with
 * the owner's own sentence it comes from and «Annulla»; the clean-up proposals still waiting («Applica» / «Lascia»);
 * «Rivedi cosa sai di me» asks for new proposals (they also arrive as notifications).
 * Reads GET /api/athena/learning, GET /api/athena/memory/proposals; POST /learning/{id}/undo, /memory/review,
 * /memory/proposals/{id}/apply|dismiss. Dossier 2026-10-24-tutto-brainstorm-cindy Cindy 8 + 18 (W3) + W7.
 */
import { HestiaElement, html, css, nothing, tr } from '@hestia/webui-sdk';
import { API, when } from './util';

const ACTION: Record<string, { label: string; icon: string; tone: string }> = {
  add: { label: tr('Learned'), icon: 'plus', tone: 'success' },
  merge: { label: tr('Merged'), icon: 'check', tone: 'info' },
  retire: { label: tr('Let go'), icon: 'minus', tone: 'neutral' },
  decay: { label: tr('Less important'), icon: 'trend-down', tone: 'neutral' },
};
const PROPOSAL: Record<string, string> = { doppione: tr('alt::Duplicate'), contraddizione: tr('Contradiction') };
const UNDO_ERROR: Record<string, string> = {
  changed_since: tr('Changed afterwards: it stays as it is'), memory_gone: tr('It\'s no longer there'), already_undone: tr('Already undone'),
};

export class AthenaLearning extends HestiaElement {
  static properties = { ...HestiaElement.properties, items: { state: true }, proposals: { state: true },
                        error: { state: true }, busy: { state: true } };
  declare items: any[] | null; declare proposals: any[]; declare error: string; declare busy: string;

  static styles = [...HestiaElement.styles, css`
    .head { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
    .sub { color: var(--text-3); font-size: 13px; }
    h2 { font-size: 15px; margin: 6px 0 0; }
    .r { display: flex; gap: 10px; align-items: flex-start; padding: 10px 0; border-top: 1px solid var(--border); }
    .r:first-child { border-top: 0; }
    .r hxk-icon { flex: none; margin-top: 2px; }
    .fact { overflow-wrap: anywhere; }
    .undone .fact { text-decoration: line-through; color: var(--text-3); }
    .quote { font-size: 13px; color: var(--text-2); border-left: 2px solid var(--border-strong); padding-left: 8px; font-style: italic; }
  `];

  constructor() { super(); this.items = null; this.proposals = []; this.error = ''; this.busy = ''; }

  connectedCallback() {
    super.connectedCallback();
    this.load();
    this.onHost('refresh', () => this.load());
    this.onHost('visible', () => this.load());
  }

  private async load() {
    const [l, p] = await Promise.all([this.host.api('GET', `${API}/learning`, { query: { limit: 100 } }),
                                      this.host.api('GET', `${API}/memory/proposals`)]);
    if (!l.ok) { this.error = l.status === 0 ? tr('Not reachable') : l.error || tr('Not reachable'); return; }
    this.error = '';
    this.items = l.data?.items || [];
    this.proposals = p.ok ? p.data?.items || [] : [];
  }

  private async undo(e: any) {
    this.busy = e.id;
    const r = await this.host.api('POST', `${API}/learning/${encodeURIComponent(e.id)}/undo`);
    this.busy = '';
    if (!r.ok) { this.host.toast(UNDO_ERROR[r.data?.status] || r.data?.detail || tr('Not cancelled'), 'warning'); return; }
    this.host.toast(tr('Cancelled'), 'success');
    this.load();
  }

  private async decide(p: any, how: 'apply' | 'dismiss') {
    this.busy = `${how}:${p.id}`;
    const r = await this.host.api('POST', `${API}/memory/proposals/${encodeURIComponent(p.id)}/${how}`);
    this.busy = '';
    if (!r.ok) { this.host.toast(r.error || tr('alt::Failed'), 'warning'); return; }
    this.host.toast(how === 'apply' ? tr('Memory tidied') : tr('Left as it is'), 'success');
    this.load();
  }

  private async review() {
    this.busy = 'review';
    const r = await this.host.api('POST', `${API}/memory/review`);
    this.busy = '';
    if (!r.ok) { this.host.toast(r.error || tr('Failed, try again'), 'warning'); return; }
    const n = r.data?.proposals || 0;
    this.host.toast(n ? tr("{0} {1} to see", n, n === 1 ? tr('proposal') : tr('proposals')) : tr('Nothing to fix'), 'success');
    this.load();
  }

  private row(e: any) {
    const a = ACTION[e.action] || ACTION.add;
    const undone = !!e.undone;
    return html`<div class="r ${undone ? 'undone' : ''}">
      <hxk-icon name=${a.icon} tone=${a.tone} size="16"></hxk-icon>
      <div class="grow col" style="gap:4px">
        <div class="row wrap"><hxk-badge tone=${a.tone}>${a.label}</hxk-badge><span class="small muted">${when(e.at)}</span>
          ${undone ? html`<hxk-badge tone="neutral">${tr("Cancelled")}</hxk-badge>` : nothing}</div>
        <div class="fact">${e.fact || e.after?.fact || '–'}</div>
        ${e.quote ? html`<div class="quote">«${e.quote}»</div>` : nothing}
      </div>
      ${undone ? nothing : html`<hxk-button size="sm" variant="ghost" icon="undo" ?loading=${this.busy === e.id} @click=${() => this.undo(e)}>${tr("Cancel")}</hxk-button>`}
    </div>`;
  }

  private proposal(p: any) {
    return html`<div class="r">
      <hxk-icon name="sparkle" tone="accent" size="16"></hxk-icon>
      <div class="grow col" style="gap:4px">
        <div class="row wrap"><hxk-badge tone="info">${PROPOSAL[p.kind] || tr('Maybe old')}</hxk-badge><span class="small muted">${p.why || ''}</span></div>
        ${(p.facts || []).slice(0, 4).map((f: string) => html`<div class="fact small">${f}</div>`)}
        ${p.merged ? html`<div class="small">${tr("Becomes:")} <i>${p.merged}</i></div>` : nothing}
      </div>
      <div class="col" style="gap:6px">
        <hxk-button size="sm" variant="primary" icon="check" ?loading=${this.busy === `apply:${p.id}`} @click=${() => this.decide(p, 'apply')}>${tr("Apply")}</hxk-button>
        <hxk-button size="sm" variant="ghost" ?loading=${this.busy === `dismiss:${p.id}`} @click=${() => this.decide(p, 'dismiss')}>${tr("Leave")}</hxk-button>
      </div>
    </div>`;
  }

  render() {
    if (this.error) return html`<div class="page"><h1>${tr("What I learned")}</h1><hxk-state kind="offline" text=${this.error} @retry=${() => this.load()}></hxk-state></div>`;
    if (!this.items) return html`<div class="page"><hxk-state kind="loading"></hxk-state></div>`;
    return html`<div class="page">
      <div class="head"><h1>${tr("What I learned")}</h1><span class="sub">${tr("Only from what you said, with the sentence it comes from")}</span>
        <span class="grow"></span><hxk-button icon="sparkle" ?loading=${this.busy === 'review'} @click=${() => this.review()}>${tr("Review what you know about me")}</hxk-button></div>
      ${this.proposals.length ? html`<h2>${tr("To decide")}</h2><div class="card">${this.proposals.map(p => this.proposal(p))}</div>` : nothing}
      ${this.items.length ? html`<div class="card">${this.items.map(e => this.row(e))}</div>`
        : html`<hxk-state kind="empty" text=${tr("Nothing yet: the night reflection learns from the conversations and writes it here.")}></hxk-state>`}
    </div>`;
  }
}
