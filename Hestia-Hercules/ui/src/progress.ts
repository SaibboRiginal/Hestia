/**
 * <hercules-progress> — "Progressi": workouts and volume per week/month, sets per muscle group, year heatmap,
 * recent records and goals. <hercules-body> — "Corpo": bodyweight trend and body measurements (offline logging).
 */
import { HestiaElement, html, css, nothing } from '@hestia/webui-sdk';
import { API, nowIso, uuid } from './data';
import { LocalPage } from './templates';
import { GROUP_LABEL, MEASURES, MEASURE_UNIT, dayLabel, herculesStyles, kg, minutes, num, parseNum } from './util';

function periodLabel(start: string, per: string): string {
  return per === 'month' ? new Date(start + 'T12:00:00').toLocaleDateString('it-IT', { month: 'short' }) : dayLabel(start, false);
}

export class HerculesProgress extends LocalPage {
  static properties = { ...HestiaElement.properties, per: { state: true }, stats: { state: true }, goals: { state: true }, fresh: { state: true } };
  declare per: 'week' | 'month'; declare stats: any; declare goals: any[] | null; declare fresh: boolean;
  static styles = [...HestiaElement.styles, herculesStyles, css`
    .heat { display: grid; grid-auto-flow: column; grid-template-rows: repeat(7, 11px); gap: 3px; overflow-x: auto; padding-bottom: 4px; }
    .heat i { width: 11px; height: 11px; border-radius: 2px; background: var(--surface-3); display: block; }
    .heat i.l1 { background: color-mix(in srgb, var(--accent) 45%, var(--surface-3)); }
    .heat i.l2 { background: var(--accent); }
    .bars { display: flex; flex-direction: column; gap: 6px; }
    .bar { display: grid; grid-template-columns: 80px 1fr 60px; gap: 8px; align-items: center; font-size: 13px; }
    .bar .t { height: 10px; border-radius: 5px; background: var(--surface-3); overflow: hidden; }
    .bar .t i { display: block; height: 100%; background: var(--accent); }
    .bar .t i.low { background: var(--warning); }
  `];
  constructor() { super(); this.per = 'week'; this.stats = undefined; this.goals = null; this.fresh = true; }

  protected async loaded() {
    const [s, g] = await Promise.all([this.L.cached(`${API}/stats`, { per: this.per, count: 12 }), this.L.cached(`${API}/goals`)]);
    this.stats = s.data; this.fresh = s.fresh; this.goals = g.data?.items ?? [];
  }
  updated() { const h = this.renderRoot.querySelector('.heat'); if (h) h.scrollLeft = h.scrollWidth; }   // newest weeks in view
  private setPer(p: 'week' | 'month') { this.per = p; this.stats = undefined; this.loaded(); }

  render() {
    const nr = this.notReady(); if (nr) return nr;
    const st = this.stats;
    if (st === undefined) return html`<div class="page"><hxk-state kind="loading"></hxk-state></div>`;
    if (st === null) return html`<div class="page"><hxk-state kind="offline" text="I progressi si calcolano quando sei online." @retry=${() => this.loaded()}></hxk-state></div>`;
    const periods = st.periods || [];
    const cur = periods[periods.length - 1] || {}, prev = periods[periods.length - 2] || {};
    const label = (p: any) => periodLabel(p.start, this.per);
    const delta = (a: number, b: number) => (b ? `${a >= b ? '+' : ''}${Math.round(((a - b) / b) * 100)}%` : '');
    const groups = cur.groups || {};
    const maxG = Math.max(10, ...Object.values(groups).map(Number));
    const target = this.per === 'week' ? 10 : 40;
    const heat = (st.heatmap || []) as any[];
    const hm = new Map(heat.map(h => [h.date, h.count]));
    const days: string[] = [];
    const end = new Date(); const start = new Date(end.getTime() - 52 * 7 * 86400000);
    start.setDate(start.getDate() - ((start.getDay() + 6) % 7));
    for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) days.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`);
    const prs = (st.recent_prs || []) as any[];
    return html`<div class="page">
      <div class="head"><h1>Progressi</h1>${this.fresh ? nothing : html`<span class="offline">dati dell'ultima connessione</span>`}<span class="grow"></span>
        <div class="tabs"><button class="tab" aria-pressed=${this.per === 'week'} @click=${() => this.setPer('week')}>Settimane</button>
          <button class="tab" aria-pressed=${this.per === 'month'} @click=${() => this.setPer('month')}>Mesi</button></div></div>
      <hxk-stat .items=${[
        { label: this.per === 'week' ? 'Allenamenti settimana' : 'Allenamenti mese', value: cur.sessions ?? 0, delta: delta(cur.sessions || 0, prev.sessions || 0) },
        { label: 'Volume', value: num(cur.volume), unit: 'kg', delta: delta(cur.volume || 0, prev.volume || 0) },
        { label: 'Serie', value: cur.sets ?? 0, delta: delta(cur.sets || 0, prev.sets || 0) },
        { label: 'Tempo', value: minutes(cur.duration_min) },
        { label: 'Totale', value: st.totals?.sessions ?? 0, hint: st.totals?.since ? 'dal ' + dayLabel(st.totals.since, false) : '' },
      ]}></hxk-stat>

      ${this.goals?.length ? html`<div class="card col"><h3>Obiettivi</h3>${this.goals.map(g => html`<div class="between">
          <div><div>${g.progress.label}</div><div class="small muted">${g.progress.hint}${g.progress.streak ? ` · ${g.progress.streak} di fila 🔥` : ''}</div></div>
          ${g.progress.met ? html`<hxk-badge tone="success">Fatto</hxk-badge>` : g.progress.behind ? html`<hxk-badge tone="warning">Indietro</hxk-badge>` : html`<hxk-badge>In corso</hxk-badge>`}</div>
          <hxk-chart type="bar" height="90" .labels=${(g.progress.history || []).map((h: any) => periodLabel(h.start, g.per))} .series=${[{ name: 'Fatti', values: (g.progress.history || []).map((h: any) => h.done) }]}></hxk-chart>`)}</div>` : nothing}

      <div class="grid" style="--min:320px">
        <div class="card col"><h3>Allenamenti</h3>
          <hxk-chart type="bar" height="180" .labels=${periods.map(label)} .series=${[{ name: 'Allenamenti', values: periods.map((p: any) => p.sessions) }]}></hxk-chart></div>
        <div class="card col"><h3>Volume</h3>
          <hxk-chart type="line" height="180" unit="kg" .labels=${periods.map(label)} .series=${[{ name: 'Volume', values: periods.map((p: any) => p.volume) }]}></hxk-chart></div>
      </div>

      <div class="card col"><div class="between"><h3>Serie per gruppo · ${this.per === 'week' ? 'questa settimana' : 'questo mese'}</h3>
        <span class="small muted">serie allenanti (secondari ½)</span></div>
        <div class="bars">${Object.entries(GROUP_LABEL).map(([g, l]) => {
          const v = Number(groups[g] || 0);
          return html`<div class="bar"><span>${l}</span><span class="t"><i class=${v < target / 2 ? 'low' : ''} style="width:${Math.min(100, (v / maxG) * 100)}%"></i></span><span class="tnum muted">${num(v, 1)}</span></div>`;
        })}</div></div>

      <div class="card col"><h3>Ultimo anno</h3>
        <div class="heat">${days.map(d => { const c = hm.get(d) || 0; return html`<i class=${c >= 2 ? 'l2' : c ? 'l1' : ''} title=${`${dayLabel(d, false)}${c ? ` · ${c}` : ''}`}></i>`; })}</div></div>

      <div class="card col"><h3>Record recenti</h3>
        ${prs.length ? html`<div class="list">${prs.map(p => html`<div class="li" @click=${() => p.exercise_id && this.host.navigate('esercizi/' + p.exercise_id)}>
          <hxk-badge tone="success">PR</hxk-badge><div class="grow"><div class="truncate">${p.exercise}</div><div class="small muted">${p.label} · ${dayLabel(p.date || '', false)}</div></div>
          <div class="tnum">${kg(p.value)}${p.previous ? html`<div class="small muted">prima ${kg(p.previous)}</div>` : nothing}</div></div>`)}</div>`
          : html`<div class="empty">Nessun record negli ultimi 30 giorni. Continua così e arriveranno.</div>`}</div>
    </div>`;
  }
}

export class HerculesBody extends LocalPage {
  static properties = { ...HestiaElement.properties, kind: { state: true }, value: { state: true }, range: { state: true } };
  declare kind: string; declare value: string; declare range: number;
  static styles = [...HestiaElement.styles, herculesStyles];
  constructor() { super(); this.kind = 'bodyweight'; this.value = ''; this.range = 90; }

  private log() {
    const v = parseNum(this.value);
    if (v === null || v <= 0) { this.host.toast('Valore non valido', 'warning'); return; }
    this.L.put('measurement', uuid(), { kind: this.kind, value: v, taken_at: nowIso(), unit: MEASURE_UNIT[this.kind] || 'cm', notes: '' });
    this.value = '';
    this.host.toast(`${MEASURES[this.kind]}: ${kg(v)} ${MEASURE_UNIT[this.kind] || 'cm'}`, 'success');
  }

  render() {
    const nr = this.notReady(); if (nr) return nr;
    const all = this.L.list('measurement').sort((a, b) => (a.taken_at || '').localeCompare(b.taken_at || ''));
    const since = new Date(Date.now() - this.range * 86400000).toISOString();
    const pts = all.filter(m => m.kind === this.kind && (this.range === 0 || m.taken_at >= since));
    const unit = MEASURE_UNIT[this.kind] || 'cm';
    const last = pts[pts.length - 1], first = pts[0];
    const avg7 = (() => {
      const w = all.filter(m => m.kind === this.kind && m.taken_at >= new Date(Date.now() - 7 * 86400000).toISOString());
      return w.length ? w.reduce((s, m) => s + m.value, 0) / w.length : null;
    })();
    const kinds = Object.keys(MEASURES).filter(k => k === 'bodyweight' || all.some(m => m.kind === k));
    return html`<div class="page">
      <div class="head"><h1>Corpo</h1><span class="sub">peso e misure</span></div>
      <div class="card col"><h2>Registra</h2><div class="row wrap">
        <select class="in" .value=${this.kind} @change=${(e: any) => (this.kind = e.target.value)}>${Object.entries(MEASURES).map(([k, v]) => html`<option value=${k} ?selected=${this.kind === k}>${v}</option>`)}</select>
        <input class="in num" style="width:100px" inputmode="decimal" placeholder=${last ? kg(last.value) : unit} .value=${this.value}
          @input=${(e: any) => (this.value = e.target.value)} @keydown=${(e: KeyboardEvent) => e.key === 'Enter' && this.log()}>
        <span class="muted">${unit}</span>
        <hxk-button variant="primary" icon="plus" @click=${() => this.log()}>Salva</hxk-button></div></div>
      <div class="tabs">${kinds.map(k => html`<button class="tab" aria-pressed=${this.kind === k} @click=${() => (this.kind = k)}>${MEASURES[k]}</button>`)}</div>
      ${last ? html`<hxk-stat .items=${[
          { label: 'Ultimo', value: kg(last.value), unit, hint: dayLabel(last.taken_at) },
          ...(avg7 !== null ? [{ label: 'Media 7 giorni', value: kg(Math.round(avg7 * 10) / 10), unit }] : []),
          ...(first && first !== last ? [{ label: 'Variazione', value: `${last.value - first.value >= 0 ? '+' : ''}${kg(Math.round((last.value - first.value) * 10) / 10)}`, unit, hint: 'dal ' + dayLabel(first.taken_at, false) }] : []),
        ]}></hxk-stat>` : nothing}
      <div class="card col"><div class="between"><h3>${MEASURES[this.kind]}</h3>
        <div class="tabs">${[[30, '1 mese'], [90, '3 mesi'], [365, '1 anno'], [0, 'Tutto']].map(([d, l]) => html`<button class="tab" aria-pressed=${this.range === d} @click=${() => (this.range = d as number)}>${l}</button>`)}</div></div>
        ${pts.length > 1 ? html`<hxk-chart type="line" height="220" unit=${unit} .labels=${pts.map(m => dayLabel(m.taken_at, false))} .series=${[{ name: MEASURES[this.kind], values: pts.map(m => m.value) }]}></hxk-chart>`
          : html`<div class="empty">Registra almeno due valori per vedere l'andamento.</div>`}</div>
      ${pts.length ? html`<div class="card list">${[...pts].reverse().slice(0, 30).map(m => html`<div class="li" style="cursor:default">
          <span class="grow">${dayLabel(m.taken_at)}</span><span class="tnum">${kg(m.value)} ${m.unit || unit}</span>
          <hxk-button size="sm" variant="ghost" icon="trash" @click=${() => this.L.remove('measurement', m.id)}></hxk-button></div>`)}</div>` : nothing}
    </div>`;
  }
}
