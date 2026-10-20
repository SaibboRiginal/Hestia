/**
 * <hercules-history> — "Storico": every workout by month (from the local mirror, works offline).
 * <hercules-session> — one workout: sets by exercise (editable), records, feedback, repeat, delete.
 */
import { HestiaElement, html, css, nothing } from '@hestia/webui-sdk';
import { API, nowIso, uuid } from './data';
import { LocalPage } from './templates';
import { FEEDBACK_TAGS, SET_TYPE_LABEL, dayLabel, herculesStyles, kg, minutes, num, parseNum, setLabel, timeLabel, usesWeight } from './util';

function summary(L: any, s: any) {
  const sets = L.setsOf(s.id).filter((x: any) => x.type !== 'warmup' && x.completed !== false);
  const vol = sets.reduce((v: number, x: any) => v + (x.weight_kg && x.reps ? x.weight_kg * x.reps : 0), 0);
  const mins = s.ended_at ? Math.round((Date.parse(s.ended_at) - Date.parse(s.started_at)) / 60000) : null;
  return { sets: sets.length, volume: Math.round(vol), minutes: mins, exercises: new Set(sets.map((x: any) => x.exercise_id)).size };
}

export class HerculesHistory extends LocalPage {
  static properties = { ...HestiaElement.properties, tpl: { state: true }, limit: { state: true }, importing: { state: true } };
  declare tpl: string; declare limit: number; declare importing: any;
  static styles = [...HestiaElement.styles, herculesStyles, css`
    .month { font-size: 12px; text-transform: uppercase; letter-spacing: .05em; color: var(--text-3); margin: 8px 0 2px; }
    .li { align-items: flex-start; }
    .d { min-width: 70px; } .d b { display: block; font-size: 15px; }
  `];
  constructor() { super(); this.tpl = ''; this.limit = 60; this.importing = null; }

  private async preview(file: File) {
    const text = await file.text();
    const r = await this.host.api('POST', `${API}/import/preview`, { body: { text } });
    if (!r.ok) { this.host.toast(r.error === 'offline' ? 'Serve la connessione' : (r.error || 'File non riconosciuto'), 'warning'); return; }
    this.importing = { text, preview: r.data, mapping: Object.fromEntries((r.data.mapping || []).map((m: any) => [m.name, m.exercise_id || ''])) };
  }
  private async commit() {
    const r = await this.host.api('POST', `${API}/import/commit`, { body: { text: this.importing.text, mapping: this.importing.mapping } });
    if (!r.ok) { this.host.toast(r.error || 'Import non riuscito', 'danger'); return; }
    this.importing = null;
    await this.L.reset();
    this.host.toast(`Importati ${r.data.sessions ?? ''} allenamenti`, 'success');
  }
  private async download(fmt: string) {
    const r = await this.host.api('GET', `${API}/export`, { query: { format: fmt } });
    if (!r.ok) { this.host.toast('Serve la connessione', 'warning'); return; }
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([r.data.text], { type: r.data.mime }));
    a.download = r.data.filename; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  }

  render() {
    const nr = this.notReady(); if (nr) return nr;
    const L = this.L;
    let sessions = L.doneSessions().reverse();
    if (this.tpl) sessions = sessions.filter(s => s.template_id === this.tpl);
    const tpls = L.templates();
    let month = '';
    const im = this.importing;
    return html`<div class="page">
      <div class="head"><h1>Storico</h1><span class="sub">${sessions.length} allenamenti</span><span class="grow"></span>
        <select class="in" .value=${this.tpl} @change=${(e: any) => (this.tpl = e.target.value)}><option value="">Tutte le schede</option>${tpls.map(t => html`<option value=${t.id}>${t.name}</option>`)}</select></div>
      ${sessions.length ? html`<div class="card list">${sessions.slice(0, this.limit).map(s => {
          const d = new Date(s.started_at);
          const m = d.toLocaleDateString('it-IT', { month: 'long', year: 'numeric' });
          const head = m !== month ? (month = m, html`<div class="month">${m}</div>`) : nothing;
          const sm = summary(L, s);
          return html`${head}<div class="li" @click=${() => this.host.navigate('storico/' + s.id)}>
            <div class="d small muted"><b>${d.getDate()}</b>${d.toLocaleDateString('it-IT', { weekday: 'short' })}</div>
            <div class="grow"><div class="truncate">${s.name}${s.source === 'quick' ? html` <span class="pill">segnato</span>` : s.source === 'import' ? html` <span class="pill">importato</span>` : nothing}</div>
              <div class="small muted">${sm.exercises} esercizi · ${sm.sets} serie${sm.volume ? ` · ${num(sm.volume)} kg` : ''}${sm.minutes ? ` · ${minutes(sm.minutes)}` : ''}</div></div>
            ${s.perceived_effort ? html`<span class="pill">RPE ${s.perceived_effort}</span>` : nothing}</div>`;
        })}
        ${sessions.length > this.limit ? html`<div class="li" @click=${() => (this.limit += 60)}><span class="link">Mostra altri</span></div>` : nothing}
      </div>` : html`<hxk-state kind="empty" text="Ancora nessun allenamento. Inizia da Allenamento o importa da Strong/Hevy."></hxk-state>`}
      <div class="card col"><h3>Importa ed esporta</h3>
        <div class="small muted">Importa lo storico da Strong o Hevy (CSV esportato dall'app). Reimportare lo stesso file non crea doppioni.</div>
        <div class="row wrap">
          <label class="chip">Scegli file CSV<input type="file" accept=".csv,text/csv" hidden @change=${(e: any) => e.target.files?.[0] && this.preview(e.target.files[0])}></label>
          <hxk-button size="sm" variant="ghost" @click=${() => this.download('csv')}>Esporta CSV</hxk-button>
          <hxk-button size="sm" variant="ghost" @click=${() => this.download('json')}>Esporta JSON</hxk-button>
        </div>
        ${im ? html`<div class="col">
          <div><b>${im.preview.format === 'hevy' ? 'Hevy' : 'Strong'}</b>: ${im.preview.workouts} allenamenti, ${im.preview.sets} serie
            ${im.preview.from ? ` dal ${dayLabel(im.preview.from, false)} al ${dayLabel(im.preview.to, false)}` : ''}</div>
          ${(im.preview.unknown || []).length ? html`<div class="small muted">Controlla l'abbinamento degli esercizi (quelli senza abbinamento diventano esercizi tuoi):</div>` : nothing}
          ${(im.preview.mapping || []).map((m: any) => html`<div class="row"><span class="grow truncate">${m.name} <span class="small muted">(${m.sets} serie)</span></span>
            <select class="in" @change=${(e: any) => (this.importing = { ...im, mapping: { ...im.mapping, [m.name]: e.target.value } })}>
              <option value="">Crea «${m.name}»</option>${L.list('exercise').sort((a: any, b: any) => a.name.localeCompare(b.name)).map((x: any) => html`<option value=${x.id} ?selected=${im.mapping[m.name] === x.id}>${x.name}</option>`)}</select></div>`)}
          <div class="row"><hxk-button variant="primary" @click=${() => this.commit()}>Importa</hxk-button><hxk-button variant="ghost" @click=${() => (this.importing = null)}>Annulla</hxk-button></div>
        </div>` : nothing}
      </div>
    </div>`;
  }
}

export class HerculesSession extends LocalPage {
  static properties = { ...HestiaElement.properties, detail: { state: true }, editing: { state: true } };
  declare detail: any; declare editing: boolean;
  static styles = [...HestiaElement.styles, herculesStyles, css`
    .sets { display: grid; grid-template-columns: 26px 1fr auto; gap: 4px 10px; align-items: center; font-variant-numeric: tabular-nums; }
    .sets.edit { grid-template-columns: 26px 80px 64px 64px 32px; }
    .sets input { width: 100%; text-align: center; }
    .n { font-size: 12px; color: var(--text-3); }
  `];
  constructor() { super(); this.detail = null; this.editing = false; }
  willUpdate(ch: Map<string, unknown>) { if (ch.has('ctx') && this.L) this.loaded(); }
  protected async loaded() {
    if (!this.ctx?.params?.id) return;
    const r = await this.L.cached(`${API}/sessions/${this.ctx.params.id}`);
    this.detail = r.data;
  }
  private get s(): any { return this.L.get('session', this.ctx.params.id); }

  private async removeIt() {
    const s = this.s;
    if (!(await this.host.confirm('Eliminare l\'allenamento?', `${s.name} del ${dayLabel(s.started_at, false)} e le sue serie.`, { label: 'Elimina', danger: true }))) return;
    for (const x of this.L.setsOf(s.id)) this.L.remove('set', x.id);
    this.L.remove('session', s.id);
    this.host.navigate('storico');
  }
  private repeat() {
    const s = this.s;
    if (this.L.activeSession()) { this.host.toast('C\'è già un allenamento in corso', 'warning'); this.host.navigate('allenamento'); return; }
    const sets = this.L.setsOf(s.id);
    const exercises = (s.exercises || []).map((b: any) => {
      const done = sets.filter((x: any) => x.session_exercise_id === b.id);
      const planned = (done.length ? done : b.planned || []).map((x: any) => ({ type: x.type || 'normal', reps_min: x.reps ?? x.reps_min ?? null, reps_max: x.reps ?? x.reps_max ?? null, reps_target: x.reps ?? x.reps_target ?? null, weight_kg: x.weight_kg ?? null, rpe: null, duration_s: x.duration_s ?? null, distance_m: null }));
      return { ...b, id: uuid(), planned, skipped: false };
    });
    this.L.put('session', uuid(), { name: s.name, status: 'active', started_at: nowIso(), template_id: s.template_id, exercises, readiness: {}, source: 'live', notes: '' });
    this.host.navigate('allenamento');
  }
  private feedback(tag: string) {
    this.L.put('feedback', uuid(), { session_id: this.s.id, tags: [tag], at: nowIso(), text: '' });
    this.host.toast(`Annotato: ${FEEDBACK_TAGS[tag]}`, 'success');
  }

  render() {
    const nr = this.notReady(); if (nr) return nr;
    const s = this.s;
    if (!s) return html`<div class="page"><hxk-state kind="empty" text="Allenamento non trovato."></hxk-state></div>`;
    const L = this.L;
    const exs = L.exercises();
    const sets = L.setsOf(s.id);
    const sm = summary(L, s);
    const prs = ((this.detail?.prs || []) as any[]).filter(p => !p.first);
    const fb = L.list('feedback').filter(f => f.session_id === s.id);
    return html`<div class="page">
      <div class="head"><hxk-button variant="ghost" size="sm" @click=${() => this.host.navigate('storico')}>‹ Storico</hxk-button><span class="grow"></span>
        ${s.status === 'active' ? html`<hxk-button variant="primary" icon="play" @click=${() => this.host.navigate('allenamento')}>Riprendi</hxk-button>` : nothing}
        <hxk-button variant="ghost" icon="edit" @click=${() => (this.editing = !this.editing)}>${this.editing ? 'Fine' : 'Modifica'}</hxk-button></div>
      <div><h1>${s.name}</h1><div class="small muted">${dayLabel(s.started_at)} · ${timeLabel(s.started_at)}${s.ended_at ? '–' + timeLabel(s.ended_at) : ''}</div></div>
      <hxk-stat .items=${[{ label: 'Durata', value: minutes(sm.minutes) }, { label: 'Serie', value: sm.sets }, { label: 'Volume', value: num(sm.volume), unit: 'kg' },
        ...(s.perceived_effort ? [{ label: 'Fatica', value: s.perceived_effort, unit: '/10' }] : [])]}></hxk-stat>
      ${prs.length ? html`<div class="card col"><h3><hxk-icon name="trophy" size=${16} tone="warning"></hxk-icon> Record</h3>${prs.map(p => html`<div class="row"><hxk-badge tone="success">PR</hxk-badge><span class="grow">${p.exercise}: ${p.label}</span>
        <span class="tnum">${kg(p.value)}${p.previous ? html` <span class="muted small">(prima ${kg(p.previous)})</span>` : nothing}</span></div>`)}</div>` : nothing}
      ${this.editing ? html`<div class="card row wrap"><label class="small row">Data
          <input class="in" type="date" .value=${s.started_at.slice(0, 10)} @change=${(e: any) => this.moveDate(e.target.value)}></label>
          <span class="grow"></span><hxk-button variant="danger" icon="trash" @click=${() => this.removeIt()}>Elimina allenamento</hxk-button></div>` : nothing}
      ${(s.exercises || []).map((b: any) => {
        const ex = exs.get(b.exercise_id);
        const mine = sets.filter(x => x.session_exercise_id === b.id);
        if (!mine.length && !this.editing) return nothing;
        const weight = usesWeight(ex?.kind);
        let n = 0;
        return html`<div class="card col">
          <div class="between"><b class="truncate" style="cursor:pointer" @click=${() => this.host.navigate('esercizi/' + b.exercise_id)}>${ex?.name || '?'}</b>
            ${weight ? html`<span class="small muted tnum">${num(mine.filter(x => x.type !== 'warmup').reduce((v, x) => v + (x.weight_kg || 0) * (x.reps || 0), 0))} kg</span>` : nothing}</div>
          ${this.editing ? html`<div class="sets edit">${mine.map(x => html`
              <span class="n">${x.type === 'warmup' ? 'R' : ++n}</span>
              <select class="in" .value=${x.type} @change=${(e: any) => L.put('set', x.id, { ...x, type: e.target.value })}>${Object.entries(SET_TYPE_LABEL).map(([k, v]) => html`<option value=${k} ?selected=${x.type === k}>${v}</option>`)}</select>
              <input class="in" inputmode="decimal" .value=${x.weight_kg == null ? '' : String(x.weight_kg).replace('.', ',')} @change=${(e: any) => L.put('set', x.id, { ...x, weight_kg: parseNum(e.target.value) })}>
              <input class="in" inputmode="numeric" .value=${String(x.reps ?? '')} @change=${(e: any) => L.put('set', x.id, { ...x, reps: parseNum(e.target.value) })}>
              <hxk-button size="sm" variant="ghost" icon="x" @click=${() => L.remove('set', x.id)}></hxk-button>`)}</div>
              <div><hxk-button size="sm" variant="ghost" icon="plus" @click=${() => this.addSet(b, mine)}>Serie</hxk-button></div>`
            : html`<div class="sets">${mine.map(x => html`<span class="n">${x.type === 'warmup' ? 'R' : ++n}</span><span>${setLabel(x, ex?.kind)}${x.rpe ? html` <span class="muted small">@${x.rpe}</span>` : nothing}</span>
              <span class="small muted">${weight && x.reps && x.weight_kg && x.type !== 'warmup' ? '1RM ' + kg(Math.round(x.weight_kg * (1 + x.reps / 30) * 10) / 10) : ''}</span>`)}</div>`}
        </div>`;
      })}
      ${s.notes ? html`<div class="card"><h3>Note</h3><div>${s.notes}</div></div>` : nothing}
      <div class="card col"><h3>Com'è andata?</h3>
        ${fb.length ? html`<div class="chips">${fb.flatMap(f => f.tags || []).map((t: string) => html`<span class="pill">${FEEDBACK_TAGS[t] || t}</span>`)}</div>` : nothing}
        <div class="chips">${Object.entries(FEEDBACK_TAGS).map(([k, v]) => html`<button class="chip" @click=${() => this.feedback(k)}>${v}</button>`)}</div>
        <div class="row wrap"><hxk-button icon="refresh" @click=${() => this.repeat()}>Ripeti questo allenamento</hxk-button>
          <hxk-button variant="ghost" icon="heart" @click=${() => this.host.assistant({ label: `Allenamento ${s.name}`, hints: { session_id: s.id }, prompt: `Commentiamo l'allenamento ${s.name} del ${dayLabel(s.started_at, false)}.` })}>Commenta con l'assistente</hxk-button></div>
      </div>
    </div>`;
  }

  private addSet(b: any, mine: any[]) {
    const last = mine[mine.length - 1];
    this.L.put('set', uuid(), { session_id: this.s.id, session_exercise_id: b.id, exercise_id: b.exercise_id, session_at: this.s.started_at,
      position: mine.length, type: 'normal', weight_kg: last?.weight_kg ?? null, reps: last?.reps ?? null, completed: true, completed_at: this.s.started_at });
  }
  private moveDate(day: string) {
    if (!day) return;
    const s = this.s;
    const shift = Date.parse(day + s.started_at.slice(10)) - Date.parse(s.started_at);
    if (isNaN(shift) || !shift) return;
    const started = new Date(Date.parse(s.started_at) + shift).toISOString();
    const ended = s.ended_at ? new Date(Date.parse(s.ended_at) + shift).toISOString() : null;
    this.L.put('session', s.id, { ...s, started_at: started, ended_at: ended });
    for (const x of this.L.setsOf(s.id)) this.L.put('set', x.id, { ...x, session_at: started });
  }
}
