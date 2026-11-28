/**
 * <chronos-standard> — «Standard activities»: every activity a module puts in the agenda by default (the evening recap,
 * reminders, syncs…) with its state, so one you deleted, paused or changed comes back with «Restore» instead of
 * being rebuilt from scratch; plus the templates each module offers («Add» opens the calendar wizard).
 * Reads GET /api/agenda/standard; POST /api/agenda/standard/{key}/restore. Recap dossier §3.9.
 */
import { HestiaElement, html, css, nothing, tr } from '@hestia/webui-sdk';
import { API } from './util';
import { describeRRule } from './cal/rrule';
import { ownerLabel } from './cal/models';

const STATES: Record<string, { tone: string; icon: string; text: string }> = {
  deleted: { tone: 'danger', icon: 'trash', text: tr('f::Deleted') },
  failed: { tone: 'danger', icon: 'alert', text: tr('Stopped on errors') },
  paused: { tone: 'warning', icon: 'pause', text: tr('Paused') },
  edited: { tone: 'info', icon: 'edit', text: tr('Changed by you') },
  active: { tone: 'success', icon: 'check-circle', text: tr('f::Active') },
};
const FILTERS = [{ id: 'todo', label: tr('To put back') }, { id: '', label: tr('All') }];

function hhmm(iso?: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

export class ChronosStandard extends HestiaElement {
  static properties = { ...HestiaElement.properties, data: { state: true }, error: { state: true },
                        filter: { state: true }, busy: { state: true } };
  declare data: any; declare error: string; declare filter: string; declare busy: string;

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
    .r hxk-icon { flex: none; margin-top: 2px; }
    .t { font-weight: 550; overflow-wrap: anywhere; }
    .tpl { display: grid; gap: 8px; grid-template-columns: repeat(auto-fill, minmax(min(100%, 220px), 1fr)); }
    .tp { border: 1px solid var(--border); border-radius: var(--radius-md); padding: 8px 10px; display: flex; gap: 8px; }
    h2 { font-size: 15px; margin: 6px 0 0; }
  `];

  constructor() { super(); this.data = null; this.error = ''; this.filter = 'todo'; this.busy = ''; }

  connectedCallback() {
    super.connectedCallback();
    this.load();
    this.onHost('refresh', () => this.load());
    this.onHost('visible', () => this.load());
  }

  private async load() {
    const r = await this.host.api('GET', `${API}/standard`);
    if (!r.ok) { this.error = r.status === 0 ? tr('Agenda not reachable') : r.error || tr('Agenda not reachable'); return; }
    this.error = '';
    this.data = r.data;
    if (this.filter === 'todo' && !(r.data.activities || []).some((a: any) => a.can_restore)) this.filter = '';
  }

  private async restore(a: any) {
    this.busy = a.key;
    const r = await this.host.api('POST', `${API}/standard/${encodeURIComponent(a.key)}/restore`);
    this.busy = '';
    if (!r.ok) { this.host.toast(r.error || tr("{0}: not restored", a.title), 'danger'); return; }
    this.host.toast(tr("{0}: back as expected", a.title), 'success');
    this.load();
  }

  private when(a: any): string {
    const rule = a.recurrence ? describeRRule(a.recurrence) : '';
    const at = hhmm(a.start_at);
    const flex = a.flex?.earliest && a.flex?.latest ? tr(' · flexible {0}–{1}', a.flex.earliest, a.flex.latest) : '';
    return [rule, at && a.type !== 'window' ? tr('at {0}', at) : '', ].filter(Boolean).join(' ') + flex;
  }

  private row(a: any) {
    const st = STATES[a.state] || STATES.active;
    return html`<div class="r">
      <hxk-icon name=${st.icon} tone=${st.tone} size="16"></hxk-icon>
      <div class="grow col" style="gap:3px">
        <div class="row wrap"><span class="t">${a.title}</span><hxk-badge tone=${st.tone}>${st.text}</hxk-badge></div>
        <div class="small muted">${ownerLabel(a.owner)}${this.when(a) ? ` · ${this.when(a)}` : ''}</div>
        ${a.description ? html`<div class="small muted">${a.description}</div>` : nothing}
      </div>
      ${a.can_restore ? html`<hxk-button size="sm" icon="undo" ?loading=${this.busy === a.key} @click=${() => this.restore(a)}>${tr("f::Restore")}</hxk-button>` : nothing}
    </div>`;
  }

  render() {
    if (this.error) return html`<div class="page"><hxk-page-head heading=${tr("Standard tasks")}></hxk-page-head><hxk-state kind="offline" text=${this.error} @retry=${() => this.load()}></hxk-state></div>`;
    const d = this.data;
    if (!d) return html`<div class="page"><hxk-state kind="loading"></hxk-state></div>`;
    const all: any[] = d.activities || [];
    const rows = this.filter === 'todo' ? all.filter(a => a.can_restore) : all;
    const tpls: any[] = d.templates || [];
    return html`<div class="page">
      <hxk-page-head heading=${tr("Standard tasks")} sub=${tr("What the modules put in the agenda by themselves: if you remove one, put it back with a click")} ask=${tr("Standard tasks")}></hxk-page-head>
      <div class="chips">${FILTERS.map(f => html`<button class="chip" aria-pressed=${this.filter === f.id} @click=${() => (this.filter = f.id)}>
        ${f.label}${f.id === 'todo' ? ` (${all.filter(a => a.can_restore).length})` : ''}</button>`)}</div>
      ${rows.length ? html`<div class="card">${rows.map(a => this.row(a))}</div>`
        : html`<hxk-state kind="empty" text=${this.filter === 'todo' ? tr('All standard activities are active and as expected.') : tr('No standard activity: the modules register them when they start.')}></hxk-state>`}
      ${tpls.length ? html`<h2>${tr("To add")}</h2><div class="tpl">${tpls.map(t => html`<div class="tp">
          <hxk-icon name=${t.icon || 'zap'} tone="accent" size="16"></hxk-icon>
          <div class="grow col" style="gap:2px"><b>${t.label}</b><span class="small muted">${ownerLabel(t.owner)}${t.description ? ` · ${t.description}` : ''}</span></div></div>`)}</div>
        <p class="small muted">${tr("They are added from the calendar: Agenda → New → «From a module…».")}</p>` : nothing}
    </div>`;
  }
}
