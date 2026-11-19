/**
 * <hygieia-routines> — all routines (goal, state of today, favorites) and the creation sheet.
 * <hygieia-routine>  — one routine: when (slot, goal or fixed days), steps (products, order, waits, own cadence,
 *                      pause), compatibility notes, adherence, versions with what changed and why.
 * <hygieia-cadence>  — goal picker shared by routines and steps.
 */
import { HestiaElement, LitElement, html, css, nothing, tr } from '@hestia/webui-sdk';
import { API, STATE, WEEKDAYS, addDays, cadenceText, call, dayLabel, hygieiaStyles, icon, label, meta, productName, relDays, search, slotIcon, today } from './util';

/** Goal of a routine or step: every day · fixed weekdays · at least N per week/month · when it happens. */
export class HygieiaCadence extends LitElement {
  static properties = { value: { attribute: false }, allowNone: { type: Boolean } };
  declare value: any;
  declare allowNone: boolean;
  static styles = [...HestiaElement.styles, hygieiaStyles, css`:host { display: flex; flex-direction: column; gap: 8px; }`];
  constructor() { super(); this.value = { mode: 'target', times: 3, per: 'week' }; this.allowNone = false; }
  private set(v: any) {
    this.value = v;
    this.dispatchEvent(new CustomEvent('change', { detail: v, bubbles: true, composed: true }));
  }
  render() {
    const v = this.value;
    const mode = v?.mode || 'none';
    const modes: Array<[string, string]> = [['target', tr('At least N times')], ['daily', tr('Every day')], ['fixed_days', tr('Fixed days')], ['as_needed', tr('When it happens')]];
    if (this.allowNone) modes.unshift(['none', tr('Every time')]);
    return html`<div class="chips">${modes.map(([m, l]) => html`<button class="chip" aria-pressed=${mode === m} @click=${() => this.set(
        m === 'none' ? null : m === 'target' ? { mode: m, times: v?.times || 2, per: v?.per || 'week' } : m === 'fixed_days' ? { mode: m, days: v?.days || [] } : { mode: m })}>${l}</button>`)}</div>
      ${mode === 'target' ? html`<div class="row wrap">
        <input class="in num" type="number" min="1" max="31" .value=${String(v.times || 1)} @change=${(e: any) => this.set({ ...v, times: Math.max(1, Number(e.target.value) || 1) })}>
        <span>${(v.times || 1) === 1 ? tr('time a') : tr('times a')}</span>
        <div class="chips"><button class="chip" aria-pressed=${v.per !== 'month'} @click=${() => this.set({ ...v, per: 'week' })}>${tr("week")}</button>
          <button class="chip" aria-pressed=${v.per === 'month'} @click=${() => this.set({ ...v, per: 'month' })}>${tr("month")}</button></div></div>
        <div class="small muted">${tr("No fixed day: I suggest it when you are behind, spread over the")} ${v.per === 'month' ? tr('the month') : tr('the week')}.</div>` : nothing}
      ${mode === 'fixed_days' ? html`<div class="chips">${WEEKDAYS.map((d, i) => html`<button class="chip" aria-pressed=${(v.days || []).includes(i)}
        @click=${() => { const s = new Set<number>(v.days || []); s.has(i) ? s.delete(i) : s.add(i); this.set({ ...v, days: [...s].sort() }); }}>${d}</button>`)}</div>` : nothing}
      ${mode === 'none' ? html`<div class="small muted">${tr("It's done every time you do the routine.")}</div>` : nothing}`;
  }
}

export class HygieiaRoutines extends HestiaElement {
  static properties = { ...HestiaElement.properties, items: { state: true }, archived: { state: true }, creating: { state: true }, m: { state: true } };
  declare items: any[] | null | undefined;
  declare archived: boolean;
  declare creating: any;
  declare m: any;
  static styles = [...HestiaElement.styles, hygieiaStyles, css`
    .ico { width: 36px; height: 36px; border-radius: 10px; display: grid; place-items: center; background: var(--surface-2); font-size: 18px; flex: none; }
    .star { background: none; border: none; cursor: pointer; padding: 4px; display: inline-flex; }
  `];
  constructor() { super(); this.items = undefined; this.archived = false; this.creating = null; this.m = null; }
  connectedCallback() {
    super.connectedCallback();
    if (this.ctx?.query?.new) this.startCreate();
    this.load();
    this.onHost('refresh', () => this.load());
  }
  private async load() {
    const [r, m] = await Promise.all([this.host.api('GET', `${API}/routines`, { query: { archived: this.archived } }), meta(this.host)]);
    this.items = r.ok ? r.data.items : null;
    this.m = m;
  }
  private startCreate() { this.creating = { name: '', slot: 'evening', areas: ['face'], cadence: { mode: 'target', times: 3, per: 'week' } }; }
  private async create() {
    const c = this.creating;
    if (!c.name.trim()) { this.host.toast(tr('Name the routine'), 'warning'); return; }
    const r = await call(this.host, 'POST', `${API}/routines`, { body: { ...c, steps: [] } });
    if (r.ok) { this.creating = null; this.host.navigate('routine/' + r.data.id, { new: '1' }); }
  }
  private async fav(r: any, e: Event) {
    e.stopPropagation();
    await call(this.host, 'PUT', `${API}/routines/${r.id}`, { body: { favorite: !r.favorite } });
    this.load();
  }
  private sheet() {
    const c = this.creating;
    return html`<div class="sheet" @click=${(e: Event) => { if (e.target === e.currentTarget) this.creating = null; }}><div class="card col">
      <div class="between"><h2>${tr("New routine")}</h2><hxk-button variant="ghost" icon="x" @click=${() => (this.creating = null)}></hxk-button></div>
      <input class="in" placeholder=${tr("Name, e.g. Evening face")} .value=${c.name} @input=${(e: any) => (this.creating = { ...c, name: e.target.value })}
        @keydown=${(e: KeyboardEvent) => e.key === 'Enter' && this.create()} autofocus>
      <h3>${tr("When")}</h3>
      <div class="chips">${Object.entries(this.m?.slots || { morning: tr('Morning'), evening: tr('Evening'), anytime: tr('Whenever') }).map(([k, l]) => html`
        <button class="chip" aria-pressed=${c.slot === k} @click=${() => (this.creating = { ...c, slot: k })}>${slotIcon(k)} ${l}</button>`)}</div>
      <h3>${tr("Zones")}</h3>
      <div class="chips">${(this.m?.areas || []).map((a: any) => html`<button class="chip" aria-pressed=${c.areas.includes(a.value)}
        @click=${() => this.creating = { ...c, areas: c.areas.includes(a.value) ? c.areas.filter((x: string) => x !== a.value) : [...c.areas, a.value] }}>${a.label}</button>`)}</div>
      <h3>${tr("Goal")}</h3>
      <hygieia-cadence .value=${c.cadence} @change=${(e: CustomEvent) => (this.creating = { ...c, cadence: e.detail })}></hygieia-cadence>
      <div class="row"><span class="grow"></span><hxk-button variant="primary" icon="check" @click=${() => this.create()}>${tr("Create and add the steps")}</hxk-button></div>
    </div></div>`;
  }
  render() {
    const head = html`<div class="between wrap"><div class="head"><button class="link" @click=${() => this.host.navigate('today')}>${tr("‹ Today")}</button><h1>${tr("Routine")}</h1></div>
      <hxk-button variant="primary" icon="plus" @click=${() => this.startCreate()}>${tr("f::New")}</hxk-button></div>`;
    if (this.items === undefined) return html`<div class="page">${head}<hxk-state kind="loading"></hxk-state></div>`;
    if (this.items === null) return html`<div class="page">${head}<hxk-state kind="offline" @retry=${() => this.load()}></hxk-state></div>`;
    const active = this.items.filter(r => r.status === 'active'), other = this.items.filter(r => r.status !== 'active');
    const row = (r: any) => { const st = STATE[r.state] || STATE.rest; return html`<div class="li" @click=${() => this.host.navigate('routine/' + r.id)}>
      <div class="ico">${(r.areas || []).length ? icon('droplet', 18, 'info') : slotIcon(r.slot, 18)}</div>
      <div class="grow"><div class="truncate"><b>${r.name}</b></div>
        <div class="small muted truncate">${slotIcon(r.slot, 12)} ${r.cadence_label} · ${r.step_count === 1 ? tr('1 step') : tr('{0} steps', r.step_count)}${r.status === 'active' && r.hint ? ' · ' + r.hint : ''}${r.reminder ? html` · ${icon('bell', 12, 'info')}` : nothing}</div></div>
      ${r.status === 'active' ? html`<hxk-badge tone=${st.tone}>${st.text}</hxk-badge>` : html`<hxk-badge>${r.status === 'paused' ? tr('Paused') : tr('f::Archived')}</hxk-badge>`}
      <button class="star ${r.favorite ? 'on' : ''}" title=${tr("Favourite (in Home)")} @click=${(e: Event) => this.fav(r, e)}>${icon('star', 18, r.favorite ? 'warning' : 'muted')}</button>
    </div>`; };
    return html`<div class="page">${head}
      ${this.items.length ? nothing : html`<div class="card muted">${tr("No routines. Create one: no fixed times, just how many times you want to do it.")}</div>`}
      ${active.length ? html`<div class="card list">${active.map(row)}</div>` : nothing}
      ${other.length ? html`<h3>${tr("Paused and archived")}</h3><div class="card list">${other.map(row)}</div>` : nothing}
      <div><button class="link small" @click=${() => { this.archived = !this.archived; this.load(); }}>${this.archived ? tr('Hide archived') : tr('Show archived')}</button></div>
      ${this.creating ? this.sheet() : nothing}
    </div>`;
  }
}

export class HygieiaRoutine extends HestiaElement {
  static properties = { ...HestiaElement.properties, r: { state: true }, steps: { state: true }, dirty: { state: true }, reason: { state: true },
    m: { state: true }, products: { state: true }, others: { state: true }, picking: { state: true }, q: { state: true }, edit: { state: true },
    saving: { state: true } };
  declare r: any;
  declare steps: any[];
  declare dirty: boolean;
  declare reason: string;
  declare m: any;
  declare products: any[];
  declare others: any[];
  declare picking: boolean;
  declare q: string;
  declare edit: string;
  declare saving: boolean;
  static styles = [...HestiaElement.styles, hygieiaStyles, css`
    .sec { display: flex; flex-direction: column; gap: 10px; }
    .step { display: flex; flex-direction: column; gap: 8px; padding: 10px 0; border-bottom: 1px solid var(--border); }
    .step:last-child { border-bottom: none; }
    .sh { display: flex; align-items: center; gap: 8px; }
    .num { width: 24px; height: 24px; border-radius: 50%; display: grid; place-items: center; font-size: 12px; background: var(--accent-soft); color: var(--accent); flex: none; font-weight: 600; }
    .ord { display: flex; flex-direction: column; }
    .ord button { background: none; border: none; color: var(--text-3); cursor: pointer; padding: 0 4px; line-height: 1; font-size: 12px; }
    .ord button:hover { color: var(--text); }
    .save { position: sticky; bottom: 12px; z-index: 5; display: flex; gap: 8px; align-items: center; flex-wrap: wrap;
      background: var(--surface); border: 1px solid var(--accent); border-radius: var(--radius-lg); padding: 10px 12px; box-shadow: var(--shadow-2); }
    .ver { display: flex; gap: 10px; padding: 8px 0; border-bottom: 1px solid var(--border); }
    .ver:last-child { border-bottom: none; }
    .title { font-size: 22px; font-weight: 650; border: none; background: transparent; color: var(--text); font-family: inherit; padding: 2px 0; min-width: 0; flex: 1; }
    .title:focus { outline: none; border-bottom: 2px solid var(--accent); }
    .hist { display: flex; gap: 3px; align-items: flex-end; height: 44px; }
    .bar { flex: 1; border-radius: 3px 3px 0 0; background: var(--surface-3); min-height: 3px; }
    .bar.met { background: var(--success); }
  `];
  constructor() {
    super(); this.r = undefined; this.steps = []; this.dirty = false; this.reason = ''; this.m = null; this.products = []; this.others = [];
    this.picking = false; this.q = ''; this.edit = ''; this.saving = false;
  }
  private get rid() { return this.ctx?.params?.id || ''; }
  connectedCallback() {
    super.connectedCallback();
    this.load();
    this.onHost('refresh', () => { if (!this.dirty) this.load(); });
    if (this.ctx?.query?.new) this.picking = true;
  }
  private async load() {
    const [r, m, p, o] = await Promise.all([this.host.api('GET', `${API}/routines/${this.rid}`), meta(this.host),
      this.host.api('GET', `${API}/products`), this.host.api('GET', `${API}/routines`)]);
    this.r = r.ok ? r.data : r.status === 404 ? 'missing' : null;
    if (r.ok) { this.steps = r.data.steps.map((s: any) => ({ ...s })); this.dirty = false; this.reason = ''; }
    this.m = m;
    this.products = p.ok ? p.data.items : [];
    this.others = o.ok ? o.data.items.filter((x: any) => x.id !== this.rid) : [];
  }

  /** Routine-level fields: saved at once, no new version. */
  private async patch(body: any) {
    const r = await call(this.host, 'PUT', `${API}/routines/${this.rid}`, { body });
    if (r.ok) { const steps = this.steps, dirty = this.dirty; this.r = r.data; if (dirty) this.steps = steps; this.dirty = dirty; }
  }
  private setSteps(steps: any[]) { this.steps = steps; this.dirty = true; }
  private updStep(i: number, ch: any) { this.setSteps(this.steps.map((s, k) => k === i ? { ...s, ...ch } : s)); }
  private move(i: number, d: number) {
    const j = i + d;
    if (j < 0 || j >= this.steps.length) return;
    const s = [...this.steps];
    [s[i], s[j]] = [s[j], s[i]];
    this.setSteps(s);
  }
  private addProduct(p: any) {
    this.setSteps([...this.steps, { id: '', product_id: p.id, product: p, label: '', amount: '', wait_seconds: 0, cadence: null, optional: false, note: '' }]);
    this.picking = false; this.q = '';
  }
  private addLabel() {
    const text = this.q.trim();
    if (!text) return;
    this.setSteps([...this.steps, { id: '', product_id: null, label: text, amount: '', wait_seconds: 0, cadence: null, optional: false, note: '' }]);
    this.picking = false; this.q = '';
  }
  private async saveSteps() {
    this.saving = true;
    const steps = this.steps.map(s => ({ id: s.id || undefined, product_id: s.product_id || null, label: s.product_id ? (s.label || '') : s.label,
      amount: s.amount || '', wait_seconds: Number(s.wait_seconds) || 0, cadence: s.cadence || null, optional: !!s.optional,
      note: s.note || '', paused_until: s.paused_until || null, not_same_day_as: s.not_same_day_as || [] }));
    const r = await call(this.host, 'PUT', `${API}/routines/${this.rid}`, { body: { steps, reason: this.reason } });
    this.saving = false;
    if (r.ok) { this.host.toast(tr("Saved{0}", r.data.version ? tr(' · version {0}', r.data.version) : ''), 'success'); this.load(); }
  }
  private async undoVersion() {
    if (!await this.host.confirm(tr('alt::Back to the previous version'), tr('The steps go back to how they were before the last change (it stays in the history).'))) return;
    const r = await call(this.host, 'POST', `${API}/routines/${this.rid}/undo`);
    if (r.ok) { this.host.toast(tr('Previous version restored'), 'success'); this.load(); }
  }
  private async archive() {
    if (!await this.host.confirm(tr('Archive routine'), tr('It won\'t appear in Today any more; history and statistics stay.'), { label: tr('f::Archive'), danger: true })) return;
    const r = await call(this.host, 'DELETE', `${API}/routines/${this.rid}`);
    if (r.ok) this.host.navigate('routine');
  }

  private stepEditor(s: any, i: number) {
    const name = s.product ? productName(s.product) : s.label;
    const open = this.edit === (s.id || `new${i}`);
    const paused = s.paused_until && s.paused_until > today();
    return html`<div class="step">
      <div class="sh">
        <div class="ord"><button @click=${() => this.move(i, -1)} aria-label="Su">▲</button><button @click=${() => this.move(i, 1)} aria-label=${tr("Down")}>▼</button></div>
        <span class="num">${i + 1}</span>
        <div class="grow click" @click=${() => (this.edit = open ? '' : (s.id || `new${i}`))}>
          <div class="truncate">${name}${s.optional ? html`<span class="small muted">${tr(' · optional')}</span>` : nothing}</div>
          <div class="small muted truncate">${[s.amount, s.wait_seconds ? tr('wait {0}s', s.wait_seconds) : '', s.cadence ? cadenceText(s.cadence) : '',
            paused ? tr("paused until {0}", dayLabel(s.paused_until, false)) : ''].filter(Boolean).join(' · ') || tr('every time')}</div>
        </div>
        <hxk-button size="sm" variant="ghost" icon=${open ? 'chevron-left' : 'edit'} @click=${() => (this.edit = open ? '' : (s.id || `new${i}`))}></hxk-button>
        <hxk-button size="sm" variant="ghost" icon="trash" @click=${() => this.setSteps(this.steps.filter((_, k) => k !== i))}></hxk-button>
      </div>
      ${open ? html`<div class="col" style="padding-left:32px">
        <div class="form">
          ${s.product_id ? nothing : html`<hxk-field label=${tr("Description")} .value=${s.label} @change=${(e: CustomEvent) => this.updStep(i, { label: e.detail })}></hxk-field>`}
          <hxk-field label=${tr("Quantity")} placeholder=${tr("e.g. 2 drops, a walnut-sized amount")} .value=${s.amount || ''} @change=${(e: CustomEvent) => this.updStep(i, { amount: e.detail })}></hxk-field>
          <hxk-field label=${tr("Wait after")} type="int" unit=${tr("seconds")} .value=${s.wait_seconds || 0} @change=${(e: CustomEvent) => this.updStep(i, { wait_seconds: e.detail || 0 })}></hxk-field>
          <hxk-field label=${tr("Optional")} type="bool" .value=${!!s.optional} @change=${(e: CustomEvent) => this.updStep(i, { optional: e.detail })}></hxk-field>
          <hxk-field class="full" label=${tr("Note")} .value=${s.note || ''} @change=${(e: CustomEvent) => this.updStep(i, { note: e.detail })}></hxk-field>
        </div>
        <h3>${tr("Frequency of this step")}</h3>
        <hygieia-cadence allowNone .value=${s.cadence || null} @change=${(e: CustomEvent) => this.updStep(i, { cadence: e.detail })}></hygieia-cadence>
        <div class="small muted">${tr("With its own frequency (e.g. retinol 3 times a week) the step appears only when needed, and the steps that don't go together alternate by themselves.")}</div>
        <h3>${tr("Pause")}</h3>
        <div class="row wrap">
          ${paused ? html`<span class="pill">${tr("paused until")} ${dayLabel(s.paused_until, false)}</span>
            <hxk-button size="sm" @click=${() => this.updStep(i, { paused_until: null })}>${tr("Resume")}</hxk-button>`
          : [7, 14, 30].map(d => html`<hxk-button size="sm" @click=${() => this.updStep(i, { paused_until: addDays(today(), d) })}>${d} ${tr("days")}</hxk-button>`)}
        </div>
        ${s.product_id ? html`<div><button class="link small" @click=${() => this.host.navigate('products/' + s.product_id)}>${tr("Open the product ›")}</button></div>` : nothing}
      </div>` : nothing}
    </div>`;
  }

  private picker() {
    const items = search(this.products.filter(p => ['in_use', 'stock', 'paused'].includes(p.status)), this.q, p => `${p.brand} ${p.name} ${p.category}`);
    return html`<div class="sheet" @click=${(e: Event) => { if (e.target === e.currentTarget) this.picking = false; }}><div class="card col">
      <div class="between"><h2>${tr("Add a step")}</h2><hxk-button variant="ghost" icon="x" @click=${() => (this.picking = false)}></hxk-button></div>
      <input class="in" placeholder=${tr("Search a product or write the step (e.g. massage)")} .value=${this.q} @input=${(e: any) => (this.q = e.target.value)}
        @keydown=${(e: KeyboardEvent) => e.key === 'Enter' && (items.length === 1 ? this.addProduct(items[0]) : this.addLabel())} autofocus>
      <div class="list">${items.slice(0, 30).map(p => html`<div class="li" @click=${() => this.addProduct(p)}>
        <div class="grow"><div class="truncate">${productName(p)}</div><div class="small muted">${label(this.m?.categories, p.category)}${(p.actives || []).length ? ' · ' + p.actives.map((a: any) => label(this.m?.actives, a.name)).join(', ') : ''}</div></div>
        <hxk-icon name="plus"></hxk-icon></div>`)}</div>
      ${this.q.trim() ? html`<hxk-button icon="plus" @click=${() => this.addLabel()}>${tr("Step without product: «")}${this.q.trim()}»</hxk-button>` : nothing}
      <button class="link small" @click=${() => this.host.navigate('products', { new: '1' })}>${tr("The product isn't there? Add it ›")}</button>
    </div></div>`;
  }

  render() {
    const back = html`<button class="link" @click=${() => this.host.navigate('routine')}>‹ Routine</button>`;
    if (this.r === undefined) return html`<div class="page">${back}<hxk-state kind="loading"></hxk-state></div>`;
    if (this.r === 'missing') return html`<div class="page">${back}<hxk-state kind="empty" text=${tr("Routine not found")}></hxk-state></div>`;
    if (this.r === null) return html`<div class="page">${back}<hxk-state kind="offline" @retry=${() => this.load()}></hxk-state></div>`;
    const r = this.r, st = r.stats || {}, plan = r.plan || {};
    const s = STATE[plan.state] || STATE.rest;
    return html`<div class="page">
      ${back}
      <div class="head">
        <input class="title" .value=${r.name} @change=${(e: any) => e.target.value.trim() && this.patch({ name: e.target.value.trim() })} aria-label=${tr("Name")}>
        <button class="link" title=${tr("f::Favourite")}
          @click=${() => this.patch({ favorite: !r.favorite })}>${icon('star', 22, r.favorite ? 'warning' : 'muted')}</button>
      </div>
      <div class="row wrap">
        <hxk-badge tone=${s.tone}>${s.text}</hxk-badge><span class="small muted">${plan.state === 'blocked' || plan.state === 'paused' ? plan.reason : plan.hint}</span>
        <span class="grow"></span>
        ${r.status === 'active' ? html`<hxk-button size="sm" icon="pause" @click=${() => this.patch({ status: 'paused' })}>${tr("alt::Pause")}</hxk-button>`
          : html`<hxk-button size="sm" icon="play" @click=${() => this.patch({ status: 'active' })}>${tr("Turn back on")}</hxk-button>`}
        <hxk-button size="sm" variant="ghost" icon="trash" @click=${() => this.archive()}>${tr("f::Archive")}</hxk-button>
      </div>

      <div class="card sec">
        <h2>${tr("Steps")}</h2>
        ${this.steps.length ? html`<div>${this.steps.map((x, i) => this.stepEditor(x, i))}</div>` : html`<div class="empty">${tr("No steps. Add the products in the order you use them.")}</div>`}
        <div><hxk-button icon="plus" @click=${() => (this.picking = true)}>${tr("Add step")}</hxk-button></div>
        ${(r.check || []).map((n: any) => html`<div class="note ${n.level}">${n.level === 'warning' ? icon('alert', 13, 'warning') : icon('info', 13, 'info')} ${n.text}</div>`)}
      </div>
      ${this.dirty ? html`<div class="save">
        <input class="in grow" placeholder=${tr("Why are you changing it? (optional, e.g. irritated skin)")} .value=${this.reason} @input=${(e: any) => (this.reason = e.target.value)}>
        <hxk-button variant="ghost" @click=${() => this.load()}>${tr("Cancel")}</hxk-button>
        <hxk-button variant="primary" icon="check" ?loading=${this.saving} @click=${() => this.saveSteps()}>${tr("Save")}</hxk-button>
      </div>` : nothing}

      <div class="card sec">
        <h2>${tr("When")}</h2>
        <div class="chips">${Object.entries(this.m?.slots || {}).map(([k, l]) => html`<button class="chip" aria-pressed=${r.slot === k}
          @click=${() => this.patch({ slot: k })}>${slotIcon(k)} ${l}</button>`)}</div>
        <h3>${tr("Goal")}</h3>
        <hygieia-cadence .value=${r.cadence} @change=${(e: CustomEvent) => this.patch({ cadence: e.detail })}></hygieia-cadence>
        <div class="row wrap"><span class="small">${tr("At most")}</span>
          <input class="in num" type="number" min="1" max="5" .value=${String(r.max_per_day || 1)} @change=${(e: any) => this.patch({ max_per_day: Number(e.target.value) || 1 })}>
          <span class="small">${tr("times a day")}</span></div>
        <h3>${tr("Zones")}</h3>
        <div class="chips">${(this.m?.areas || []).map((a: any) => html`<button class="chip" aria-pressed=${(r.areas || []).includes(a.value)}
          @click=${() => this.patch({ areas: (r.areas || []).includes(a.value) ? r.areas.filter((x: string) => x !== a.value) : [...(r.areas || []), a.value] })}>${a.label}</button>`)}</div>
        ${this.others.length ? html`<h3>${tr("Never on the same day as")}</h3>
          <div class="chips">${this.others.filter(o => o.status !== 'archived').map(o => html`<button class="chip" aria-pressed=${(r.not_same_day_as || []).includes(o.id)}
            @click=${() => this.patch({ not_same_day_as: (r.not_same_day_as || []).includes(o.id) ? r.not_same_day_as.filter((x: string) => x !== o.id) : [...(r.not_same_day_as || []), o.id] })}>${o.name}</button>`)}</div>
          <div class="small muted">${tr("Routines with active ingredients that don't go together (e.g. retinol and acids) already exclude each other.")}</div>` : nothing}
        <h3>${tr("Reminders")}</h3>
        <label class="row"><input type="checkbox" .checked=${!!r.reminder} @change=${(e: any) => this.patch({ reminder: e.target.checked })}>
          <span>${tr("Remind me when I'm behind")}</span></label>
        <div class="small muted">${tr("Only when you are behind, at most 2 a week (changed in the settings), never piled up: a single notice that updates with how many times you skipped it.")}${r.reminder_state?.silenced_until ? tr(" Muted until {0}.", dayLabel(r.reminder_state.silenced_until, false)) : ''}</div>
      </div>

      <div class="card sec">
        <h2>${tr("Trend")}</h2>
        <hxk-stat .items=${[{ label: tr('Goal kept'), value: st.adherence ?? '–', unit: st.adherence !== null && st.adherence !== undefined ? '%' : '' },
          { label: tr('In a row'), value: st.streak || 0, unit: st.per === 'month' ? tr('months') : tr('weeks') }, { label: tr('Times in total'), value: st.total || 0 },
          { label: tr('f::Last'), value: relDays(st.last_done) }]}></hxk-stat>
        ${(st.history || []).length ? html`<div class="hist" title=${st.per === 'month' ? tr('Per month') : tr('Per week')}>
          ${st.history.map((h: any) => html`<div class="bar ${h.met ? 'met' : ''}" title="${dayLabel(h.start, false)}: ${h.done}${h.need ? '/' + h.need : ''}"
            style="height:${Math.max(6, Math.min(100, (h.done / Math.max(1, h.need || h.done || 1)) * 100))}%"></div>`)}</div>
          <div class="small muted">${tr("Latest")} ${st.history.length} ${st.per === 'month' ? tr('months') : tr('weeks')}${tr('; green = goal reached')}${st.skipped ? tr(' · skipped {0} times', st.skipped) : ''}</div>` : nothing}
      </div>

      <div class="card sec">
        <div class="between"><h2>${tr("Versions")}</h2>${(r.versions || []).length > 1 ? html`<hxk-button size="sm" icon="undo" @click=${() => this.undoVersion()}>${tr("Back to the previous one")}</hxk-button>` : nothing}</div>
        ${(r.versions || []).map((v: any) => html`<div class="ver">
          <b class="tnum">v${v.version}</b>
          <div class="grow"><div class="small">${dayLabel(v.valid_from, false)}${v.by && v.by !== 'webui' ? tr(" · from {0}", v.by === 'assistant' ? 'assistant' : v.by) : ''}</div>
            ${v.diff ? html`<div class="small muted">${v.diff}</div>` : nothing}
            ${v.reason ? html`<div class="small">«${v.reason}»</div>` : nothing}</div></div>`)}
      </div>
      ${this.picking ? this.picker() : nothing}
    </div>`;
  }
}
