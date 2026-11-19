/**
 * <hercules-exercises> — catalog: search, filter by group/equipment, create a custom exercise (works offline).
 * <hercules-exercise>  — one exercise: records, e1RM trend, history, alternatives, notes.
 */
import { HestiaElement, html, css, nothing, tr } from '@hestia/webui-sdk';
import { API, uuid } from './data';
import { LocalPage } from './templates';
import { EQUIPMENT, GROUPS, GROUP_LABEL, KINDS, MUSCLES, dayLabel, herculesStyles, kg, muscleText, num, parseNum, relDays, search, setLabel, usesWeight } from './util';

const PATTERNS: Record<string, string> = {
  squat: tr('Squat'), hinge: tr('Hip hinge'), push_h: tr('Horizontal push'), push_v: tr('Vertical push'), pull_h: tr('Horizontal pull'),
  pull_v: tr('Vertical pull'), lunge: tr('Lunge'), carry: tr('Transport'), core: tr('Core'), isolation: tr('Isolation'),
};

export class HerculesExercises extends LocalPage {
  static properties = { ...HestiaElement.properties, q: { state: true }, group: { state: true }, equip: { state: true }, creating: { state: true }, mine: { state: true } };
  declare q: string; declare group: string; declare equip: string; declare creating: any; declare mine: boolean;
  static styles = [...HestiaElement.styles, herculesStyles, css`
    .form { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 10px; }
  `];
  constructor() { super(); this.q = ''; this.group = ''; this.equip = ''; this.creating = null; this.mine = false; }

  private usage(): Map<string, { times: number; last: string }> {
    const doneIds = new Set(this.L.doneSessions().map(s => s.id));
    const u = new Map<string, { times: number; last: string; sessions: Set<string> }>();
    for (const s of this.L.list('set')) {
      if (!doneIds.has(s.session_id)) continue;
      const e = u.get(s.exercise_id) || { times: 0, last: '', sessions: new Set<string>() };
      if (!e.sessions.has(s.session_id)) { e.sessions.add(s.session_id); e.times++; }
      if ((s.session_at || '') > e.last) e.last = s.session_at || '';
      u.set(s.exercise_id, e);
    }
    return u as any;
  }

  private create() {
    const c = this.creating;
    if (!c.name?.trim()) { this.host.toast(tr('Name the exercise'), 'warning'); return; }
    const e = this.L.put('exercise', uuid(), {
      name: c.name.trim(), aliases: [], primary_muscles: c.muscle ? [c.muscle] : [], secondary_muscles: [], equipment: c.equipment,
      kind: c.kind, movement_pattern: c.pattern, stress_joints: [], unilateral: false, is_custom: true, archived: false, notes: '', instructions: '',
    });
    this.creating = null;
    this.host.navigate('exercises/' + e.id);
  }

  render() {
    const nr = this.notReady(); if (nr) return nr;
    const usage = this.usage();
    let items = this.L.list('exercise').filter(e => !e.archived).map(e => ({ ...e, times: usage.get(e.id)?.times || 0, last: usage.get(e.id)?.last || '' }));
    if (this.group) items = items.filter(e => (e.primary_muscles || []).some((m: string) => GROUPS[this.group].includes(m)));
    if (this.equip) items = items.filter(e => e.equipment === this.equip);
    if (this.mine) items = items.filter(e => e.times > 0 || e.is_custom);
    items = this.q ? search(items, this.q) : items.sort((a, b) => b.times - a.times || a.name.localeCompare(b.name));
    const c = this.creating;
    return html`<div class="page">
      <div class="head"><h1>${tr("Exercises")}</h1><span class="sub">${items.length}</span><span class="grow"></span>
        <hxk-button variant="primary" icon="plus" @click=${() => (this.creating = { name: this.q, equipment: 'barbell', kind: 'weight_reps', pattern: 'isolation', muscle: '' })}>${tr("New")}</hxk-button></div>
      ${c ? html`<div class="card col"><h2>${tr("New exercise")}</h2><div class="form">
          <input class="in" placeholder=${tr("Name")} .value=${c.name} @input=${(e: any) => (this.creating = { ...c, name: e.target.value })}>
          <select class="in" .value=${c.equipment} @change=${(e: any) => (this.creating = { ...c, equipment: e.target.value })}>${Object.entries(EQUIPMENT).map(([k, v]) => html`<option value=${k} ?selected=${c.equipment === k}>${v}</option>`)}</select>
          <select class="in" .value=${c.kind} @change=${(e: any) => (this.creating = { ...c, kind: e.target.value })}>${Object.entries(KINDS).map(([k, v]) => html`<option value=${k} ?selected=${c.kind === k}>${v}</option>`)}</select>
          <select class="in" .value=${c.muscle} @change=${(e: any) => (this.creating = { ...c, muscle: e.target.value })}><option value="">${tr("Main muscle…")}</option>${Object.entries(MUSCLES).map(([k, v]) => html`<option value=${k}>${v}</option>`)}</select>
          <select class="in" .value=${c.pattern} @change=${(e: any) => (this.creating = { ...c, pattern: e.target.value })}>${Object.entries(PATTERNS).map(([k, v]) => html`<option value=${k} ?selected=${c.pattern === k}>${v}</option>`)}</select>
        </div><div class="row"><hxk-button variant="primary" @click=${() => this.create()}>${tr("Create")}</hxk-button><hxk-button variant="ghost" @click=${() => (this.creating = null)}>${tr("Cancel")}</hxk-button></div></div>` : nothing}
      <input class="in" placeholder=${tr("Search by name, alias or muscle…")} .value=${this.q} @input=${(e: any) => (this.q = e.target.value)}>
      <div class="chips">
        <button class="chip" aria-pressed=${this.mine} @click=${() => (this.mine = !this.mine)}>${tr("Mine")}</button>
        ${Object.keys(GROUPS).map(g => html`<button class="chip" aria-pressed=${this.group === g} @click=${() => (this.group = this.group === g ? '' : g)}>${GROUP_LABEL[g]}</button>`)}
        <select class="in" .value=${this.equip} @change=${(e: any) => (this.equip = e.target.value)}><option value="">${tr("Any equipment")}</option>${Object.entries(EQUIPMENT).map(([k, v]) => html`<option value=${k}>${v}</option>`)}</select>
      </div>
      <div class="card list">${items.slice(0, 200).map(e => html`<div class="li" @click=${() => this.host.navigate('exercises/' + e.id)}>
          <div class="grow"><div class="truncate">${e.favorite ? html`<hxk-icon name="star" size=${13} tone="warning"></hxk-icon> ` : ''}${e.name}${e.is_custom ? html` <span class="pill">${tr("yours")}</span>` : nothing}</div>
            <div class="small muted truncate">${muscleText(e)} · ${EQUIPMENT[e.equipment] || e.equipment}</div></div>
          <div class="small muted" style="text-align:right">${e.times ? html`${e.times}×<br>${relDays(e.last)}` : ''}</div></div>`)}
        ${items.length ? nothing : html`<div class="empty" style="padding:12px">${tr("No results. «New» to create it.")}</div>`}
      </div>
    </div>`;
  }
}

export class HerculesExercise extends LocalPage {
  static properties = { ...HestiaElement.properties, detail: { state: true }, metric: { state: true }, editing: { state: true } };
  declare detail: any; declare metric: string; declare editing: boolean;
  static styles = [...HestiaElement.styles, herculesStyles, css`
    .hist .li { cursor: pointer; align-items: flex-start; }
  `];
  constructor() { super(); this.detail = undefined; this.metric = 'best_e1rm'; this.editing = false; }
  willUpdate(ch: Map<string, unknown>) { if (ch.has('ctx') && this.L) this.loaded(); }
  protected async loaded() {
    if (!this.ctx?.params?.id) return;
    const r = await this.L.cached(`${API}/exercises/${this.ctx.params.id}`);
    this.detail = r.data;
  }
  private save(changes: any) {
    const e = this.L.get('exercise', this.ctx.params.id);
    if (e) this.L.put('exercise', e.id, { ...e, ...changes });
  }

  render() {
    const nr = this.notReady(); if (nr) return nr;
    const e = this.L.get('exercise', this.ctx.params.id) || this.detail?.exercise;
    if (!e) return html`<div class="page"><hxk-state kind="empty" text=${tr("Exercise not found.")}></hxk-state></div>`;
    const d = this.detail;
    const rec = d?.records || {};
    const hist = (d?.history || []) as any[];
    const weight = usesWeight(e.kind);
    const stats = [
      weight && rec.best_e1rm ? { label: tr('estimated 1RM'), value: kg(rec.best_e1rm.value), unit: 'kg', hint: tr("{0} × {1} · {2}", kg(rec.best_e1rm.weight), rec.best_e1rm.reps, dayLabel(rec.best_e1rm.date, false)) } : null,
      weight && rec.heaviest ? { label: tr('Maximum weight'), value: kg(rec.heaviest.value), unit: 'kg', hint: tr("× {0} · {1}", rec.heaviest.reps, dayLabel(rec.heaviest.date, false)) } : null,
      rec.most_reps ? { label: tr('alt::Max reps'), value: rec.most_reps.value, hint: rec.most_reps.weight ? tr("with {0} kg", kg(rec.most_reps.weight)) : '' } : null,
      weight && rec.best_session_volume ? { label: tr('Session volume'), value: num(rec.best_session_volume.value), unit: 'kg' } : null,
      { label: tr('Sessions'), value: hist.length },
    ].filter(Boolean) as any[];
    const metrics: Record<string, string> = weight ? { best_e1rm: tr('estimated 1RM'), top_weight: tr('Maximum weight'), volume: tr('Volume'), max_reps: tr('alt::Reps') } : { max_reps: tr('alt::Reps'), reps: tr('Total reps') };
    const metric = metrics[this.metric] ? this.metric : Object.keys(metrics)[0];
    const pts = hist.filter(h => h[metric] !== null && h[metric] !== undefined);
    return html`<div class="page">
      <div class="head"><hxk-button variant="ghost" size="sm" @click=${() => this.host.navigate('exercises')}>${tr('‹ Exercises')}</hxk-button></div>
      <div class="between"><div><h1>${e.name}</h1><div class="small muted">${muscleText(e)}${(e.secondary_muscles || []).length ? tr(' · also ') + e.secondary_muscles.map((m: string) => MUSCLES[m] || m).join(', ') : ''} · ${EQUIPMENT[e.equipment] || e.equipment}</div></div>
        <button class="chip" aria-pressed=${!!e.favorite} title=${tr("Favourite")} @click=${() => this.save({ favorite: !e.favorite })}><hxk-icon name="star" size=${14}></hxk-icon></button></div>
      ${d === undefined ? html`<hxk-state kind="loading"></hxk-state>` : d === null ? html`<div class="offline">${tr("Statistics available when you are online.")}</div>` : nothing}
      ${d?.stall ? html`<div class="card" style="border-color:var(--warning)"><b>${tr("Plateau")}</b> ${tr("· no progress in the last")} ${d.stall.exposures} ${tr("sessions.")}
        <button class="link" @click=${() => this.host.assistant({ label: tr("Plateau on {0}", e.name), hints: { exercise_id: e.id }, prompt: tr("I'm stuck on {0}: what do I change?", e.name) })}>${tr("Ask the coach")}</button></div>` : nothing}
      ${stats.length > 1 ? html`<hxk-stat .items=${stats}></hxk-stat>` : nothing}
      ${pts.length > 1 ? html`<div class="card col"><div class="tabs">${Object.entries(metrics).map(([k, v]) => html`<button class="tab" aria-pressed=${metric === k} @click=${() => (this.metric = k)}>${v}</button>`)}</div>
        <hxk-chart type="line" .labels=${pts.map(h => dayLabel(h.date, false))} .series=${[{ name: metrics[metric], values: pts.map(h => Number(h[metric])) }]} unit=${metric === 'max_reps' || metric === 'reps' ? '' : 'kg'} height="200"></hxk-chart></div>` : nothing}
      ${weight && rec.rep_max && Object.keys(rec.rep_max).length ? html`<div class="card col"><h3>${tr("Best weight per reps")}</h3><div class="row wrap" style="gap:16px">
        ${Object.entries(rec.rep_max).map(([r, v]: [string, any]) => html`<div><div class="small muted">${r}+ ${tr("abbr::reps")}</div><div class="tnum"><b>${kg(v.value)}</b> kg</div></div>`)}</div></div>` : nothing}
      ${hist.length ? html`<div class="card col hist"><h3>${tr("History")}</h3><div class="list">${[...hist].reverse().slice(0, 30).map(h => html`<div class="li" @click=${() => this.host.navigate('history/' + h.session_id)}>
          <div style="min-width:76px" class="small muted">${dayLabel(h.date)}</div>
          <div class="grow small tnum">${(h.detail || []).map((s: any) => setLabel(s, e.kind)).join(' · ')}</div>
          ${weight && h.best_e1rm ? html`<div class="small muted tnum">${kg(h.best_e1rm)}</div>` : nothing}</div>`)}</div></div>` : nothing}
      ${d?.alternatives?.length ? html`<div class="card col"><h3>${tr("Alternatives")}</h3><div class="chips">${d.alternatives.map((a: any) => html`<button class="chip" @click=${() => this.host.navigate('exercises/' + a.id)}>${a.name}</button>`)}</div></div>` : nothing}
      <div class="card col"><h3>${tr("Notes and settings")}</h3>
        <textarea class="in" rows="2" placeholder=${tr("Notes (adjustments, grip, feelings)")} .value=${e.notes || ''} @change=${(ev: any) => this.save({ notes: ev.target.value })}></textarea>
        <div class="row wrap"><label class="small row">${tr("Increment kg")} <input class="in num" inputmode="decimal" placeholder=${String(d?.increment ?? '')} .value=${e.increment_kg == null ? '' : String(e.increment_kg)} @change=${(ev: any) => this.save({ increment_kg: parseNum(ev.target.value) })}></label>
          ${e.is_custom ? html`<label class="small row">${tr("Name")} <input class="in" .value=${e.name} @change=${(ev: any) => this.save({ name: ev.target.value || e.name })}></label>` : nothing}
          <span class="grow"></span>
          <hxk-button size="sm" variant="ghost" @click=${() => { this.save({ archived: !e.archived }); if (!e.archived) this.host.navigate('exercises'); }}>${e.archived ? tr('f::Restore') : tr('f::Archive')}</hxk-button></div>
      </div>
    </div>`;
  }
}
