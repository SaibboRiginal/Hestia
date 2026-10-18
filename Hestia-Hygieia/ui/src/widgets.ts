/** Hygieia widgets for Home and dashboards: today in one tap, next routine, expiring / running out, the week. */
import { HestiaElement, html, css, nothing } from '@hestia/webui-sdk';
import type { QuickAction } from '@hestia/webui-sdk';
import { API, STATE, WEEKDAYS, call, hygieiaStyles, localDay } from './util';

abstract class Widget extends HestiaElement {
  static styles = [...HestiaElement.styles, hygieiaStyles, css`
    :host { display: block; height: 100%; }
    .w { display: flex; flex-direction: column; gap: 8px; height: 100%; padding: 2px; }
  `];
  connectedCallback() {
    super.connectedCallback();
    this.load();
    this.onHost('refresh', () => this.load());
    this.onHost('visible', () => this.load());
  }
  protected load(): void { /* widget specific */ }
  protected get size() { return this.ctx?.size || 'm'; }
}

const ROUTINE_ACTION: QuickAction = { method: 'POST', path: `${API}/quick/routine/{id}`, undo: { method: 'DELETE', path: `${API}/quick/routine/{id}` } };
const PRODUCT_ACTION: QuickAction = { method: 'POST', path: `${API}/quick/product/{id}`, undo: { method: 'DELETE', path: `${API}/quick/product/{id}` } };

export class HygieiaTodayWidget extends Widget {
  static properties = { ...HestiaElement.properties, plan: { state: true }, n: { state: true } };
  declare plan: any;
  declare n: number;
  constructor() { super(); this.plan = undefined; this.n = 0; }
  protected async load() {
    const r = await this.host.api('GET', `${API}/today`);
    this.plan = r.ok ? r.data : null;
    this.n++;                                      // re-mounts the chips so they reload too
  }
  render() {
    const c = this.plan?.counts;
    return html`<div class="w">
      <div class="between click" @click=${() => this.host.navigate('oggi')}><span class="small muted">Self care di oggi</span>
        ${c ? html`<span class="small muted">${c.done ? `✓ ${c.done}` : ''}${c.done && c.due ? ' · ' : ''}${c.due ? `${c.due} da fare` : ''}</span>` : nothing}</div>
      ${this.plan === null ? html`<hxk-state kind="offline" @retry=${() => this.load()}></hxk-state>` : html`
        ${[this.n].map(() => html`<hxk-quicklog .host=${this.host} source=${`${API}/quick/routines`} .action=${ROUTINE_ACTION} @logged=${() => this.load()}></hxk-quicklog>`)}
        ${this.plan && !this.plan.routines.length ? html`<div class="muted small">Nessuna routine ancora. <button class="link" @click=${() => this.host.navigate('routine', { nuova: '1' })}>Creane una</button></div>` : nothing}
        ${this.size === 'l' || this.size === 'xl' ? html`<span class="small muted">Prodotti preferiti</span>
          ${[this.n].map(() => html`<hxk-quicklog compact .host=${this.host} source=${`${API}/quick/products`} .action=${PRODUCT_ACTION}></hxk-quicklog>`)}` : nothing}`}
    </div>`;
  }
}

export class HygieiaNextWidget extends Widget {
  static properties = { ...HestiaElement.properties, plan: { state: true }, busy: { state: true } };
  declare plan: any;
  declare busy: boolean;
  constructor() { super(); this.plan = undefined; this.busy = false; }
  protected async load() { const r = await this.host.api('GET', `${API}/today`); this.plan = r.ok ? r.data : null; }
  private async done(n: any) {
    this.busy = true;
    const r = await call(this.host, 'POST', `${API}/quick/routine/${n.routine_id}`, { body: {} });
    this.busy = false;
    if (r.ok) this.host.toast(r.data.label, 'success', { label: 'Annulla', run: async () => { await call(this.host, 'DELETE', `${API}/quick/routine/${n.routine_id}`); this.load(); } });
    this.load();
  }
  render() {
    const p = this.plan;
    if (p === undefined) return html`<hxk-state kind="loading"></hxk-state>`;
    if (p === null) return html`<hxk-state kind="offline" @retry=${() => this.load()}></hxk-state>`;
    const n = p.next;
    if (!n) {
      const done = p.counts?.done || 0;
      return html`<div class="w click" @click=${() => this.host.navigate('oggi')}><span class="small muted">Self care</span>
        <div class="big">${done ? 'Tutto fatto ✓' : 'Niente da fare'}</div><div class="small muted">${done ? `${done} routine oggi` : 'Nessuna routine in programma oggi'}</div></div>`;
    }
    const st = STATE[n.state] || STATE.rest;
    const steps = n.steps.filter((s: any) => s.include);
    return html`<div class="w">
      <div class="between"><span class="small muted">Prossima</span><hxk-badge tone=${st.tone}>${st.text}</hxk-badge></div>
      <div class="big truncate click" @click=${() => this.host.navigate('oggi')}>${n.name}</div>
      <div class="small muted truncate">${n.hint}${steps.length ? ` · ${steps.length} passi` : ''}</div>
      ${this.size !== 's' ? html`<div class="small truncate">${steps.map((s: any) => s.label).join(' → ')}</div>` : nothing}
      <div><hxk-button variant="primary" icon="check" ?loading=${this.busy} @click=${() => this.done(n)}>Fatta</hxk-button></div>
    </div>`;
  }
}

export class HygieiaAlertsWidget extends Widget {
  static properties = { ...HestiaElement.properties, items: { state: true }, shop: { state: true } };
  declare items: any[] | null | undefined;
  declare shop: number;
  constructor() { super(); this.items = undefined; this.shop = 0; }
  protected async load() {
    const [a, s] = await Promise.all([this.host.api('GET', `${API}/alerts`), this.host.api('GET', `${API}/shopping`)]);
    this.items = a.ok ? a.data.items : null;
    this.shop = s.ok ? s.data.count : 0;
  }
  render() {
    if (this.items === undefined) return html`<hxk-state kind="loading"></hxk-state>`;
    if (this.items === null) return html`<hxk-state kind="offline" @retry=${() => this.load()}></hxk-state>`;
    const max = this.size === 'l' || this.size === 'xl' ? 8 : 4;
    return html`<div class="w">
      <div class="between click" @click=${() => this.host.navigate('spesa')}><span class="small muted">Prodotti</span>
        ${this.shop ? html`<span class="pill">🛒 ${this.shop} da comprare</span>` : nothing}</div>
      ${this.items.length ? html`<div class="list">${this.items.slice(0, max).map(a => html`<div class="li" style="padding:6px 2px" @click=${() => this.host.navigate('prodotti/' + a.product_id)}>
        <span>${a.type === 'expiry' ? '⏳' : a.type === 'restock' ? '🛒' : '⚠️'}</span><span class="grow truncate small">${a.text}</span></div>`)}</div>`
        : html`<div class="muted small">Niente in scadenza o in esaurimento.</div>`}
    </div>`;
  }
}

export class HygieiaWeekWidget extends Widget {
  static properties = { ...HestiaElement.properties, st: { state: true } };
  declare st: any;
  constructor() { super(); this.st = undefined; }
  protected async load() { const r = await this.host.api('GET', `${API}/stats`, { query: { days: 13 } }); this.st = r.ok ? r.data : null; }
  render() {
    const s = this.st;
    if (s === undefined) return html`<hxk-state kind="loading"></hxk-state>`;
    if (s === null) return html`<hxk-state kind="offline" @retry=${() => this.load()}></hxk-state>`;
    const counts: Record<string, number> = {};
    for (const h of s.heatmap || []) counts[h.date] = h.count;
    const now = new Date();
    const monday = new Date(now); monday.setDate(now.getDate() - ((now.getDay() + 6) % 7));
    const days = Array.from({ length: 7 }, (_, i) => { const d = new Date(monday); d.setDate(monday.getDate() + i); return localDay(d); });
    const goals = (s.routines || []).filter((r: any) => r.history?.length && r.history[r.history.length - 1].need);
    return html`<div class="w click" @click=${() => this.host.navigate('statistiche')}>
      <div class="between"><span class="small muted">Questa settimana</span>${s.week.goals ? html`<span class="small muted">obiettivi ${s.week.goals_met}/${s.week.goals}</span>` : nothing}</div>
      <div class="big tnum">${s.week.logs} <span class="muted" style="font-size:14px;font-weight:400">routine fatte</span></div>
      <div class="row" style="gap:4px">${days.map((d, i) => html`<div class="col" style="align-items:center;gap:2px;flex:1">
        <span style="width:100%;max-width:26px;height:26px;border-radius:7px;display:grid;place-items:center;font-size:11px;color:var(--accent-contrast);background:${counts[d] ? 'var(--success)' : d === localDay(now) ? 'var(--accent-soft)' : 'var(--surface-3)'}">${counts[d] > 1 ? counts[d] : ''}</span>
        <span class="small muted">${WEEKDAYS[i][0]}</span></div>`)}</div>
      ${this.size === 'l' || this.size === 'xl' ? html`<div class="list">${goals.slice(0, 5).map((r: any) => { const h = r.history[r.history.length - 1];
        return html`<div class="between small" style="padding:3px 0"><span class="truncate">${r.name}</span><span class="tnum ${h.met ? '' : 'muted'}">${h.done}/${h.need}${h.met ? ' ✓' : ''}</span></div>`; })}</div>` : nothing}
    </div>`;
  }
}
