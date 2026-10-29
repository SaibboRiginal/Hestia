/** Hercules widgets for Home and dashboards (§8.2). Local mirror first, so most of them work offline too. */
import { HestiaElement, html, css, nothing } from '@hestia/webui-sdk';
import type { QuickAction } from '@hestia/webui-sdk';
import { API, Local, local, nowIso, uuid } from './data';
import { rest } from './today';
import { GROUP_LABEL, WEEKDAYS, dayLabel, dur, herculesStyles, kg, localDay, minutes, num, parseNum, search } from './util';

abstract class Widget extends HestiaElement {
  protected L!: Local;
  private _off: (() => void) | null = null;
  static styles = [...HestiaElement.styles, herculesStyles, css`
    :host { display: block; height: 100%; }
    .w { display: flex; flex-direction: column; gap: 8px; height: 100%; padding: 2px; }
    .w > * { flex-shrink: 0; }   /* a short cell must not squash the title line (truncate hides it whole) */
    .big { font-size: 22px; font-weight: 650; line-height: 1.1; }
    .click { cursor: pointer; }
  `];
  connectedCallback() {
    super.connectedCallback();
    this.L = local(this.host);
    this._off = this.L.onChange(() => this.requestUpdate());
    this.L.ready.then(() => { this.load(); this.requestUpdate(); });
    this.onHost('refresh', () => this.load());
    this.onHost('visible', () => this.load());
  }
  disconnectedCallback() { super.disconnectedCallback(); this._off?.(); }
  protected load(): void { /* widget specific */ }
  protected get size() { return this.ctx?.size || 'm'; }
}

export class HerculesNextWidget extends Widget {
  static properties = { ...HestiaElement.properties, next: { state: true } };
  declare next: any;
  protected async load() { this.next = (await this.L.cached(`${API}/next`)).data; }
  render() {
    const act = this.L?.activeSession();
    if (act) return html`<div class="w click" @click=${() => this.host.navigate('allenamento')}>
      <span class="small muted">In corso</span><div class="big truncate">${act.name}</div>
      <div><hxk-button variant="primary" icon="play">Riprendi</hxk-button></div></div>`;
    const n = this.next;
    if (n === undefined) return html`<hxk-state kind="loading"></hxk-state>`;
    const t = n?.template;
    if (!t) return html`<div class="w"><div class="muted">Nessuna scheda ancora.</div><div><hxk-button icon="plus" @click=${() => this.host.navigate('schede')}>Crea una scheda</hxk-button></div></div>`;
    const done = (n.done_today || []).length > 0;
    const exs = this.L.exercises();
    return html`<div class="w">
      <span class="small muted">${done ? html`<hxk-icon name="check" size=${12} tone="success"></hxk-icon> Fatto oggi · prossimo` : n.reason || 'Prossimo allenamento'}</span>
      <div class="big truncate click" @click=${() => this.host.navigate('schede/' + t.id)}>${t.name}</div>
      <div class="small muted">${(t.items || []).length} esercizi${n.estimated_minutes ? ` · ${minutes(n.estimated_minutes)}` : ''}</div>
      ${this.size === 'l' ? html`<div class="small truncate">${(t.items || []).slice(0, 5).map((i: any) => exs.get(i.exercise_id)?.name).filter(Boolean).join(' · ')}</div>` : nothing}
      <div class="row"><hxk-button variant="primary" icon="play" @click=${() => this.host.navigate('allenamento', { scheda: t.id })}>Inizia</hxk-button></div>
    </div>`;
  }
}

export class HerculesWeekWidget extends Widget {
  static properties = { ...HestiaElement.properties, sum: { state: true } };
  declare sum: any;
  protected async load() { this.sum = (await this.L.cached(`${API}/summary`)).data; }
  render() {
    if (!this.L?.loaded && this.sum === undefined) return html`<hxk-state kind="loading"></hxk-state>`;
    const now = new Date();
    const monday = new Date(now); monday.setDate(now.getDate() - ((now.getDay() + 6) % 7));
    const days = Array.from({ length: 7 }, (_, i) => { const d = new Date(monday); d.setDate(monday.getDate() + i); return localDay(d); });
    const doneDays = new Set(this.L.doneSessions().map(s => localDay(s.started_at)));
    const goal = this.sum?.goals?.[0];
    const count = days.filter(d => doneDays.has(d)).length;
    return html`<div class="w click" @click=${() => this.host.navigate('progressi')}>
      <div class="between"><span class="small muted">Questa settimana</span>${goal?.behind ? html`<hxk-badge tone="warning">indietro</hxk-badge>` : nothing}</div>
      <div class="big tnum">${count}${goal ? html`<span class="muted" style="font-size:15px"> / ${goal.times}</span>` : nothing} <span style="font-size:14px;font-weight:400" class="muted">allenamenti</span></div>
      <div class="row" style="gap:4px">${days.map((d, i) => html`<div class="col" style="align-items:center;gap:2px;flex:1">
        <span style="width:100%;max-width:26px;height:26px;border-radius:7px;display:block;background:${doneDays.has(d) ? 'var(--success)' : d === localDay(now) ? 'var(--accent-soft)' : 'var(--surface-3)'}"></span>
        <span class="small muted">${WEEKDAYS[i][0]}</span></div>`)}</div>
      ${(this.sum?.activities || []).length ? html`<div class="row small" style="gap:10px;flex-wrap:wrap">${this.sum.activities.map((a: any) => html`<span class="row" style="gap:4px"><hxk-icon name="run" size=${12} tone=${a.done >= a.times ? 'success' : 'accent'}></hxk-icon><span class="tnum">${a.label} ${a.done}/${a.times}</span></span>`)}</div>` : nothing}
      ${this.size !== 's' && this.sum?.week ? html`<div class="small muted">${num(this.sum.week.volume)} kg · ${this.sum.week.sets} serie${goal?.streak ? html` · <hxk-icon name="flame" size=${12} tone="warning"></hxk-icon> ${goal.streak} settimane di fila` : ''}</div>` : nothing}
    </div>`;
  }
}

export class HerculesQuickWidget extends Widget {
  render() {
    const action: QuickAction = { method: 'POST', path: `${API}/quick/{id}`, undo: { method: 'DELETE', path: `${API}/quick/{id}` } };
    return html`<div class="w"><span class="small muted">Segna fatto oggi</span>
      <hxk-quicklog .host=${this.host} source=${`${API}/quick/templates`} .action=${action} ?compact=${this.size === 's'}
        @logged=${(e: CustomEvent) => { this.L.sync(); if (e.detail?.chip?.id?.startsWith('resume:')) this.host.navigate('allenamento'); }}></hxk-quicklog></div>`;
  }
}

export class HerculesPrsWidget extends Widget {
  static properties = { ...HestiaElement.properties, prs: { state: true } };
  declare prs: any[] | null | undefined;
  protected async load() { const r = await this.L.cached(`${API}/stats`, { per: 'week', count: 4 }); this.prs = r.data ? r.data.recent_prs || [] : null; }
  render() {
    if (this.prs === undefined) return html`<hxk-state kind="loading"></hxk-state>`;
    if (this.prs === null) return html`<hxk-state kind="offline"></hxk-state>`;
    if (!this.prs.length) return html`<div class="w"><span class="small muted">Record recenti</span><div class="muted">Nessun record negli ultimi 30 giorni.</div></div>`;
    return html`<div class="w"><span class="small muted"><hxk-icon name="trophy" size=${12} tone="warning"></hxk-icon> Record recenti</span><div class="list">
      ${this.prs.slice(0, this.size === 'l' || this.size === 'xl' ? 8 : 4).map(p => html`<div class="li" style="padding:6px 2px" @click=${() => this.host.navigate('esercizi/' + p.exercise_id)}>
        <div class="grow"><div class="truncate">${p.exercise}</div><div class="small muted">${p.label} · ${dayLabel(p.date, false)}</div></div><b class="tnum">${kg(p.value)}</b></div>`)}</div></div>`;
  }
}

export class HerculesExerciseWidget extends Widget {
  static properties = { ...HestiaElement.properties, detail: { state: true } };
  declare detail: any;
  private exId(): string | null {
    const name = this.ctx?.params?.exercise || '';
    if (!name) return null;
    return search(this.L.list('exercise'), name)[0]?.id || null;
  }
  protected async load() {
    const id = this.exId();
    this.detail = id ? (await this.L.cached(`${API}/exercises/${id}`)).data : null;
  }
  render() {
    if (!this.ctx?.params?.exercise) return html`<div class="w muted">Scegli un esercizio nelle impostazioni del widget.</div>`;
    const d = this.detail;
    if (d === undefined) return html`<hxk-state kind="loading"></hxk-state>`;
    if (!d) return html`<div class="w muted">Esercizio «${this.ctx.params.exercise}» non trovato o offline.</div>`;
    const hist = (d.history || []).filter((h: any) => h.best_e1rm);
    const best = d.records?.best_e1rm;
    return html`<div class="w click" @click=${() => this.host.navigate('esercizi/' + d.exercise.id)}>
      <div class="between"><span class="truncate"><b>${d.exercise.name}</b></span>${d.stall ? html`<hxk-badge tone="warning">stallo</hxk-badge>` : nothing}</div>
      <div class="row"><span class="big tnum">${best ? kg(best.value) : '–'}</span><span class="small muted">kg 1RM stimato${d.records?.heaviest ? ` · max ${kg(d.records.heaviest.value)}×${d.records.heaviest.reps}` : ''}</span></div>
      ${hist.length > 1 ? html`<hxk-chart type="line" height=${this.size === 'xl' ? 220 : 120} unit="kg" .labels=${hist.map((h: any) => dayLabel(h.date, false))} .series=${[{ name: '1RM stimato', values: hist.map((h: any) => h.best_e1rm) }]}></hxk-chart>` : nothing}
    </div>`;
  }
}

export class HerculesVolumeWidget extends Widget {
  static properties = { ...HestiaElement.properties, stats: { state: true } };
  declare stats: any;
  private get weeks() { return Math.max(1, Math.min(26, Number(this.ctx?.params?.weeks) || 4)); }
  protected async load() { this.stats = (await this.L.cached(`${API}/stats`, { per: 'week', count: this.weeks })).data; }
  render() {
    const st = this.stats;
    if (st === undefined) return html`<hxk-state kind="loading"></hxk-state>`;
    if (!st) return html`<hxk-state kind="offline"></hxk-state>`;
    const tot: Record<string, number> = {};
    for (const p of st.periods || []) for (const [g, v] of Object.entries(p.groups || {})) tot[g] = (tot[g] || 0) + Number(v);
    const keys = Object.keys(GROUP_LABEL);
    return html`<div class="w click" @click=${() => this.host.navigate('progressi')}>
      <span class="small muted">Serie per gruppo · ${this.weeks === 1 ? 'questa settimana' : `media ${this.weeks} settimane`}</span>
      <hxk-chart type="bar" height="140" .labels=${keys.map(k => GROUP_LABEL[k])} .series=${[{ name: 'Serie a settimana', values: keys.map(k => Math.round(((tot[k] || 0) / this.weeks) * 10) / 10) }]}></hxk-chart>
    </div>`;
  }
}

export class HerculesWeightWidget extends Widget {
  static properties = { ...HestiaElement.properties, value: { state: true } };
  declare value: string;
  constructor() { super(); this.value = ''; }
  private log() {
    const v = parseNum(this.value);
    if (!v || v < 20 || v > 400) { this.host.toast('Peso non valido', 'warning'); return; }
    this.L.put('measurement', uuid(), { kind: 'bodyweight', value: v, taken_at: nowIso(), unit: 'kg', notes: '' });
    this.value = '';
    this.host.toast(`Peso ${kg(v)} kg`, 'success');
  }
  render() {
    if (!this.L?.loaded) return html`<hxk-state kind=${this.host.online ? 'loading' : 'offline'}></hxk-state>`;
    const pts = this.L.list('measurement').filter(m => m.kind === 'bodyweight').sort((a, b) => a.taken_at.localeCompare(b.taken_at)).slice(-30);
    const last = pts[pts.length - 1], prev = pts.length > 1 ? pts[0] : null;
    return html`<div class="w">
      <div class="between click" @click=${() => this.host.navigate('corpo')}><span class="small muted">Peso corporeo</span>${last ? html`<span class="small muted">${dayLabel(last.taken_at)}</span>` : nothing}</div>
      <div class="row"><span class="big tnum">${last ? kg(last.value) : '–'}</span><span class="muted">kg</span>
        ${prev && last ? html`<span class="small muted">${last.value - prev.value >= 0 ? '+' : ''}${kg(Math.round((last.value - prev.value) * 10) / 10)} in ${pts.length} misure</span>` : nothing}</div>
      ${this.size !== 's' && pts.length > 1 ? html`<hxk-chart type="line" height="90" unit="kg" .labels=${pts.map(m => dayLabel(m.taken_at, false))} .series=${[{ name: 'Peso', values: pts.map(m => m.value) }]}></hxk-chart>` : nothing}
      <div class="row"><input class="in num" inputmode="decimal" placeholder=${last ? kg(last.value) : 'kg'} .value=${this.value}
        @input=${(e: any) => (this.value = e.target.value)} @keydown=${(e: KeyboardEvent) => e.key === 'Enter' && this.log()}>
        <hxk-button size="sm" icon="plus" @click=${() => this.log()}>Salva</hxk-button></div>
    </div>`;
  }
}

export class HerculesLiveWidget extends Widget {
  static properties = { ...HestiaElement.properties, tick: { state: true } };
  declare tick: number;
  private timer: any = null;
  connectedCallback() { super.connectedCallback(); this.timer = setInterval(() => { if (this.L?.activeSession() || rest.until) this.tick = Date.now(); }, 1000); }
  disconnectedCallback() { super.disconnectedCallback(); clearInterval(this.timer); }
  render() {
    const act = this.L?.activeSession();
    if (!act) return html`<div class="w"><span class="muted">Nessun allenamento in corso.</span>
      <div><hxk-button icon="play" @click=${() => this.host.navigate('allenamento')}>Vai ad Allenamento</hxk-button></div></div>`;
    const sets = this.L.setsOf(act.id);
    const total = (act.exercises || []).reduce((n: number, b: any) => n + (b.planned || []).length, 0);
    const exs = this.L.exercises();
    const doneBlocks = new Set(sets.map(s => s.session_exercise_id));
    const current = (act.exercises || []).find((b: any) => sets.filter(s => s.session_exercise_id === b.id).length < (b.planned || []).length) || null;
    const left = rest.until ? (rest.until - Date.now()) / 1000 : 0;
    return html`<div class="w click" @click=${() => this.host.navigate('allenamento')}>
      <div class="between"><b class="truncate">${act.name}</b><span class="small muted tnum">${dur((Date.now() - Date.parse(act.started_at)) / 1000)}</span></div>
      <div class="small muted">${sets.length}/${total} serie · ${doneBlocks.size}/${(act.exercises || []).length} esercizi</div>
      ${current ? html`<div class="truncate">Ora: <b>${exs.get(current.exercise_id)?.name || '?'}</b></div>` : nothing}
      ${rest.until ? html`<div class="pill tnum" style="font-size:15px"><hxk-icon name="timer" size=${14}></hxk-icon> ${left > 0 ? dur(left) : 'recupero finito'}</div>` : nothing}
    </div>`;
  }
}
