/**
 * <hercules-templates> — "Schede": workout types, the weekly program and the training goals.
 * <hercules-template>  — one template: exercises, planned sets, progression, rest; edits are local first (offline).
 */
import { HestiaElement, html, css, nothing, plural, tr } from '@hestia/webui-sdk';
import { API, Local, local, uuid } from './data';
import { GROUPS, GROUP_LABEL, PROGRESSION, SET_TYPE_LABEL, WEEKDAYS, dur, herculesStyles, kg, minutes, muscleText, parseNum, plannedLabel, relDays, usesTime, usesWeight } from './util';

abstract class LocalPage extends HestiaElement {
  protected L!: Local;
  private _off: (() => void) | null = null;
  connectedCallback() {
    super.connectedCallback();
    this.L = local(this.host);
    this._off = this.L.onChange(() => this.requestUpdate());
    this.L.ready.then(() => { this.loaded(); this.requestUpdate(); });
    this.onHost('refresh', () => { this.L.sync(); this.loaded(); });
  }
  disconnectedCallback() { super.disconnectedCallback(); this._off?.(); }
  protected loaded(): void { /* page specific */ }
  protected notReady() {
    if (!this.L || this.L.loaded) return null;
    return html`<div class="page">${this.host.online ? html`<hxk-state kind="loading"></hxk-state>`
      : html`<hxk-state kind="offline" text=${tr("Open Workout once online to download the data.")} @retry=${() => this.L.sync()}></hxk-state>`}</div>`;
  }
}
export { LocalPage };

export class HerculesTemplates extends LocalPage {
  static properties = { ...HestiaElement.properties, goals: { state: true }, newGoal: { state: true }, editProgram: { state: true } };
  declare goals: any[] | null;
  declare newGoal: { times: number; per: string; scope: string; target_id: string } | null;
  declare editProgram: any;
  static styles = [...HestiaElement.styles, herculesStyles, css`
    .grid { --min: 260px; }
    .tpl { display: flex; flex-direction: column; gap: 6px; }
    .week { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 6px; }
    .day { border: 1px solid var(--border); border-radius: var(--radius-md); padding: 6px; min-height: 64px; display: flex; flex-direction: column; gap: 4px; font-size: 12px; }
    .day select { width: 100%; font-size: 12px; padding: 4px; }
    .goal { display: flex; align-items: center; gap: 10px; }
    .dots { display: flex; gap: 3px; }
    .dot { width: 10px; height: 10px; border-radius: 50%; background: var(--surface-3); }
    .dot.on { background: var(--success); }
    @media (max-width: 600px) { .week { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
  `];
  constructor() { super(); this.goals = null; this.newGoal = null; this.editProgram = null; }

  protected async loaded() {
    const r = await this.L.cached(`${API}/goals`);
    this.goals = r.data?.items ?? [];
  }

  private create() {
    const t = this.L.put('template', uuid(), { name: tr('New plan'), favorite: false, items: [], folder: '', notes: '', color: '', position: this.L.templates().length, archived: false, revision: 0 });
    this.host.navigate('schede/' + t.id, { nuova: '1' });
  }

  private program(): any | null { return this.L.list('program').find(p => p.active) || null; }

  private saveProgram(p: any) {
    for (const o of this.L.list('program')) if (o.id !== p.id && o.active) this.L.put('program', o.id, { ...o, active: false });
    this.L.put('program', p.id, p);
  }

  private async saveGoal() {
    const g = this.newGoal!;
    const body: any = { times: g.times, per: g.per, scope: g.scope, target_id: g.scope === 'any' ? null : g.target_id, active: true };
    this.L.put('goal', uuid(), body);
    this.newGoal = null;
    await this.L.sync();
    this.loaded();
  }
  private async removeGoal(g: any) {
    this.L.remove('goal', g.id);
    await this.L.sync();
    this.loaded();
  }

  render() {
    const nr = this.notReady(); if (nr) return nr;
    const L = this.L;
    const exs = L.exercises();
    const tpls = L.templates();
    const prog = this.editProgram || this.program();
    return html`<div class="page">
      <div class="head"><h1>${tr("Workout plans")}</h1><span class="sub">${tr("your workout types")}</span><span class="grow"></span>
        <hxk-button variant="ghost" icon="heart" @click=${() => this.host.assistant({ label: tr('Create a plan'), prompt: tr('Help me create a workout plan.'), suggestions: [tr('A push pull legs program'), tr('Full body 3 times a week'), tr('40-minute plan')] })}>${tr("Create it with the assistant")}</hxk-button>
        <hxk-button variant="primary" icon="plus" @click=${() => this.create()}>${tr("New plan")}</hxk-button></div>

      ${tpls.length ? html`<div class="grid">${tpls.map(t => {
        const last = L.doneSessions().filter(s => s.template_id === t.id).pop();
        const muscles = new Set<string>();
        (t.items || []).forEach((i: any) => (exs.get(i.exercise_id)?.primary_muscles || []).forEach((m: string) => muscles.add(m)));
        const groups = Object.entries(GROUP_LABEL).filter(([g]) => GROUPS[g].some(m => muscles.has(m))).map(([, l]) => l);
        return html`<hxk-card clickable heading=${t.name} subtitle=${tr("{0} · last {1}", plural((t.items || []).length, 'exercise', 'exercises'), relDays(last?.started_at))}
            @click=${() => this.host.navigate('schede/' + t.id)}>
          ${t.favorite ? html`<hxk-icon slot="actions" name="star" size=${14} tone="warning" title=${tr("f::Favourite")}></hxk-icon>` : nothing}
          <div class="tpl"><div class="small muted truncate">${(t.items || []).map((i: any) => exs.get(i.exercise_id)?.name).filter(Boolean).join(', ') || tr('Empty')}</div>
            ${groups.length ? html`<div class="chips">${groups.map(g => html`<span class="pill">${g}</span>`)}</div>` : nothing}</div>
        </hxk-card>`;
      })}</div>` : html`<hxk-state kind="empty" text=${tr("No plan: create one (e.g. Push, Pull, Legs).")}></hxk-state>`}

      <div class="card col">
        <div class="between"><h2>${tr("Weekly programme")}</h2>
          ${prog ? html`<span class="small muted">${prog.mode === 'rotation' ? tr('in rotation: the next on the list') : tr('by day of the week')}</span>` : nothing}</div>
        ${prog ? html`
          <div class="row wrap">
            <input class="in grow" .value=${prog.name} @change=${(e: any) => this.saveProgram({ ...prog, name: e.target.value || tr('Program') })}>
            <select class="in" .value=${prog.mode} @change=${(e: any) => this.saveProgram({ ...prog, mode: e.target.value })}>
              <option value="weekly">${tr("Fixed days")}</option><option value="rotation">${tr("Rotation")}</option></select>
          </div>
          ${prog.mode === 'rotation' ? html`<div class="col">
              ${(prog.days || []).map((d: any, i: number) => html`<div class="row"><span class="pill">${i + 1}</span><span class="grow">${L.get('template', d.template_id)?.name || '?'}</span>
                <hxk-button size="sm" variant="ghost" icon="x" @click=${() => this.saveProgram({ ...prog, days: prog.days.filter((_: any, j: number) => j !== i) })}></hxk-button></div>`)}
              <select class="in" @change=${(e: any) => { if (e.target.value) this.saveProgram({ ...prog, days: [...(prog.days || []), { weekday: null, template_id: e.target.value, label: '' }] }); e.target.value = ''; }}>
                <option value="">${tr("+ Add to the rotation…")}</option>${tpls.map(t => html`<option value=${t.id}>${t.name}</option>`)}</select></div>`
            : html`<div class="week">${WEEKDAYS.map((w, wd) => {
              const d = (prog.days || []).find((x: any) => x.weekday === wd);
              return html`<div class="day"><b>${w}</b>
                <select class="in" .value=${d?.template_id || ''} @change=${(e: any) => {
                  const days = (prog.days || []).filter((x: any) => x.weekday !== wd);
                  if (e.target.value) days.push({ weekday: wd, template_id: e.target.value, label: '' });
                  this.saveProgram({ ...prog, days: days.sort((a: any, b: any) => a.weekday - b.weekday) });
                }}><option value="">${tr("Rest")}</option>${tpls.map(t => html`<option value=${t.id} ?selected=${d?.template_id === t.id}>${t.name}</option>`)}</select></div>`;
            })}</div>`}
          <div class="row"><hxk-button size="sm" variant="ghost" @click=${() => this.saveProgram({ ...prog, active: false })}>${tr("Turn off programme")}</hxk-button></div>`
        : html`<div class="muted small">${tr("Without a programme Hestia suggests the favourite plan done least recently.")}</div>
          <div><hxk-button icon="calendar" ?disabled=${!tpls.length} @click=${() => this.saveProgram({ id: uuid(), name: tr('My programme'), mode: 'weekly', active: true, days: [], notes: '' })}>${tr("Create programme")}</hxk-button></div>`}
      </div>

      <div class="card col">
        <div class="between"><h2>${tr("Goals")}</h2><span class="small muted">${tr("e.g. 3 times a week")}</span></div>
        ${this.goals === null ? html`<hxk-state kind="loading"></hxk-state>` : this.goals.length ? this.goals.map(g => html`<div class="goal">
            <div class="grow"><div>${g.progress?.label || g.label}</div><div class="small muted">${g.progress?.hint || ''}${g.progress?.streak ? html` · <hxk-icon name="flame" size=${12} tone="warning"></hxk-icon> ${tr("sets of")} ${g.progress.streak}` : ''}</div></div>
            <div class="dots">${Array.from({ length: g.times }, (_, i) => html`<span class="dot ${i < (g.progress?.done || 0) ? 'on' : ''}"></span>`)}</div>
            <hxk-button size="sm" variant="ghost" icon="trash" @click=${() => this.removeGoal(g)}></hxk-button></div>`)
          : html`<div class="muted small">${tr("No goal: add a generic one and then, if you want, a more specific one (a plan or a muscle).")}</div>`}
        ${this.newGoal ? html`<div class="row wrap">
            <input class="in num" type="number" min="1" max="31" .value=${String(this.newGoal.times)} @input=${(e: any) => (this.newGoal = { ...this.newGoal!, times: Number(e.target.value) || 1 })}>
            <span>${tr("times a")}</span>
            <select class="in" .value=${this.newGoal.per} @change=${(e: any) => (this.newGoal = { ...this.newGoal!, per: e.target.value })}>
              <option value="day">${tr("day")}</option><option value="week">${tr("week")}</option><option value="month">${tr("month")}</option></select>
            <select class="in" .value=${this.newGoal.scope} @change=${(e: any) => (this.newGoal = { ...this.newGoal!, scope: e.target.value, target_id: '' })}>
              <option value="any">${tr("any workout")}</option><option value="template">${tr("a program")}</option><option value="muscle">${tr("a muscle group")}</option></select>
            ${this.newGoal.scope === 'template' ? html`<select class="in" @change=${(e: any) => (this.newGoal = { ...this.newGoal!, target_id: e.target.value })}>
                <option value="">${tr("choose…")}</option>${tpls.map(t => html`<option value=${t.id}>${t.name}</option>`)}</select>` : nothing}
            ${this.newGoal.scope === 'muscle' ? html`<select class="in" @change=${(e: any) => (this.newGoal = { ...this.newGoal!, target_id: e.target.value })}>
                <option value="">${tr("choose…")}</option>${Object.entries(GROUP_LABEL).map(([k, v]) => html`<option value=${k}>${v}</option>`)}</select>` : nothing}
            <hxk-button variant="primary" ?disabled=${this.newGoal.scope !== 'any' && !this.newGoal.target_id} @click=${() => this.saveGoal()}>${tr("Save")}</hxk-button>
            <hxk-button variant="ghost" @click=${() => (this.newGoal = null)}>${tr("Cancel")}</hxk-button></div>`
          : html`<div><hxk-button icon="plus" @click=${() => (this.newGoal = { times: 3, per: 'week', scope: 'any', target_id: '' })}>${tr("Add goal")}</hxk-button></div>`}
      </div>
    </div>`;
  }
}

export class HerculesTemplate extends LocalPage {
  static properties = { ...HestiaElement.properties, picking: { state: true }, open: { state: true }, detail: { state: true } };
  declare picking: boolean;
  declare open: string;
  declare detail: any;
  static styles = [...HestiaElement.styles, herculesStyles, css`
    .item { display: flex; flex-direction: column; gap: 8px; }
    .ih { display: flex; align-items: center; gap: 8px; }
    .ih .name { font-weight: 600; cursor: pointer; }
    .srow { display: grid; grid-template-columns: 110px 70px 70px 80px 36px; gap: 6px; align-items: center; }
    .srow.reps { grid-template-columns: 110px 70px 70px 36px; }
    .srow .hd { font-size: 11px; color: var(--text-3); text-transform: uppercase; }
    .srow input, .srow select { width: 100%; text-align: center; }
    .sug { font-size: 12px; color: var(--success); }
    @media (max-width: 520px) { .srow { grid-template-columns: 82px 56px 56px 64px 32px; } .srow.reps { grid-template-columns: 82px 56px 56px 32px; } }
  `];
  constructor() { super(); this.picking = false; this.open = ''; this.detail = null; }

  willUpdate(ch: Map<string, unknown>) {
    if (ch.has('ctx') && this.L) this.loaded();
  }
  protected async loaded() {
    if (!this.ctx?.params?.id) return;
    const r = await this.L.cached(`${API}/templates/${this.ctx.params.id}`);
    this.detail = r.data;
  }

  private get t(): any | null { return this.L.get('template', this.ctx.params.id); }
  private save(changes: any) {
    const t = this.t; if (!t) return;
    this.L.put('template', t.id, { ...t, ...changes, revision: (t.revision || 0) + 1 });
  }
  private item(id: string, changes: any) {
    const t = this.t!;
    this.save({ items: t.items.map((i: any) => (i.id === id ? { ...i, ...changes } : i)) });
  }
  private moveItem(id: string, dir: -1 | 1) {
    const items = [...this.t!.items]; const i = items.findIndex(x => x.id === id), j = i + dir;
    if (j < 0 || j >= items.length) return;
    [items[i], items[j]] = [items[j], items[i]];
    this.save({ items });
  }
  private setRow(it: any, si: number, changes: any) {
    this.item(it.id, { sets: it.sets.map((s: any, k: number) => (k === si ? { ...s, ...changes } : s)) });
  }
  private pick(ex: any) {
    const last = this.L.lastTime(ex.id);
    const w = last?.sets[0]?.weight_kg ?? null;
    const sets = Array.from({ length: 3 }, () => ({ type: 'normal', reps_min: 8, reps_max: 12, weight_kg: w, rpe: null, duration_s: null, distance_m: null }));
    const it = { id: uuid(), exercise_id: ex.id, superset: null, rest_seconds: null, notes: '', progression: 'double', priority: 2, sets };
    this.save({ items: [...(this.t!.items || []), it] });
    this.picking = false; this.open = it.id;
  }
  private async removeIt() {
    const t = this.t!;
    if (!(await this.host.confirm(tr('Delete the plan?'), tr("«{0}» will be deleted (the history stays).", t.name), { label: tr('Delete'), danger: true }))) return;
    this.L.remove('template', t.id);
    this.host.navigate('schede');
  }
  private async undo() {
    await this.L.sync();
    const r = await this.host.api('POST', `${API}/templates/${this.t!.id}/undo`);
    if (r.ok) { await this.L.sync(); this.loaded(); this.host.toast(tr('alt::Previous version restored'), 'success'); }
    else this.host.toast(r.error || tr('Nothing to undo'), 'warning');
  }

  render() {
    const nr = this.notReady(); if (nr) return nr;
    const t = this.t;
    if (!t) return html`<div class="page"><hxk-state kind="empty" text=${tr("Plan not found.")}></hxk-state></div>`;
    const exs = this.L.exercises();
    const est = estimate(t, this.L.settings.rest_default);
    const sugs = this.L.suggestions;
    return html`<div class="page">
      <div class="head"><hxk-button variant="ghost" size="sm" @click=${() => this.host.navigate('schede')}>${tr('‹ Plans')}</hxk-button></div>
      <div class="row wrap">
        <input class="in grow" style="font-size:20px;font-weight:600" .value=${t.name} @change=${(e: any) => this.save({ name: e.target.value || tr('Workout plan') })}>
        <button class="chip" aria-pressed=${!!t.favorite} title=${tr("Favourite: appears in Home for «Mark done»")} @click=${() => this.save({ favorite: !t.favorite })}><hxk-icon name="star" size=${14}></hxk-icon> ${tr("f::Favourite")}</button>
      </div>
      <div class="row wrap small muted">${plural((t.items || []).length, 'exercise', 'exercises')} · ${tr('about {0}', minutes(est))}
        ${t.changed_by === 'assistant' ? html`· ${tr('changed by the assistant')} <button class="link" @click=${() => this.undo()}>${tr("Undo change")}</button>` : nothing}</div>
      <div class="row wrap">
        <hxk-button variant="primary" icon="play" ?disabled=${!(t.items || []).length || !!this.L.activeSession()} @click=${() => this.startNow(t)}>${tr("alt::Start now")}</hxk-button>
        <hxk-button variant="ghost" icon="heart" @click=${() => this.host.assistant({ label: tr("Plan {0}", t.name), hints: { template_id: t.id }, prompt: tr("Let's review the plan {0}.", t.name), suggestions: [tr('It\'s too long'), tr('Add an exercise for the lats'), tr('It bores me, let\'s change something')] })}>${tr("Review with the assistant")}</hxk-button>
      </div>

      ${(t.items || []).map((it: any, idx: number) => {
        const ex = exs.get(it.exercise_id);
        const open = this.open === it.id;
        const sug = sugs[it.id] || this.detail?.items?.find((x: any) => x.id === it.id)?.suggestion;
        const time = usesTime(ex?.kind), weight = usesWeight(ex?.kind);
        return html`<div class="card item">
          <div class="ih">
            <div class="grow" @click=${() => (this.open = open ? '' : it.id)}>
              <div class="name truncate">${idx + 1}. ${ex?.name || '?'}</div>
              <div class="small muted truncate">${it.sets.filter((s: any) => s.type !== 'warmup').length} ${tr("sets ·")} ${plannedLabel(it.sets.find((s: any) => s.type !== 'warmup') || {}, ex?.kind)} · ${muscleText(ex)}</div>
              ${sug && sug.action !== 'plan' ? html`<div class="sug">${tr("Next time:")} ${sug.reason}</div>` : nothing}
            </div>
            <hxk-button size="sm" variant="ghost" ?disabled=${idx === 0} @click=${() => this.moveItem(it.id, -1)}>↑</hxk-button>
            <hxk-button size="sm" variant="ghost" ?disabled=${idx === t.items.length - 1} @click=${() => this.moveItem(it.id, 1)}>↓</hxk-button>
            <hxk-button size="sm" variant="ghost" icon=${open ? 'x' : 'edit'} @click=${() => (this.open = open ? '' : it.id)}></hxk-button>
          </div>
          ${open ? html`
            <div class="srow ${weight ? '' : 'reps'}"><span class="hd">${tr("Type")}</span><span class="hd">${time ? tr('Sec') : tr('Min reps')}</span><span class="hd">${time ? '' : tr('Max reps')}</span>${weight ? html`<span class="hd">kg</span>` : nothing}<span></span>
              ${it.sets.map((s: any, si: number) => html`
                <select class="in" .value=${s.type} @change=${(e: any) => this.setRow(it, si, { type: e.target.value })}>
                  ${Object.entries(SET_TYPE_LABEL).map(([k, v]) => html`<option value=${k} ?selected=${s.type === k}>${v}</option>`)}</select>
                ${time ? html`<input class="in" inputmode="numeric" .value=${String(s.duration_s ?? '')} @change=${(e: any) => this.setRow(it, si, { duration_s: parseNum(e.target.value) })}><span></span>`
                  : html`<input class="in" inputmode="numeric" .value=${String(s.reps_min ?? '')} @change=${(e: any) => this.setRow(it, si, { reps_min: parseNum(e.target.value) })}>
                  <input class="in" inputmode="numeric" .value=${String(s.reps_max ?? '')} @change=${(e: any) => this.setRow(it, si, { reps_max: parseNum(e.target.value) })}>`}
                ${weight ? html`<input class="in" inputmode="decimal" .value=${s.weight_kg == null ? '' : String(s.weight_kg).replace('.', ',')} @change=${(e: any) => this.setRow(it, si, { weight_kg: parseNum(e.target.value) })}>` : nothing}
                <hxk-button size="sm" variant="ghost" icon="x" @click=${() => this.item(it.id, { sets: it.sets.filter((_: any, k: number) => k !== si) })}></hxk-button>`)}
            </div>
            <div class="row wrap">
              <hxk-button size="sm" icon="plus" @click=${() => this.item(it.id, { sets: [...it.sets, { ...(it.sets[it.sets.length - 1] || { type: 'normal', reps_min: 8, reps_max: 12 }) }] })}>${tr("Streak")}</hxk-button>
              <label class="small row">${tr("Progression")}
                <select class="in" .value=${it.progression} @change=${(e: any) => this.item(it.id, { progression: e.target.value })}>
                  ${Object.entries(PROGRESSION).map(([k, v]) => html`<option value=${k} ?selected=${it.progression === k}>${v}</option>`)}</select></label>
              <label class="small row">${tr("alt::Rest")}
                <select class="in" .value=${String(it.rest_seconds ?? '')} @change=${(e: any) => this.item(it.id, { rest_seconds: parseNum(e.target.value) })}>
                  <option value="">${tr("default ({0})", dur(this.L.settings.rest_default))}</option>
                  ${[45, 60, 90, 120, 150, 180, 240, 300].map(v => html`<option value=${v} ?selected=${it.rest_seconds === v}>${dur(v)}</option>`)}</select></label>
              <label class="small row">${tr("Priority")}
                <select class="in" .value=${String(it.priority || 2)} @change=${(e: any) => this.item(it.id, { priority: Number(e.target.value) })}>
                  <option value="1">${tr("High (not cut)")}</option><option value="2">${tr("Normal")}</option><option value="3">${tr("Low (cut first)")}</option></select></label>
            </div>
            <input class="in" placeholder=${tr("Notes (e.g. narrow grip, seat 4)")} .value=${it.notes || ''} @change=${(e: any) => this.item(it.id, { notes: e.target.value })}>
            <div class="row">
              ${sug?.last ? html`<span class="small muted grow">${tr("Last time:")} ${(sug.last.sets || []).map((x: any) => `${kg(x.weight_kg)}×${x.reps}`).join(', ')}</span>` : html`<span class="grow"></span>`}
              <hxk-button size="sm" variant="danger" icon="trash" @click=${() => this.save({ items: t.items.filter((x: any) => x.id !== it.id) })}>${tr("Remove")}</hxk-button></div>` : nothing}
        </div>`;
      })}
      ${this.picking ? html`<hercules-picker .host=${this.host} .ctx=${this.ctx} @pick=${(e: CustomEvent) => this.pick(e.detail)} @close=${() => (this.picking = false)}></hercules-picker>`
        : html`<div><hxk-button icon="plus" @click=${() => (this.picking = true)}>${tr("Add exercise")}</hxk-button></div>`}
      <textarea class="in" rows="2" placeholder=${tr("Notes on the plan")} .value=${t.notes || ''} @change=${(e: any) => this.save({ notes: e.target.value })}></textarea>
      <div class="row"><span class="grow"></span><hxk-button variant="danger" icon="trash" @click=${() => this.removeIt()}>${tr("Delete plan")}</hxk-button></div>
    </div>`;
  }

  private startNow(t: any) {
    // the live page owns the session logic: open it with this template preselected
    this.host.navigate('allenamento', { scheda: t.id });
  }
}

/** Rough minutes: 40 s per set + rest between sets (same idea as the server's estimate). */
export function estimate(t: any, restDefault = 90): number {
  let s = 0;
  for (const it of t.items || []) {
    const n = (it.sets || []).length;
    s += n * 40 + Math.max(0, n - 1) * (it.rest_seconds || restDefault) + 60;
  }
  return Math.round(s / 60);
}
