/**
 * <hercules-today> — page "Allenamento": today's plan, check-in and adaptation (with the assistant), and the live
 * workout (sets, rest timer, warm-ups, plates). The live workout reads/writes only the local mirror, so it works
 * offline in the gym and syncs later (data.ts).
 */
import { HestiaElement, html, css, nothing } from '@hestia/webui-sdk';
import { API, Local, local, nowIso, uuid } from './data';
import {
  FEEDBACK_TAGS, PAIN_AREAS, SET_TYPES, SET_TYPE_LABEL, dur, e1rm, herculesStyles, kg, minutes, muscleText,
  parseNum, plannedLabel, plates, setLabel, today, usesTime, usesWeight, warmups,
} from './util';

/** Rest timer shared by the page and the live widget (module scope survives navigation). */
export const rest = { until: 0, total: 0, label: '', notified: false };

export class HerculesToday extends HestiaElement {
  static properties = {
    ...HestiaElement.properties,
    tick: { state: true }, next: { state: true }, picker: { state: true }, menu: { state: true }, finishing: { state: true },
    result: { state: true }, check: { state: true }, adapted: { state: true }, busy: { state: true }, platesFor: { state: true },
  };
  declare tick: number;
  declare next: any;
  declare picker: { mode: 'add' | 'replace'; block?: string; prefer?: string[] } | null;
  declare menu: string;
  declare finishing: { effort: number | null; notes: string; update: boolean } | null;
  declare result: any;
  declare check: { energy: number | null; time: number | null; pain: string[]; text: string };
  declare adapted: any;
  declare busy: string;
  declare platesFor: number | null;
  private L!: Local;
  private timer: any = null;
  private off: (() => void) | null = null;
  private drafts = new Map<string, { weight_kg?: number | null; reps?: number | null; rpe?: number | null; duration_s?: number | null }>();

  static styles = [...HestiaElement.styles, herculesStyles, css`
    .live-head { position: sticky; top: 0; z-index: 3; background: var(--bg); padding: 8px 0; display: flex; flex-direction: column; gap: 8px; }
    .restbar { display: flex; align-items: center; gap: 10px; background: var(--accent-soft); color: var(--accent); border-radius: var(--radius-md); padding: 8px 12px; }
    .restbar .t { font-size: 22px; font-weight: 650; font-variant-numeric: tabular-nums; min-width: 64px; }
    .restbar .bar { flex: 1; height: 6px; background: var(--surface); border-radius: 3px; overflow: hidden; }
    .restbar .bar i { display: block; height: 100%; background: var(--accent); }
    .restbar.over { background: var(--success-soft); color: var(--success); }
    .block { display: flex; flex-direction: column; gap: 8px; }
    .block.skipped { opacity: .55; }
    .bh { display: flex; align-items: flex-start; gap: 8px; }
    .bh .name { font-weight: 600; font-size: 15px; cursor: pointer; }
    .sets { display: grid; grid-template-columns: 30px 1fr 84px 70px 44px; gap: 6px 8px; align-items: center; }
    .sets.time { grid-template-columns: 30px 1fr 96px 44px; }
    .sets.reps { grid-template-columns: 30px 1fr 70px 44px; }
    .sets .hd { font-size: 11px; color: var(--text-3); text-transform: uppercase; letter-spacing: .04em; }
    .n { width: 26px; height: 26px; border-radius: 50%; display: grid; place-items: center; font-size: 12px; font-weight: 600; background: var(--surface-2); color: var(--text-2); }
    .n.w { background: var(--warning-soft); color: var(--warning); }
    .prev { font-size: 13px; color: var(--text-3); font-variant-numeric: tabular-nums; cursor: pointer; }
    .sets input { width: 100%; text-align: center; font-size: 16px; padding: 8px 4px; font-variant-numeric: tabular-nums; }
    .ok { width: 40px; height: 40px; border-radius: var(--radius-md); border: 1px solid var(--border-strong); background: var(--surface); cursor: pointer; display: grid; place-items: center; color: var(--text-3); }
    .ok[aria-pressed=true] { background: var(--success); border-color: var(--success); color: #fff; }
    .row-done input { background: var(--success-soft); border-color: transparent; }
    .menu { display: flex; flex-wrap: wrap; gap: 6px; padding: 6px 0; }
    .plan { display: flex; flex-direction: column; gap: 4px; }
    .plan .it { display: flex; gap: 8px; font-size: 13.5px; }
    .plan .it .x { color: var(--text-3); margin-left: auto; text-align: right; }
    .reason { font-size: 12px; color: var(--text-3); }
    .pr { display: flex; gap: 8px; align-items: center; }
    .big { font-size: 28px; font-weight: 650; }
    .foot { display: flex; gap: 8px; flex-wrap: wrap; position: sticky; bottom: 0; background: var(--bg); padding: 10px 0; }
    .warn { color: var(--warning); font-size: 13px; }
    .plates { display: flex; gap: 4px; align-items: center; flex-wrap: wrap; }
    .plate { border-radius: 4px; background: var(--surface-3); padding: 2px 6px; font-size: 12px; font-weight: 600; }
  `];

  constructor() {
    super();
    this.tick = 0; this.next = null; this.picker = null; this.menu = ''; this.finishing = null; this.result = null;
    this.check = { energy: null, time: null, pain: [], text: '' }; this.adapted = null; this.busy = ''; this.platesFor = null;
  }

  connectedCallback() {
    super.connectedCallback();
    this.L = local(this.host);
    this.off = this.L.onChange(() => this.requestUpdate());
    this.L.ready.then(() => {
      this.loadNext();
      const pre = this.ctx?.query?.scheda;          // "Inizia ora" from a template page
      if (pre && !this.L.activeSession()) { const t = this.L.get('template', pre); if (t) this.start(t); this.host.navigate('allenamento'); }
      this.requestUpdate();
    });
    this.onHost('refresh', () => { this.L.sync(); this.loadNext(); });
    this.onHost('online', () => this.loadNext());
    this.timer = setInterval(() => this.onTick(), 500);
  }
  disconnectedCallback() {
    super.disconnectedCallback();
    clearInterval(this.timer);
    this.off?.();
  }

  private onTick() {
    const act = this.L?.activeSession();
    if (!act && !rest.until) return;
    this.tick = Date.now();
    if (rest.until && !rest.notified && Date.now() >= rest.until) {
      rest.notified = true;
      try { navigator.vibrate?.([200, 100, 200]); } catch { /* not supported */ }
      if (document.hidden) this.host.notify('Recupero finito', rest.label || 'Prossima serie', { tag: 'hercules-rest' });
    }
  }

  private async loadNext() {
    const r = await this.L.cached(`${API}/next`);
    this.next = r.data;
  }

  // ── session actions (local first) ───────────────────────────────────────
  private planFor(t: any): any[] {
    return (t.items || []).map((it: any) => {
      const sug = this.L.suggestions[it.id];
      const planned = (sug?.sets || it.sets || []).map((p: any) => ({
        type: p.type || 'normal', reps_min: p.reps_min ?? null, reps_max: p.reps_max ?? null, weight_kg: p.weight_kg ?? null,
        rpe: p.rpe ?? null, duration_s: p.duration_s ?? null, distance_m: p.distance_m ?? null, reps_target: p.reps ?? p.reps_target ?? p.reps_max ?? null,
      }));
      return { id: uuid(), exercise_id: it.exercise_id, superset: it.superset ?? null, rest_seconds: it.rest_seconds ?? null,
               notes: it.notes || '', template_item_id: it.id, planned, skipped: false, replaced_from: null };
    });
  }

  private todayCheckin(): any {
    const t = today();
    const rows = this.L.list('checkin').filter(c => (c.at || '').length && new Date(c.at).toDateString() === new Date(t + 'T12:00:00').toDateString());
    rows.sort((a, b) => (a.at || '').localeCompare(b.at || ''));
    return rows.length ? rows[rows.length - 1] : null;
  }

  private start(t: any | null) {
    if (this.L.activeSession()) { this.host.toast('C\'è già un allenamento in corso', 'warning'); return; }
    const c = this.todayCheckin();
    this.L.put('session', uuid(), {
      name: t ? t.name : 'Allenamento libero', status: 'active', started_at: nowIso(), template_id: t?.id ?? null, program_id: null,
      exercises: t ? this.planFor(t) : [], readiness: c ? { energy: c.energy, sleep: c.sleep, pain_areas: c.pain_areas, time_minutes: c.time_minutes } : {},
      source: 'live', notes: '', adaptation_id: null,
    });
    this.result = null;
    window.scrollTo?.({ top: 0 });
  }

  private saveSession(sess: any, changes: any) {
    this.L.put('session', sess.id, { ...sess, ...changes });
  }

  private setAt(sess: any, block: any, i: number): any | null {
    return this.L.setsOf(sess.id).find(s => s.session_exercise_id === block.id && (s.position ?? 0) === i) || null;
  }

  private draftKey(block: any, i: number) { return `${block.id}:${i}`; }

  private value(sess: any, block: any, i: number, field: 'weight_kg' | 'reps' | 'rpe' | 'duration_s'): number | null {
    const d = this.drafts.get(this.draftKey(block, i));
    if (d && d[field] !== undefined) return d[field] as number | null;
    const s = this.setAt(sess, block, i);
    if (s) return s[field] ?? null;
    const p = (block.planned || [])[i] || {};
    if (field === 'reps') return p.reps_target ?? p.reps_max ?? p.reps_min ?? null;
    if (field === 'weight_kg') {
      if (p.weight_kg !== null && p.weight_kg !== undefined) return p.weight_kg;
      const prev = this.L.lastTime(block.exercise_id, sess.id);
      const work = prev?.sets.filter((x: any) => x.type !== 'warmup') || [];
      return work.length ? work[Math.min(i, work.length - 1)].weight_kg ?? null : null;
    }
    return p[field] ?? null;
  }

  private edit(sess: any, block: any, i: number, field: 'weight_kg' | 'reps' | 'rpe' | 'duration_s', raw: string) {
    const key = this.draftKey(block, i);
    const v = field === 'duration_s' ? parseDuration(raw) : parseNum(raw);
    this.drafts.set(key, { ...(this.drafts.get(key) || {}), [field]: v });
    const existing = this.setAt(sess, block, i);
    if (existing) this.L.put('set', existing.id, { ...existing, [field]: v });
  }

  private toggle(sess: any, block: any, i: number, ex: any) {
    const existing = this.setAt(sess, block, i);
    if (existing) { this.L.remove('set', existing.id); return; }
    const p = (block.planned || [])[i] || {};
    const body = {
      session_id: sess.id, session_exercise_id: block.id, exercise_id: block.exercise_id, session_at: sess.started_at,
      position: i, type: p.type || 'normal', weight_kg: usesWeight(ex?.kind) ? this.value(sess, block, i, 'weight_kg') : null,
      reps: usesTime(ex?.kind) ? null : this.value(sess, block, i, 'reps'), rpe: this.value(sess, block, i, 'rpe'),
      duration_s: usesTime(ex?.kind) ? this.value(sess, block, i, 'duration_s') : null, completed: true, completed_at: nowIso(), notes: '',
    };
    this.L.put('set', uuid(), body);
    this.drafts.delete(this.draftKey(block, i));
    const secs = Number(block.rest_seconds || this.L.settings.rest_default || 90);
    if (p.type !== 'warmup' || secs) {
      const s = p.type === 'warmup' ? Math.min(60, secs) : secs;
      Object.assign(rest, { until: Date.now() + s * 1000, total: s, label: ex?.name || '', notified: false });
    }
  }

  private addSet(sess: any, block: any) {
    const last = (block.planned || [])[block.planned.length - 1] || { type: 'normal', reps_min: 8, reps_max: 12 };
    this.updateBlock(sess, block.id, { planned: [...(block.planned || []), { ...last, type: last.type === 'warmup' ? 'normal' : last.type }] });
  }
  private removeLastSet(sess: any, block: any) {
    const n = (block.planned || []).length;
    if (!n) return;
    const s = this.setAt(sess, block, n - 1);
    if (s) this.L.remove('set', s.id);
    this.updateBlock(sess, block.id, { planned: block.planned.slice(0, -1) });
  }
  private addWarmups(sess: any, block: any, ex: any) {
    const work = (block.planned || []).find((p: any) => p.type !== 'warmup');
    const w = work?.weight_kg ?? this.value(sess, block, (block.planned || []).findIndex((p: any) => p.type !== 'warmup'), 'weight_kg');
    const inc = this.L.settings.increments[ex?.equipment] || 2.5;
    const ws = warmups(w, this.L.settings.warmup, inc, ex?.equipment === 'barbell' ? this.L.settings.bar_weight : 0);
    if (!ws.length) { this.host.toast('Serve un peso di lavoro per calcolare il riscaldamento', 'info'); return; }
    const kept = (block.planned || []).filter((p: any) => p.type !== 'warmup');
    // logged sets keep their position: shift them after the new warm-ups
    const sets = this.L.setsOf(sess.id).filter(s => s.session_exercise_id === block.id);
    const oldWarm = (block.planned || []).filter((p: any) => p.type === 'warmup').length;
    for (const s of sets) this.L.put('set', s.id, { ...s, position: (s.position ?? 0) - oldWarm + ws.length });
    this.updateBlock(sess, block.id, { planned: [...ws.map(x => ({ type: 'warmup', reps_min: x.reps, reps_max: x.reps, reps_target: x.reps, weight_kg: x.weight_kg })), ...kept] });
    this.menu = '';
  }
  private updateBlock(sess: any, blockId: string, changes: any) {
    const fresh = this.L.get('session', sess.id) || sess;
    this.saveSession(fresh, { exercises: (fresh.exercises || []).map((b: any) => (b.id === blockId ? { ...b, ...changes } : b)) });
  }
  private move(sess: any, blockId: string, dir: -1 | 1) {
    const list = [...(sess.exercises || [])];
    const i = list.findIndex(b => b.id === blockId), j = i + dir;
    if (i < 0 || j < 0 || j >= list.length) return;
    [list[i], list[j]] = [list[j], list[i]];
    this.saveSession(sess, { exercises: list });
  }
  private removeBlock(sess: any, block: any) {
    for (const s of this.L.setsOf(sess.id).filter(s => s.session_exercise_id === block.id)) this.L.remove('set', s.id);
    this.saveSession(sess, { exercises: (sess.exercises || []).filter((b: any) => b.id !== block.id) });
    this.menu = '';
  }

  private pick(ex: any) {
    const sess = this.L.activeSession();
    if (!sess || !this.picker) return;
    const prev = this.L.lastTime(ex.id);
    const work = prev?.sets.filter((s: any) => s.type !== 'warmup') || [];
    const w = work.length ? work[0].weight_kg : null;
    if (this.picker.mode === 'add') {
      const planned = Array.from({ length: Math.max(3, work.length || 3) }, (_, i) => ({
        type: 'normal', reps_min: 8, reps_max: 12, reps_target: work[i]?.reps ?? 10, weight_kg: work[i]?.weight_kg ?? w,
      }));
      this.saveSession(sess, { exercises: [...(sess.exercises || []), { id: uuid(), exercise_id: ex.id, superset: null, rest_seconds: null, notes: '', template_item_id: null, planned, skipped: false, replaced_from: null }] });
    } else {
      const blk = (sess.exercises || []).find((b: any) => b.id === this.picker!.block);
      if (blk) {
        for (const s of this.L.setsOf(sess.id).filter(s => s.session_exercise_id === blk.id)) this.L.remove('set', s.id);
        this.updateBlock(sess, blk.id, { exercise_id: ex.id, replaced_from: blk.exercise_id,
          planned: (blk.planned || []).map((p: any) => ({ ...p, weight_kg: p.type === 'warmup' ? null : w })) });
      }
    }
    this.picker = null; this.menu = '';
  }

  private async finish() {
    const sess = this.L.activeSession();
    if (!sess || !this.finishing) return;
    const f = this.finishing;
    this.busy = 'finish';
    const body = { perceived_effort: f.effort, notes: f.notes || null, update_template: f.update };
    let detail: any = null;
    if (this.host.online && await this.L.sync()) {
      const r = await this.host.api('POST', `${API}/sessions/${sess.id}/finish`, { body });
      if (r.ok) { detail = r.data; await this.L.sync(); }
    }
    if (!detail) {
      this.saveSession(sess, { status: 'done', ended_at: nowIso(), perceived_effort: f.effort, notes: f.notes });
      const work = this.L.setsOf(sess.id).filter(x => x.type !== 'warmup');
      detail = { ...sess, offline: true, prs: this.localPrs(sess), summary: {
        sets: work.length, volume: Math.round(work.reduce((v, x) => v + (x.weight_kg || 0) * (x.reps || 0), 0)),
        duration_min: Math.round((Date.now() - Date.parse(sess.started_at)) / 60000) } };
    }
    this.result = detail;
    this.finishing = null; this.busy = ''; rest.until = 0;
    this.loadNext();
  }

  /** PRs computed on the device when finishing offline (heaviest weight and best e1RM vs history). */
  private localPrs(sess: any): any[] {
    const out: any[] = [];
    const exs = this.L.exercises();
    const mine = this.L.setsOf(sess.id).filter(s => s.type !== 'warmup' && s.completed !== false);
    const others = this.L.list('set').filter(s => s.session_id !== sess.id && s.type !== 'warmup');
    const doneIds = new Set(this.L.doneSessions().map(s => s.id));
    for (const exId of new Set(mine.map(s => s.exercise_id))) {
      const hist = others.filter(s => s.exercise_id === exId && doneIds.has(s.session_id));
      if (!hist.length) continue;
      const best = (arr: any[], f: (s: any) => number | null) => Math.max(0, ...arr.map(s => f(s) || 0));
      const name = exs.get(exId)?.name || '?';
      const w = best(mine.filter(s => s.exercise_id === exId), s => s.weight_kg), wh = best(hist, s => s.weight_kg);
      if (w > wh) out.push({ exercise: name, label: 'Peso massimo', value: w });
      const e = best(mine.filter(s => s.exercise_id === exId), s => e1rm(s.weight_kg, s.reps)), eh = best(hist, s => e1rm(s.weight_kg, s.reps));
      if (e > eh) out.push({ exercise: name, label: '1RM stimato', value: Math.round(e * 10) / 10 });
    }
    return out;
  }

  private async discard() {
    const sess = this.L.activeSession();
    if (!sess) return;
    if (!(await this.host.confirm('Annullare l\'allenamento?', 'Le serie registrate verranno scartate.', { label: 'Scarta', danger: true }))) return;
    this.saveSession(sess, { status: 'discarded', ended_at: nowIso() });
    rest.until = 0;
  }

  private saveCheckin(): any {
    const c = this.check;
    return this.L.put('checkin', uuid(), { at: nowIso(), energy: c.energy, time_minutes: c.time, pain_areas: c.pain, free_text: c.text });
  }

  private async adapt(templateId: string | null) {
    if (!this.host.online) { this.host.toast('Per adattare serve la connessione: puoi comunque iniziare la scheda', 'warning'); return; }
    this.busy = 'adapt';
    this.saveCheckin();
    await this.L.sync();
    const c = this.check;
    const r = await this.host.api('POST', `${API}/adapt`, { body: { energy: c.energy, time_minutes: c.time, pain_areas: c.pain, free_text: c.text, template_id: templateId } });
    this.busy = '';
    if (r.ok) this.adapted = r.data; else this.host.toast(r.error || 'Adattamento non riuscito', 'danger');
  }

  private async applyAdapted() {
    if (!this.adapted) return;
    this.busy = 'apply';
    const r = await this.host.api('POST', `${API}/adapt/${this.adapted.adaptation_id}/apply`);
    this.busy = '';
    if (!r.ok) { this.host.toast(r.error || 'Non riuscito', 'danger'); return; }
    this.adapted = null;
    await this.L.sync();
  }

  private async restore() {
    const sess = this.L.activeSession();
    if (!sess?.original_plan) return;
    if (!this.host.online) { this.host.toast('Serve la connessione', 'warning'); return; }
    await this.L.sync();
    const r = await this.host.api('POST', `${API}/restore`, { body: { session_id: sess.id } });
    if (r.ok) await this.L.sync(); else this.host.toast(r.error || 'Non riuscito', 'danger');
  }

  private async quickDone(t: any) {
    if (!this.host.online) {
      // offline: a done session with the planned values, like the server's "Segna fatto"
      const plan = this.planFor(t);
      const end = new Date(), start = new Date(end.getTime() - 45 * 60000).toISOString();
      const sid = uuid();
      this.L.put('session', sid, { name: t.name, status: 'done', started_at: start, ended_at: end.toISOString(), template_id: t.id, source: 'quick', exercises: plan, readiness: {} });
      plan.forEach((b: any) => (b.planned || []).forEach((p: any, i: number) => this.L.put('set', uuid(), {
        session_id: sid, session_exercise_id: b.id, exercise_id: b.exercise_id, session_at: start, position: i, type: p.type,
        weight_kg: p.weight_kg, reps: p.reps_target ?? p.reps_max, completed: true, completed_at: start })));
      this.host.toast(`${t.name} segnato fatto`, 'success', { label: 'Annulla', run: () => {
        for (const s of this.L.setsOf(sid)) this.L.remove('set', s.id);
        this.L.remove('session', sid);
      } });
      return;
    }
    const r = await this.host.api('POST', `${API}/quick/${t.id}`, { body: {} });
    if (!r.ok) { this.host.toast(r.error || 'Non riuscito', 'danger'); return; }
    await this.L.sync();
    this.loadNext();
    this.host.toast(r.data.label || 'Fatto', 'success', { label: 'Annulla', run: async () => {
      await this.host.api('DELETE', `${API}/quick/${t.id}`); await this.L.sync(); this.loadNext();
    } });
  }

  private async skipToday() {
    const r = await this.host.api('POST', `${API}/days/skip`, { body: {} });
    if (!r.ok) { this.host.toast(r.error === 'offline' ? 'Serve la connessione' : (r.error || 'Non riuscito'), 'warning'); return; }
    await this.L.sync();
    this.loadNext();
    this.host.toast('Oggi saltato', 'info', { label: 'Annulla', run: async () => { await this.host.api('DELETE', `${API}/days/skip`); this.loadNext(); } });
  }

  private talk(extra?: Record<string, string | number>) {
    const act = this.L.activeSession();
    this.host.assistant({
      label: act ? `Allenamento in corso: ${act.name}` : 'Allenamento di oggi',
      hints: { session_id: act?.id || '', template_id: act?.template_id || this.next?.template?.id || '', ...(extra || {}) },
      prompt: act ? 'Sto facendo questo allenamento: aiutami ad adattarlo se serve.' : 'Parliamo dell\'allenamento di oggi.',
      suggestions: ['Oggi sono stanco', 'Ho male alla spalla', 'Ho solo 30 minuti', 'La panca è occupata', 'Voglio spingere di più'],
    });
  }

  // ── render ──────────────────────────────────────────────────────────────
  render() {
    const L = this.L;
    if (!L) return nothing;
    if (!L.loaded) {
      return html`<div class="page">${this.host.online
        ? html`<hxk-state kind="loading" text="Scarico schede ed esercizi…"></hxk-state>`
        : html`<hxk-state kind="offline" text="Apri Allenamento una volta online: poi funziona anche senza rete." @retry=${() => L.sync()}></hxk-state>`}</div>`;
    }
    const act = L.activeSession();
    return html`<div class="page">
      ${this.syncBadge()}
      ${this.result ? this.renderResult() : act ? this.renderLive(act) : this.renderPlan()}
    </div>`;
  }

  private syncBadge() {
    const L = this.L;
    if (this.host.online && !L.pending) return nothing;
    return html`<div class="offline"><hxk-icon name="offline" size="14"></hxk-icon>
      ${this.host.online ? `${L.pending} modifiche da sincronizzare…` : `Offline · ${L.pending ? L.pending + ' modifiche salvate sul dispositivo' : 'i dati restano sul dispositivo'}`}</div>`;
  }

  private renderPlan() {
    const L = this.L;
    const n = this.next;
    const t = n?.template ? (L.get('template', n.template.id) || n.template) : null;
    const others = L.templates().filter(x => x.id !== t?.id);
    const exs = L.exercises();
    const doneToday = (n?.done_today || []).length > 0 || L.doneSessions().some(s => s.started_at && new Date(s.started_at).toDateString() === new Date().toDateString());
    return html`
      <div class="head"><h1>Allenamento</h1><span class="sub">${new Date().toLocaleDateString('it-IT', { weekday: 'long', day: 'numeric', month: 'long' })}</span>
        <span class="grow"></span>
        <hxk-button variant="ghost" icon="heart" @click=${() => this.talk()}>Parla con l'assistente</hxk-button></div>

      ${t ? html`<hxk-card heading=${t.name} subtitle=${[n?.reason, n?.estimated_minutes ? `circa ${minutes(n.estimated_minutes)}` : ''].filter(Boolean).join(' · ')}>
        ${doneToday ? html`<div class="pill" style="margin-bottom:8px"><hxk-icon name="check" size="12"></hxk-icon> Già fatto oggi</div>` : nothing}
        <div class="plan">${(t.items || []).map((it: any) => {
          const ex = exs.get(it.exercise_id); const sug = L.suggestions[it.id];
          const sets = (sug?.sets || it.sets || []).filter((p: any) => p.type !== 'warmup');
          return html`<div class="it"><span class="truncate">${ex?.name || '?'}</span>
            <span class="x tnum">${sets.length} serie · ${plannedLabel(sets[0] || {}, ex?.kind)}${sug?.action === 'weight' ? html` <hxk-badge tone="success">+</hxk-badge>` : nothing}</span></div>
            ${sug?.reason && sug.action !== 'plan' ? html`<div class="reason">${sug.reason}</div>` : nothing}`;
        })}</div>
        <div class="row wrap" style="margin-top:12px">
          <hxk-button variant="primary" size="lg" icon="play" @click=${() => this.start(t)}>Inizia</hxk-button>
          <hxk-button icon="check" @click=${() => this.quickDone(t)}>Segna fatto</hxk-button>
          ${n?.rest_day ? nothing : html`<hxk-button variant="ghost" @click=${() => this.skipToday()}>Salta oggi</hxk-button>`}
        </div>
      </hxk-card>` : html`<hxk-card heading="Nessuna scheda">
        <div class="muted">Crea la tua prima scheda (es. Push, Pull, Gambe) o inizia un allenamento libero.</div>
        <div class="row wrap" style="margin-top:10px">
          <hxk-button variant="primary" icon="plus" @click=${() => this.host.navigate('schede')}>Crea una scheda</hxk-button>
          <hxk-button icon="play" @click=${() => this.start(null)}>Allenamento libero</hxk-button>
        </div></hxk-card>`}

      ${this.renderCheckin(t)}

      ${others.length ? html`<div class="card col"><h3>Altre schede</h3><div class="list">
        ${others.map(o => html`<div class="li" @click=${() => this.host.navigate('schede/' + o.id)}>
          <div class="grow"><div class="truncate">${o.favorite ? html`<span style="color:var(--warning)">★</span> ` : ''}${o.name}</div>
            <div class="small muted truncate">${(o.items || []).map((i: any) => exs.get(i.exercise_id)?.name).filter(Boolean).join(', ')}</div></div>
          <hxk-button size="sm" icon="play" @click=${(e: Event) => { e.stopPropagation(); this.start(o); }}>Inizia</hxk-button></div>`)}
        <div class="li" @click=${() => this.start(null)}><div class="grow muted">Allenamento libero</div><hxk-icon name="play"></hxk-icon></div>
      </div></div>` : nothing}`;
  }

  private renderCheckin(t: any) {
    const c = this.check;
    const set = (p: Partial<typeof c>) => (this.check = { ...c, ...p });
    const a = this.adapted;
    const exs = this.L.exercises();
    return html`<div class="card col">
      <div class="between"><h2>Come stai oggi?</h2><span class="small muted">facoltativo</span></div>
      <div class="col"><span class="small muted">Energia</span><div class="chips">
        ${[1, 2, 3, 4, 5].map(v => html`<button class="chip" aria-pressed=${c.energy === v} @click=${() => set({ energy: c.energy === v ? null : v })}>${['😩', '😕', '😐', '🙂', '💪'][v - 1]} ${v}</button>`)}</div></div>
      <div class="col"><span class="small muted">Tempo a disposizione</span><div class="chips">
        ${[20, 30, 45, 60, 90].map(v => html`<button class="chip" aria-pressed=${c.time === v} @click=${() => set({ time: c.time === v ? null : v })}>${v} min</button>`)}</div></div>
      <div class="col"><span class="small muted">Fastidi o dolori</span><div class="chips">
        ${PAIN_AREAS.map(p => html`<button class="chip warn" aria-pressed=${c.pain.includes(p)} @click=${() => set({ pain: c.pain.includes(p) ? c.pain.filter(x => x !== p) : [...c.pain, p] })}>${p}</button>`)}</div></div>
      <input class="in" placeholder="Altro? (es. dormito poco, panca occupata)" .value=${c.text} @input=${(e: any) => set({ text: e.target.value })}>
      <div class="row wrap">
        <hxk-button variant="primary" icon="refresh" ?loading=${this.busy === 'adapt'} ?disabled=${!t}
          @click=${() => this.adapt(t?.id || null)}>Adatta l'allenamento</hxk-button>
        <hxk-button variant="ghost" icon="check" @click=${() => { this.saveCheckin(); this.host.toast('Salvato', 'success'); }}>Salva e basta</hxk-button>
        <hxk-button variant="ghost" icon="heart" @click=${() => this.talk({ energy: c.energy ?? '', time_minutes: c.time ?? '', pain: c.pain.join(',') })}>Parlane</hxk-button>
      </div>
      ${a ? html`<div class="sep"></div>
        <div class="between"><h2>Piano adattato: ${a.name}</h2><span class="pill tnum">${minutes(a.minutes_before)} → ${minutes(a.minutes_after)}</span></div>
        <ul style="margin:0;padding-left:18px">${(a.trace || []).map((x: string) => html`<li class="small">${x}</li>`)}</ul>
        ${(a.warnings || []).map((w: string) => html`<div class="warn">⚠ ${w}</div>`)}
        <div class="plan">${(a.exercises || []).map((e: any) => html`<div class="it" style=${e.skipped ? 'text-decoration:line-through;opacity:.6' : ''}>
          <span class="truncate">${exs.get(e.exercise_id)?.name || '?'}</span>
          <span class="x tnum">${(e.planned || []).filter((p: any) => p.type !== 'warmup').length} serie · ${plannedLabel((e.planned || []).find((p: any) => p.type !== 'warmup') || {}, exs.get(e.exercise_id)?.kind)}</span></div>`)}</div>
        <div class="row wrap">
          <hxk-button variant="primary" icon="play" ?loading=${this.busy === 'apply'} @click=${() => this.applyAdapted()}>Inizia con questo piano</hxk-button>
          <hxk-button variant="ghost" @click=${() => (this.adapted = null)}>Lascia il piano normale</hxk-button>
        </div>` : nothing}
    </div>`;
  }

  private renderLive(sess: any) {
    const L = this.L;
    const exs = L.exercises();
    const sets = L.setsOf(sess.id);
    const total = (sess.exercises || []).reduce((n: number, b: any) => n + (b.skipped ? 0 : (b.planned || []).length), 0);
    const elapsed = (Date.now() - Date.parse(sess.started_at)) / 1000;
    const volume = sets.reduce((v, s) => v + (s.type !== 'warmup' && s.weight_kg && s.reps ? s.weight_kg * s.reps : 0), 0);
    return html`
      <div class="live-head">
        <div class="between"><div class="grow"><h1 class="truncate">${sess.name}</h1>
          <div class="small muted tnum">${dur(elapsed)} · ${sets.length}/${total} serie · ${kg(Math.round(volume))} kg</div></div>
          <hxk-button variant="ghost" icon="heart" @click=${() => this.talk()}>Assistente</hxk-button></div>
        ${this.renderRest()}
      </div>
      ${sess.adaptation_id ? html`<div class="row small muted">Piano adattato oggi.
        ${sess.original_plan ? html`<button class="link" @click=${() => this.restore()}>Torna al piano originale</button>` : nothing}</div>` : nothing}
      ${this.picker ? html`<hercules-picker .host=${this.host} .ctx=${this.ctx} .prefer=${this.picker.prefer || []}
          heading=${this.picker.mode === 'add' ? 'Aggiungi esercizio' : 'Sostituisci esercizio'}
          @pick=${(e: CustomEvent) => this.pick(e.detail)} @close=${() => (this.picker = null)}></hercules-picker>` : nothing}
      ${(sess.exercises || []).map((b: any, bi: number) => this.renderBlock(sess, b, exs.get(b.exercise_id), bi))}
      <hxk-button icon="plus" @click=${() => (this.picker = { mode: 'add' })}>Aggiungi esercizio</hxk-button>
      ${this.finishing ? this.renderFinish(sess) : html`<div class="foot">
        <hxk-button variant="primary" size="lg" icon="check" @click=${() => (this.finishing = { effort: null, notes: '', update: false })}>Termina allenamento</hxk-button>
        <hxk-button variant="danger" @click=${() => this.discard()}>Scarta</hxk-button></div>`}`;
  }

  private renderRest() {
    if (!rest.until) return nothing;
    const left = (rest.until - Date.now()) / 1000;
    const over = left <= 0;
    const pct = over ? 100 : Math.max(0, Math.min(100, 100 - (left / rest.total) * 100));
    return html`<div class="restbar ${over ? 'over' : ''}">
      <hxk-icon name="clock"></hxk-icon>
      <span class="t">${over ? '+' + dur(-left) : dur(left)}</span>
      <span class="bar"><i style="width:${pct}%"></i></span>
      <hxk-button size="sm" variant="ghost" @click=${() => { rest.until -= 15000; this.tick++; }}>−15</hxk-button>
      <hxk-button size="sm" variant="ghost" @click=${() => { rest.until += 15000; rest.total += 15; rest.notified = false; this.tick++; }}>+15</hxk-button>
      <hxk-button size="sm" variant="ghost" icon="x" @click=${() => { rest.until = 0; this.tick++; }}></hxk-button>
    </div>`;
  }

  private renderBlock(sess: any, b: any, ex: any, bi: number) {
    const L = this.L;
    const prev = L.lastTime(b.exercise_id, sess.id);
    const prevWork = prev?.sets || [];
    const kind = ex?.kind;
    const time = usesTime(kind), weight = usesWeight(kind);
    const cls = time ? 'sets time' : weight ? 'sets' : 'sets reps';
    const sug = b.template_item_id ? L.suggestions[b.template_item_id] : null;
    const menuOpen = this.menu === b.id;
    let workIdx = 0;
    return html`<div class="card block ${b.skipped ? 'skipped' : ''}">
      <div class="bh">
        <div class="grow">
          <div class="name truncate" @click=${() => this.host.navigate('esercizi/' + b.exercise_id)}>${ex?.name || 'Esercizio'}</div>
          <div class="small muted truncate">${muscleText(ex)}${prev ? ` · ultima volta ${prev.sets.map((s: any) => setLabel(s, kind)).slice(0, 4).join(', ')}` : ''}</div>
          ${sug?.reason && sug.action !== 'plan' ? html`<div class="reason">${sug.reason}</div>` : nothing}
        </div>
        <hxk-button size="sm" variant="ghost" icon="more" @click=${() => (this.menu = menuOpen ? '' : b.id)}></hxk-button>
      </div>
      ${menuOpen ? html`<div class="menu">
        ${weight ? html`<hxk-button size="sm" @click=${() => this.addWarmups(sess, b, ex)}>Riscaldamento</hxk-button>` : nothing}
        <hxk-button size="sm" @click=${() => (this.picker = { mode: 'replace', block: b.id, prefer: ex?.primary_muscles || [] })}>Sostituisci</hxk-button>
        <hxk-button size="sm" ?disabled=${bi === 0} @click=${() => this.move(sess, b.id, -1)}>Su</hxk-button>
        <hxk-button size="sm" ?disabled=${bi === (sess.exercises || []).length - 1} @click=${() => this.move(sess, b.id, 1)}>Giù</hxk-button>
        <hxk-button size="sm" @click=${() => this.updateBlock(sess, b.id, { rest_seconds: Math.max(30, Number(b.rest_seconds || L.settings.rest_default) - 30) })}>Recupero −30 s</hxk-button>
        <hxk-button size="sm" @click=${() => this.updateBlock(sess, b.id, { rest_seconds: Number(b.rest_seconds || L.settings.rest_default) + 30 })}>Recupero +30 s</hxk-button>
        <hxk-button size="sm" variant="danger" icon="trash" @click=${() => this.removeBlock(sess, b)}>Togli</hxk-button>
        <span class="small muted" style="align-self:center">Recupero ${dur(Number(b.rest_seconds || L.settings.rest_default))}</span>
      </div>` : nothing}
      <div class=${cls}>
        <span class="hd">#</span><span class="hd">Prima</span>
        ${time ? html`<span class="hd">Tempo</span>` : weight ? html`<span class="hd">kg</span><span class="hd">Rip</span>` : html`<span class="hd">Rip</span>`}
        <span></span>
        ${(b.planned || []).map((p: any, i: number) => {
          const s = this.setAt(sess, b, i);
          const isWarm = p.type === 'warmup';
          const pw = isWarm ? null : prevWork.filter((x: any) => x.type !== 'warmup')[workIdx];
          const label = isWarm ? 'R' : SET_TYPES[p.type] || String(++workIdx);
          const w = this.value(sess, b, i, 'weight_kg');
          return html`
            <span class="n ${isWarm ? 'w' : ''}" title=${SET_TYPE_LABEL[p.type] || ''}>${label}</span>
            <span class="prev truncate" title="Usa i valori dell'ultima volta" @click=${() => {
              if (!pw) return; if (weight) this.edit(sess, b, i, 'weight_kg', String(pw.weight_kg ?? '')); this.edit(sess, b, i, 'reps', String(pw.reps ?? '')); this.requestUpdate(); }}>
              ${pw ? setLabel(pw, kind) : plannedLabel(p, kind)}</span>
            ${time ? html`<input class="in ${s ? 'row-done' : ''}" inputmode="numeric" placeholder="m:ss" .value=${fmtDuration(this.value(sess, b, i, 'duration_s'))}
                @change=${(e: any) => this.edit(sess, b, i, 'duration_s', e.target.value)}>`
              : html`${weight ? html`<input class="in ${s ? 'row-done' : ''}" inputmode="decimal" .value=${w === null ? '' : String(w).replace('.', ',')}
                  @focus=${() => (this.platesFor = ex?.equipment === 'barbell' ? w : null)}
                  @change=${(e: any) => this.edit(sess, b, i, 'weight_kg', e.target.value)}>` : nothing}
                <input class="in ${s ? 'row-done' : ''}" inputmode="numeric" .value=${String(this.value(sess, b, i, 'reps') ?? '')}
                  @change=${(e: any) => this.edit(sess, b, i, 'reps', e.target.value)}>`}
            <button class="ok" aria-pressed=${!!s} aria-label="Serie fatta" @click=${() => this.toggle(sess, b, i, ex)}><hxk-icon name="check"></hxk-icon></button>`;
        })}
      </div>
      ${this.platesFor && ex?.equipment === 'barbell' ? this.renderPlates(this.platesFor) : nothing}
      <div class="row">
        <hxk-button size="sm" variant="ghost" icon="plus" @click=${() => this.addSet(sess, b)}>Serie</hxk-button>
        ${(b.planned || []).length ? html`<hxk-button size="sm" variant="ghost" @click=${() => this.removeLastSet(sess, b)}>− Serie</hxk-button>` : nothing}
        <span class="grow"></span>
        ${b.replaced_from ? html`<span class="small muted">sostituito</span>` : nothing}
      </div>
    </div>`;
  }

  private renderPlates(w: number) {
    const s = this.L.settings;
    const p = plates(w, s.bar_weight, s.plates);
    if (!p.perSide.length) return nothing;
    return html`<div class="plates small"><span class="muted">Per lato (${kg(s.bar_weight)} kg bilanciere):</span>
      ${p.perSide.map(x => html`<span class="plate">${kg(x)}</span>`)}${p.rest ? html`<span class="muted">+${kg(p.rest)} non caricabili</span>` : nothing}</div>`;
  }

  private renderFinish(sess: any) {
    const f = this.finishing!;
    const set = (p: any) => (this.finishing = { ...f, ...p });
    const logged = this.L.setsOf(sess.id).length;
    return html`<div class="card col">
      <h2>Termina allenamento</h2>
      ${logged ? nothing : html`<div class="warn">Nessuna serie registrata.</div>`}
      <div class="col"><span class="small muted">Quanto è stato duro? (1–10)</span><div class="chips">
        ${[5, 6, 7, 8, 9, 10].map(v => html`<button class="chip" aria-pressed=${f.effort === v} @click=${() => set({ effort: f.effort === v ? null : v })}>${v}</button>`)}</div></div>
      <textarea class="in" rows="2" placeholder="Note (facoltative)" .value=${f.notes} @input=${(e: any) => set({ notes: e.target.value })}></textarea>
      ${sess.template_id ? html`<label class="row small"><input type="checkbox" .checked=${f.update} @change=${(e: any) => set({ update: e.target.checked })}>
        Aggiorna la scheda con i pesi di oggi</label>` : nothing}
      <div class="row wrap">
        <hxk-button variant="primary" icon="check" ?loading=${this.busy === 'finish'} @click=${() => this.finish()}>Salva</hxk-button>
        <hxk-button variant="ghost" @click=${() => (this.finishing = null)}>Continua ad allenarti</hxk-button>
      </div></div>`;
  }

  private renderResult() {
    const r = this.result;
    const sm = r.summary || {};
    const prs = (r.prs || []).filter((p: any) => !p.first);
    return html`<div class="card col">
      <div class="between"><h1>Fatto! 💪</h1>${r.offline ? html`<span class="offline">salvato sul dispositivo</span>` : nothing}</div>
      <div class="row wrap" style="gap:18px">
        ${sm.duration_min !== undefined ? html`<div><div class="big tnum">${minutes(sm.duration_min)}</div><div class="small muted">durata</div></div>` : nothing}
        ${sm.sets !== undefined ? html`<div><div class="big tnum">${sm.sets}</div><div class="small muted">serie</div></div>` : nothing}
        ${sm.volume !== undefined ? html`<div><div class="big tnum">${kg(sm.volume)}</div><div class="small muted">kg sollevati</div></div>` : nothing}
      </div>
      ${prs.length ? html`<h3>Record 🏆</h3>${prs.map((p: any) => html`<div class="pr"><hxk-badge tone="success">PR</hxk-badge>
        <span class="grow">${p.exercise}: ${p.label}</span><span class="tnum">${typeof p.value === 'number' ? kg(p.value) : p.value}${p.unit ? ' ' + p.unit : ''}</span></div>`)}` : nothing}
      <h3>Com'è andata?</h3>
      <div class="chips">${Object.entries(FEEDBACK_TAGS).map(([k, v]) => html`<button class="chip" @click=${() => this.feedback(r.id, k)}>${v}</button>`)}</div>
      <div class="row wrap">
        <hxk-button variant="primary" @click=${() => this.host.navigate('storico/' + r.id)}>Vedi dettaglio</hxk-button>
        <hxk-button variant="ghost" icon="heart" @click=${() => this.talk({ session_id: r.id })}>Commentalo con l'assistente</hxk-button>
        <hxk-button variant="ghost" @click=${() => (this.result = null)}>Chiudi</hxk-button>
      </div></div>`;
  }

  private feedback(sessionId: string, tag: string) {
    this.L.put('feedback', uuid(), { session_id: sessionId, tags: [tag], at: nowIso(), text: '' });
    this.host.toast(`Annotato: ${FEEDBACK_TAGS[tag]}. Ne terrà conto il coach.`, 'success');
  }
}

function parseDuration(raw: string): number | null {
  if (!raw) return null;
  const parts = raw.split(':').map(x => parseNum(x));
  if (parts.some(p => p === null)) return null;
  return parts.length === 1 ? parts[0]! : parts.reduce((t, p) => t! * 60 + p!, 0)!;
}
function fmtDuration(s: number | null): string { return s ? dur(s) : ''; }
