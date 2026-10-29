/**
 * <hygieia-today> — "Self care": today's plan. One tap marks a routine done; opening it shows the steps of today
 * (with why a step is not for today), lets you tick only some, and runs the wait timers between steps.
 */
import { HestiaElement, html, css, nothing } from '@hestia/webui-sdk';
import { API, STATE, STEP_STATE, addDays, call, dayLabel, hygieiaStyles, icon, alertIcon, meta, productName, search, secs, slotIcon, today } from './util';

/** Wait timers survive page changes (one per step). */
const timers: Record<string, number> = {};

export class HygieiaToday extends HestiaElement {
  static properties = { ...HestiaElement.properties, plan: { state: true }, alerts: { state: true }, open: { state: true },
    picked: { state: true }, busy: { state: true }, date: { state: true }, showAll: { state: true }, adhoc: { state: true },
    products: { state: true }, q: { state: true }, m: { state: true }, tick: { state: true } };
  declare plan: any;
  declare alerts: any[];
  declare open: string;
  declare picked: Record<string, Set<string>>;
  declare busy: string;
  declare date: string;
  declare showAll: boolean;
  declare adhoc: boolean;
  declare products: any[] | null;
  declare q: string;
  declare m: any;
  declare tick: number;
  private timer: any = null;

  static styles = [...HestiaElement.styles, hygieiaStyles, css`
    .slot { display: flex; flex-direction: column; gap: 10px; }
    .r { display: flex; flex-direction: column; gap: 10px; }
    .r.done { opacity: .85; }
    .rh { display: flex; align-items: center; gap: 12px; }
    .ico { width: 40px; height: 40px; border-radius: 12px; display: grid; place-items: center; font-size: 20px; background: var(--surface-2); flex: none; }
    .r.done .ico { background: var(--success-soft); }
    .name { font-weight: 600; font-size: 15px; }
    .steps { display: flex; flex-direction: column; gap: 2px; border-top: 1px solid var(--border); padding-top: 8px; }
    .st { display: flex; align-items: center; gap: 10px; padding: 7px 2px; border-radius: var(--radius-sm); }
    .st.off { opacity: .55; }
    .st input { width: 20px; height: 20px; accent-color: var(--accent); flex: none; }
    .num { width: 22px; height: 22px; border-radius: 50%; display: grid; place-items: center; font-size: 12px; background: var(--surface-3); color: var(--text-2); flex: none; }
    .why { font-size: 12px; color: var(--text-3); }
    .why.blocked { color: var(--danger); }
    .timer { font-variant-numeric: tabular-nums; }
    .alerts { display: flex; gap: 8px; overflow-x: auto; padding-bottom: 2px; }
    .alert { flex: none; max-width: 280px; display: flex; gap: 8px; align-items: center; font-size: 13px; padding: 8px 12px;
      border-radius: var(--radius-md); background: var(--surface); border: 1px solid var(--border); cursor: pointer; }
    .alert.warning { border-color: var(--warning); }
    .counts { display: flex; gap: 6px; flex-wrap: wrap; }
    .datebar { display: flex; align-items: center; gap: 4px; }
    .warnline { font-size: 12px; color: var(--warning); }
  `];

  constructor() {
    super();
    this.plan = undefined; this.alerts = []; this.open = ''; this.picked = {}; this.busy = ''; this.date = today();
    this.showAll = false; this.adhoc = false; this.products = null; this.q = ''; this.m = null; this.tick = 0;
  }

  connectedCallback() {
    super.connectedCallback();
    if (this.ctx?.query?.data) this.date = this.ctx.query.data;
    this.load();
    this.onHost('refresh', () => this.load());
    this.onHost('visible', () => this.load());
    this.timer = setInterval(() => { if (Object.keys(timers).length) this.tick = Date.now(); }, 1000);
  }
  disconnectedCallback() { super.disconnectedCallback(); clearInterval(this.timer); }

  private async load() {
    const [p, a, m] = await Promise.all([
      this.host.api('GET', `${API}/today`, { query: { date: this.date, paused: this.showAll } }),
      this.host.api('GET', `${API}/alerts`), meta(this.host)]);
    this.plan = p.ok ? p.data : null;
    this.alerts = a.ok ? a.data.items || [] : [];
    this.m = m;
  }

  private go(delta: number) {
    const d = addDays(this.date, delta);
    if (d > today()) return;
    this.date = d; this.open = ''; this.plan = undefined; this.load();
  }

  private chosen(r: any): Set<string> {
    if (!this.picked[r.routine_id]) {
      const s = new Set<string>();
      for (const st of r.steps) if (st.done || (st.done === null && st.include && !st.optional)) s.add(st.step_id);
      this.picked = { ...this.picked, [r.routine_id]: s };
    }
    return this.picked[r.routine_id];
  }
  private toggleStep(r: any, id: string) {
    const s = new Set(this.chosen(r));
    s.has(id) ? s.delete(id) : s.add(id);
    this.picked = { ...this.picked, [r.routine_id]: s };
  }

  private async done(r: any, withSteps: boolean) {
    this.busy = r.routine_id;
    const body: any = { date: this.date };
    if (withSteps) body.steps = r.steps.map((s: any) => ({ step_id: s.step_id, done: this.chosen(r).has(s.step_id) }));
    const res = await call(this.host, 'POST', `${API}/routines/${r.routine_id}/done`, { body, quiet: true });
    this.busy = '';
    if (res.ok) {
      this.host.toast(`${r.name}: ${res.data.status === 'partial' ? 'fatta in parte' : 'fatta'}${res.data.hint ? ' · ' + res.data.hint : ''}`, 'success',
        { label: 'Annulla', run: () => this.undo(r) });
      this.open = '';
      const { [r.routine_id]: _, ...rest } = this.picked; this.picked = rest;
    } else if (res.status === 409) {
      this.host.toast('Già segnata per questo giorno', 'info');
    } else {
      this.host.toast(res.error || 'Non salvata', 'warning');
    }
    this.load();
  }
  private async undo(r: any) {
    await call(this.host, 'DELETE', `${API}/routines/${r.routine_id}/done`, { query: { date: this.date } });
    this.load();
  }
  private async skip(r: any) {
    const res = await call(this.host, 'POST', `${API}/routines/${r.routine_id}/skip`, { body: { date: this.date } });
    if (res.ok) this.host.toast(`${r.name} saltata`, 'neutral', { label: 'Annulla', run: () => this.undoSkip(res.data.id) });
    this.open = '';
    this.load();
  }
  private async undoSkip(id: string) { await call(this.host, 'DELETE', `${API}/logs/${id}`); this.load(); }

  private startTimer(stepKey: string, seconds: number) {
    timers[stepKey] = Date.now() + seconds * 1000;
    this.tick = Date.now();
    setTimeout(() => {
      if (!timers[stepKey]) return;
      delete timers[stepKey];
      this.host.notify('Self care', 'Puoi passare al passo successivo', { tag: 'hygieia-timer' });
      this.host.toast('Attesa finita: passo successivo', 'info');
      this.tick = Date.now();
    }, seconds * 1000);
  }

  private async openAdhoc() {
    this.adhoc = true;
    if (!this.products) {
      const r = await this.host.api('GET', `${API}/products`, { query: { status: 'current' } });
      this.products = r.ok ? r.data.items : [];
    }
  }
  private async useProduct(p: any) {
    const r = await call(this.host, 'POST', `${API}/products/${p.id}/use`, { body: { date: this.date } });
    if (r.ok) this.host.toast(`${p.name} usato`, 'success', {
      label: 'Annulla', run: async () => { await call(this.host, 'DELETE', `${API}/products/${p.id}/use`, { query: { date: this.date } }); this.load(); } });
    this.adhoc = false; this.q = '';
    this.load();
  }

  private stepRow(r: any, s: any, i: number, editable: boolean) {
    const key = `${r.routine_id}:${s.step_id}`;
    const left = timers[key] ? (timers[key] - Date.now()) / 1000 : 0;
    const why = s.reason || STEP_STATE[s.state] || '';
    const checked = this.chosen(r).has(s.step_id);
    return html`<div class="st ${s.include || checked ? '' : 'off'}">
      ${editable ? html`<input type="checkbox" .checked=${checked} @change=${() => this.toggleStep(r, s.step_id)} aria-label=${s.label}>`
        : html`<span class="num">${s.done ? icon('check', 12, 'success') : i + 1}</span>`}
      <div class="grow">
        <div class="truncate">${s.product ? html`<span class="click" @click=${() => this.host.navigate('prodotti/' + s.product.id)}>${s.label}</span>` : s.label}
          ${s.amount ? html`<span class="small muted"> · ${s.amount}</span>` : nothing}${s.optional ? html`<span class="small muted"> · facoltativo</span>` : nothing}</div>
        ${why || s.hint ? html`<div class="why ${s.state === 'blocked' ? 'blocked' : ''}">${why}${why && s.hint ? ' · ' : ''}${s.hint}</div>` : nothing}
        ${s.note ? html`<div class="why">${s.note}</div>` : nothing}
      </div>
      ${s.wait_seconds && (s.include || checked) && editable ? (left > 0
        ? html`<span class="pill timer" @click=${() => { delete timers[key]; this.tick = Date.now(); }}>${icon('timer', 13)} ${secs(left)}</span>`
        : html`<hxk-button size="sm" variant="ghost" icon="clock" @click=${() => this.startTimer(key, s.wait_seconds)}>${secs(s.wait_seconds)}</hxk-button>`) : nothing}
    </div>`;
  }

  private card(r: any) {
    const st = STATE[r.state] || STATE.rest;
    const isOpen = this.open === r.routine_id;
    const done = r.state === 'done';
    const included = r.steps.filter((s: any) => s.include).length;
    return html`<div class="card r ${done ? 'done' : ''}">
      <div class="rh">
        <div class="ico">${done ? icon('check', 20, 'success') : (r.areas || []).length ? icon('droplet', 20, 'info') : slotIcon(r.slot, 20)}</div>
        <div class="grow click" @click=${() => { this.open = isOpen ? '' : r.routine_id; }}>
          <div class="row"><span class="name truncate">${r.name}</span>${r.favorite ? icon('star', 14, 'warning') : nothing}</div>
          <div class="small muted">${r.state === 'blocked' || r.state === 'paused' ? r.reason : r.hint}${included ? ` · ${included} ${included === 1 ? 'passo' : 'passi'}` : ''}${r.minutes && !done ? ` · ~${r.minutes} min` : ''}</div>
        </div>
        ${done ? html`<hxk-button size="sm" variant="ghost" icon="undo" @click=${() => this.undo(r)}>Annulla</hxk-button>`
          : html`<hxk-badge tone=${st.tone}>${st.text}</hxk-badge>
            <hxk-button variant=${r.state === 'due' || r.state === 'suggested' ? 'primary' : 'default'} icon="check" ?loading=${this.busy === r.routine_id}
              @click=${() => this.done(r, false)}>Fatta</hxk-button>`}
      </div>
      ${r.warnings?.length && !done ? html`<div class="warnline">${icon('alert', 13, 'warning')} ${r.warnings[0]}</div>` : nothing}
      ${isOpen ? html`<div class="steps">
        ${r.steps.length ? r.steps.map((s: any, i: number) => this.stepRow(r, s, i, !done)) : html`<div class="empty">Nessun passo: aggiungili nella routine.</div>`}
        <div class="row wrap" style="margin-top:6px">
          ${!done ? html`<hxk-button variant="primary" icon="check" @click=${() => this.done(r, true)}>Segna i passi scelti</hxk-button>
            <hxk-button variant="ghost" @click=${() => this.skip(r)}>Salta</hxk-button>` : nothing}
          <span class="grow"></span>
          <hxk-button variant="ghost" icon="edit" @click=${() => this.host.navigate('routine/' + r.routine_id)}>Modifica</hxk-button>
        </div>
      </div>` : nothing}
    </div>`;
  }

  private adhocSheet() {
    const items = search(this.products || [], this.q, p => `${p.brand} ${p.name} ${p.category}`);
    return html`<div class="sheet" @click=${(e: Event) => { if (e.target === e.currentTarget) this.adhoc = false; }}>
      <div class="card col">
        <div class="between"><h2>Ho usato un prodotto</h2><hxk-button variant="ghost" icon="x" @click=${() => (this.adhoc = false)}></hxk-button></div>
        <input class="in" placeholder="Cerca…" .value=${this.q} @input=${(e: any) => (this.q = e.target.value)} autofocus>
        ${this.products === null ? html`<hxk-state kind="loading"></hxk-state>` : html`<div class="list">
          ${items.slice(0, 40).map(p => html`<div class="li" @click=${() => this.useProduct(p)}>
            <div class="grow"><div class="truncate">${p.favorite ? html`${icon('star', 13, 'warning')} ` : nothing}${productName(p)}</div><div class="small muted">${p.status_label} · ${p.uses} usi</div></div>
            <hxk-icon name="plus"></hxk-icon></div>`)}
          ${!items.length ? html`<div class="empty">Nessun prodotto in uso. <button class="link" @click=${() => this.host.navigate('prodotti', { nuovo: '1' })}>Aggiungine uno</button></div>` : nothing}
        </div>`}
      </div></div>`;
  }

  render() {
    const p = this.plan;
    const nav = html`<div class="nav">
      <button class="tab" @click=${() => this.host.navigate('routine')}>Routine</button>
      <button class="tab" @click=${() => this.host.navigate('prodotti')}>Prodotti</button>
      <button class="tab" @click=${() => this.host.navigate('diario')}>Diario</button>
      <button class="tab" @click=${() => this.host.navigate('statistiche')}>Statistiche</button>
      <button class="tab" @click=${() => this.host.navigate('spesa')}>Spesa</button></div>`;
    const head = html`<div class="between wrap">
      <div class="head"><h1>Self care</h1>
        <div class="datebar"><hxk-button size="sm" variant="ghost" icon="chevron-left" @click=${() => this.go(-1)}></hxk-button>
          <span class="sub">${dayLabel(this.date)}</span>
          ${this.date < today() ? html`<hxk-button size="sm" variant="ghost" icon="chevron-right" @click=${() => this.go(1)}></hxk-button>` : nothing}</div></div>
      ${nav}</div>`;
    if (p === undefined) return html`<div class="page">${head}<hxk-state kind="loading"></hxk-state></div>`;
    if (p === null) return html`<div class="page">${head}<hxk-state kind="offline" @retry=${() => this.load()}></hxk-state></div>`;
    const groups: Record<string, any[]> = { morning: [], anytime: [], evening: [] };
    for (const r of p.routines) (groups[r.slot] || groups.anytime).push(r);
    const c = p.counts || {};
    return html`<div class="page">
      ${head}
      ${this.alerts.length && this.date === today() ? html`<div class="alerts">${this.alerts.slice(0, 6).map(a => html`
        <div class="alert ${a.level}" @click=${() => this.host.navigate('prodotti/' + a.product_id)}>
          ${alertIcon(a)}<span class="truncate">${a.text}</span></div>`)}</div>` : nothing}
      ${p.routines.length ? html`<div class="counts">
        ${c.done ? html`<span class="pill good">${icon('check', 13)} ${c.done} fatte</span>` : nothing}
        ${c.due ? html`<span class="pill warn">${c.due} da fare</span>` : nothing}
        ${c.suggested ? html`<span class="pill">${c.suggested} consigliate</span>` : nothing}
        ${c.blocked ? html`<span class="pill">${c.blocked} non oggi</span>` : nothing}
        <span class="grow"></span>
        <button class="link small" @click=${() => { this.showAll = !this.showAll; this.load(); }}>${this.showAll ? 'Nascondi in pausa' : 'Mostra anche in pausa'}</button>
      </div>` : nothing}
      ${!p.routines.length ? html`<div class="card col" style="align-items:flex-start">
          <h2>Nessuna routine</h2>
          <div class="muted">Crea la prima, per esempio «Viso sera: detergente → retinolo → crema». Puoi dire quante volte a settimana farla, niente orari fissi.</div>
          <div class="row wrap"><hxk-button variant="primary" icon="plus" @click=${() => this.host.navigate('routine', { nuova: '1' })}>Crea una routine</hxk-button>
            <hxk-button icon="plus" @click=${() => this.host.navigate('prodotti', { nuovo: '1' })}>Aggiungi prodotti</hxk-button></div></div>` : nothing}
      ${(['morning', 'anytime', 'evening'] as const).map(slot => groups[slot].length ? html`<div class="slot">
        <h3>${slotIcon(slot)} ${this.m?.slots?.[slot] || slot}</h3>${groups[slot].map(r => this.card(r))}</div>` : nothing)}
      <div class="row wrap">
        <hxk-button icon="plus" @click=${() => this.openAdhoc()}>Ho usato un prodotto</hxk-button>
        ${(p.adhoc || []).map((a: any) => html`<span class="pill">${icon('check', 13, 'success')} ${a.product}</span>`)}
      </div>
      ${this.adhoc ? this.adhocSheet() : nothing}
    </div>`;
  }
}
