/**
 * <chronos-cal-grid> — week (7 days) / day (1 day) time grid.
 * - windows: 'lane' = clickable strip at the column's left edge + sticky label + faint tint; 'band' = translucent band
 * - frequent rules in 'compact' mode → one summary chip per rule per day in the top «Ricorrenti» row
 *   (failed runs always stay as their own blocks)
 * - drag a block to move (15-min snap, across days), drag its bottom edge to resize
 * Events: cal-select {ev, rect} · cal-create (Date) · cal-move {ev,start,end} · cal-day (Date).
 */
import { LitElement, css, html, nothing, tokens } from '@hestia/webui-sdk';
import { type CalEvent, TYPE_META, fire } from '../models';
import { DAY_MS, addDays, addMinutes, fmt, isSameDay, isToday, minutesOfDay, snap, startOfDay } from '../date';
import type { FrequentMode, WindowsMode } from '../prefs';
import { calStyles, ic } from '../ui';

const HOUR = 48;
const MIN_BLOCK_MIN = 22;            // instants and very short items still get a clickable block
const SNAP_MIN = 15;
const LANE = 10;                     // window lane width (strip 7px + gap)
const GUTTER = 56;

interface Placed { ev: CalEvent; top: number; height: number; col: number; cols: number; instant: boolean; segStart: Date; }
interface Band { ev: CalEvent; top: number; height: number; lane: number; segStart: Date; }
interface Drag { ev: CalEvent; mode: 'move' | 'resize'; startX: number; startY: number; moved: boolean;
                 dayDelta: number; minDelta: number; colWidth: number; target: HTMLElement; }
interface Segs { bands: Band[][]; blocks: Placed[][]; lanes: number[]; groups: CalEvent[][]; }

export class ChronosCalGrid extends LitElement {
  static properties = {
    days: { attribute: false }, events: { attribute: false }, windowsMode: { attribute: false }, frequentMode: { attribute: false },
    focusDay: { attribute: false }, scrollHour: { attribute: false }, workHours: { attribute: false },
    drag: { state: true }, now: { state: true }, scrollY: { state: true },
  };
  declare days: Date[]; declare events: CalEvent[]; declare windowsMode: WindowsMode; declare frequentMode: FrequentMode;
  declare focusDay: Date; declare scrollHour: number; declare workHours: [number, number];
  declare drag: Drag | null; declare now: number; declare scrollY: number;
  private segs: Segs = { bands: [], blocks: [], lanes: [], groups: [] };
  private timer: ReturnType<typeof setInterval> | null = null;
  private justDragged = false;
  private scrolledFor = '';

  static styles = [tokens, calStyles, css`
    :host { display: flex; flex-direction: column; min-height: 0; flex: 1; user-select: none; }
    .head { display: grid; border-bottom: 1px solid var(--border); flex-shrink: 0; padding-right: 8px; }
    .dh { display: flex; flex-direction: column; align-items: center; padding: 8px 0 6px; gap: 2px; border-radius: var(--radius-md); }
    .dh:hover { background: var(--surface-2); }
    .wd { font-size: 11.5px; color: var(--text-3); text-transform: uppercase; letter-spacing: .04em; }
    .dn { font-size: 20px; width: 36px; height: 36px; display: grid; place-items: center; border-radius: 50%; color: var(--text); }
    .dh.today .dn { background: var(--accent); color: var(--accent-contrast); }
    .dh.today .wd { color: var(--accent); }
    .dh.sel { background: var(--accent-soft); }
    .sum { display: grid; border-bottom: 1px solid var(--border); flex-shrink: 0; padding-right: 8px; max-height: 96px; overflow-y: auto; }
    .sum-h { font-size: 10.5px; color: var(--text-3); text-align: right; padding: 6px 6px 0 0; line-height: 1.1; }
    .sum-c { border-left: 1px solid var(--border); padding: 3px; display: flex; flex-direction: column; gap: 2px; min-width: 0; }
    .schip { display: flex; align-items: center; gap: 4px; font-size: 11px; padding: 2px 6px; border-radius: var(--radius-full);
             background: color-mix(in srgb, var(--c) 12%, transparent); color: var(--text-2); min-width: 0; text-align: left; }
    .schip:hover { background: color-mix(in srgb, var(--c) 22%, transparent); color: var(--text); }
    .schip.paused { filter: grayscale(.8); opacity: .7; }
    .schip .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--c); flex-shrink: 0; }
    .tr { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
    .schip .x, .fx { margin-left: auto; font-size: 10px; color: var(--text-3); flex-shrink: 0; }
    .tint { position: absolute; left: 0; right: 0; background: color-mix(in srgb, var(--c) 5%, transparent); pointer-events: none; }
    .lane { position: absolute; width: 7px; pointer-events: auto; cursor: pointer; border-radius: 4px; z-index: 1;
            background: repeating-linear-gradient(180deg, color-mix(in srgb, var(--c) 75%, transparent) 0 6px, color-mix(in srgb, var(--c) 45%, transparent) 6px 9px); }
    .lane:hover { width: 9px; background: var(--c); }
    .lane.skipped { opacity: .4; }
    .lane.paused, .lane-label.paused { filter: grayscale(1); opacity: .5; }
    .lane-label { position: absolute; pointer-events: auto; cursor: pointer; z-index: 1; max-width: calc(100% - 24px);
                  font-size: 10.5px; line-height: 16px; padding: 0 6px; border-radius: 0 var(--radius-full) var(--radius-full) 0;
                  background: color-mix(in srgb, var(--c) 16%, var(--surface)); color: color-mix(in srgb, var(--c) 70%, var(--text));
                  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .lane-label:hover { background: color-mix(in srgb, var(--c) 28%, var(--surface)); }
    .lane-label b, .band-label b { font-weight: 700; font-variant-numeric: tabular-nums; }
    .scroll { flex: 1; overflow-y: auto; overflow-x: hidden; position: relative; min-height: 0; }
    .grid { display: grid; position: relative; }
    .gutter { position: relative; }
    .hl { position: absolute; right: 8px; transform: translateY(-50%); font-size: 11px; color: var(--text-3); }
    .col { position: relative; border-left: 1px solid var(--border); cursor: cell; }
    .col.today { background: color-mix(in srgb, var(--accent) 3%, transparent); }
    .off { position: absolute; left: 0; right: 0; background: color-mix(in srgb, var(--text) 3.5%, transparent); pointer-events: none; }
    .line { position: absolute; left: 0; right: 0; border-top: 1px solid var(--border); }
    .half { position: absolute; left: 0; right: 0; border-top: 1px dashed color-mix(in srgb, var(--border) 60%, transparent); }
    .now { position: absolute; left: -1px; right: 0; border-top: 2px solid var(--danger); z-index: 6; pointer-events: none; }
    .now span { position: absolute; left: -5px; top: -6px; width: 10px; height: 10px; border-radius: 50%; background: var(--danger); }
    .layer { position: absolute; inset: 0; display: grid; pointer-events: none; }
    .lcol { position: relative; }
    .band { position: absolute; left: 0; right: 4px; pointer-events: auto; cursor: grab; border-radius: var(--radius-sm);
            background: color-mix(in srgb, var(--c) 9%, transparent); border-left: 3px solid color-mix(in srgb, var(--c) 70%, transparent); }
    .band:hover { background: color-mix(in srgb, var(--c) 15%, transparent); }
    .band-label { display: flex; align-items: center; gap: 4px; font-size: 11px; font-weight: 500; padding: 3px 6px;
                  color: color-mix(in srgb, var(--c) 85%, var(--text)); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .band.skipped { background: repeating-linear-gradient(135deg, transparent 0 6px, color-mix(in srgb, var(--c) 10%, transparent) 6px 12px); opacity: .7; }
    .band.paused { filter: grayscale(.8); opacity: .6; }
    .blk { position: absolute; pointer-events: auto; cursor: grab; border-radius: var(--radius-sm); padding: 3px 6px; overflow: hidden;
           background: color-mix(in srgb, var(--c) 18%, var(--surface)); border: 1px solid color-mix(in srgb, var(--c) 40%, transparent);
           border-left: 3px solid var(--c); color: var(--text); font-size: 12px; line-height: 1.3; box-shadow: var(--shadow-1); z-index: 2; }
    .blk:hover { z-index: 4; box-shadow: var(--shadow-2); }
    .blk.instant { border-radius: var(--radius-full); padding: 2px 8px; }
    .bt { display: flex; align-items: center; gap: 4px; font-weight: 500; }
    .bm { color: var(--text-3); font-size: 11px; }
    .blk.skipped { text-decoration: line-through; opacity: .55; }
    .blk.done { opacity: .55; }
    .blk.paused { filter: grayscale(.8); opacity: .7; }
    .blk.moved { border-style: dashed; }
    .blk.failed { border-color: var(--danger); background: color-mix(in srgb, var(--danger) 12%, var(--surface)); }
    .blk.failed .ic { color: var(--danger); }
    .blk.dragging, .band.dragging, .lane.dragging { opacity: .35; }
    .rz { position: absolute; left: 0; right: 0; bottom: 0; height: 7px; cursor: ns-resize; }
    .ghost { position: absolute; z-index: 10; pointer-events: none; border: 2px dashed var(--accent); border-radius: var(--radius-sm);
             background: var(--accent-soft); color: var(--accent); font-size: 11.5px; font-weight: 600; padding: 3px 6px; }
  `];

  constructor() {
    super();
    this.days = []; this.events = []; this.windowsMode = 'lane'; this.frequentMode = 'compact'; this.focusDay = new Date();
    this.scrollHour = 7; this.workHours = [9, 18]; this.drag = null; this.now = Date.now(); this.scrollY = 0;
  }
  connectedCallback() { super.connectedCallback(); this.timer = setInterval(() => (this.now = Date.now()), 60_000); }
  disconnectedCallback() { super.disconnectedCallback(); if (this.timer) clearInterval(this.timer); this.detach(); }

  private nowTop() { return minutesOfDay(new Date(this.now)) / 60 * HOUR; }

  updated() {
    // scroll once per set of days: to "now" when today is shown, otherwise to the preferred hour
    const id = this.days.map(d => d.getTime()).join(',');
    if (id === this.scrolledFor) return;
    const el = this.renderRoot.querySelector('.scroll') as HTMLElement | null;
    if (!el) return;
    this.scrolledFor = id;
    el.scrollTop = this.days.some(isToday) ? Math.max(0, this.nowTop() - 160) : this.scrollHour * HOUR;
    this.scrollY = el.scrollTop;
  }

  willUpdate(ch: Map<string, unknown>) {
    if (ch.has('days') || ch.has('events') || ch.has('windowsMode') || ch.has('frequentMode')) this.segs = this.segments();
  }

  /** Per-day segments, windows split from blocks. */
  private segments(): Segs {
    const days = this.days;
    const bands: Band[][] = days.map(() => []);
    const blocks: Placed[][] = days.map(() => []);
    const summary: CalEvent[][] = days.map(() => []);
    const compact = this.frequentMode === 'compact';
    for (const ev of this.events) {
      const s = ev.start, e = ev.end ?? addMinutes(ev.start, MIN_BLOCK_MIN);
      if (compact && ev.cls === 'frequent' && ev.occ.type !== 'window' && ev.occ.run?.ok !== false) {
        const i = days.findIndex(d => isSameDay(d, s));
        if (i >= 0) summary[i].push(ev);
        continue;
      }
      days.forEach((d, i) => {
        const ds = startOfDay(d), de = new Date(ds.getTime() + DAY_MS);
        if (e <= ds || s >= de) return;
        const segStart = s < ds ? ds : s, segEnd = e > de ? de : e;
        const top = minutesOfDay(segStart) / 60 * HOUR;
        const rawH = ((segEnd.getTime() - segStart.getTime()) / 60000) / 60 * HOUR;
        if (ev.occ.type === 'window') bands[i].push({ ev, top, height: Math.max(rawH, 18), lane: 0, segStart });
        else blocks[i].push({ ev, top, height: Math.max(rawH, MIN_BLOCK_MIN / 60 * HOUR), col: 0, cols: 1, instant: !ev.end, segStart });
      });
    }
    bands.forEach(layoutLanes);
    blocks.forEach(layoutColumns);
    const lanes = bands.map(list => this.windowsMode === 'lane' && list.length ? Math.max(...list.map(b => b.lane)) + 1 : 0);
    const groups = summary.map((list, i) => {
      const byKey = new Map<string, CalEvent[]>();
      for (const ev of list) (byKey.get(ev.occ.key) ?? byKey.set(ev.occ.key, []).get(ev.occ.key)!).push(ev);
      return [...byKey.values()].map(g => {
        g.sort((a, b) => a.start.getTime() - b.start.getTime());
        return { ...g[0], id: `${g[0].occ.key}|sum|${i}`, group: g } as CalEvent;
      });
    });
    return { bands, blocks, lanes, groups };
  }

  private cols() { return `${GUTTER}px repeat(${this.days.length}, minmax(0, 1fr))`; }
  private time(ev: CalEvent) { return `${fmt.time(ev.start)}${ev.end ? ' – ' + fmt.time(ev.end) : ''}`; }
  private segTime(b: Band) { return `${fmt.time(b.ev.start)}–${b.ev.end ? fmt.time(b.ev.end) : ''}`; }
  /** Window labels stick to the top of the viewport while their window is on screen. */
  private labelTop(b: Band) { return Math.min(Math.max(b.top, this.scrollY + 2), Math.max(b.top, b.top + b.height - 17)); }
  private offHours(d: Date): { all: boolean; start: number; end: number } | null {
    const [s, e] = this.workHours;
    if (!(e > s)) return null;
    const wd = d.getDay();
    return { all: wd === 0 || wd === 6, start: Math.max(0, s), end: Math.min(24, e) };
  }
  private sel(ev: CalEvent, el: HTMLElement) { fire(this, 'cal-select', { ev, rect: el.getBoundingClientRect() }); }

  private slotClick(e: MouseEvent, day: Date) {
    if (this.justDragged) { this.justDragged = false; return; }
    const col = e.currentTarget as HTMLElement;
    const y = e.clientY - col.getBoundingClientRect().top;
    fire(this, 'cal-create', addMinutes(startOfDay(day), Math.floor((y / HOUR * 60) / 30) * 30));
  }

  // ── drag & drop (pointer events) ───────────────────────────────────────
  private onMove = (e: PointerEvent) => this.dragMove(e);
  private onUp = () => this.dragEnd();
  private onCancel = () => { this.detach(); this.drag = null; };   // touch scroll took over

  private startDrag(e: PointerEvent, ev: CalEvent, mode: 'move' | 'resize') {
    if (e.button !== 0) return;
    e.stopPropagation();
    if (mode === 'resize' && !ev.end) return;
    const grid = this.renderRoot.querySelector('.grid') as HTMLElement | null;
    const colWidth = grid ? (grid.clientWidth - GUTTER) / this.days.length : 100;
    this.drag = { ev, mode, startX: e.clientX, startY: e.clientY, moved: false, dayDelta: 0, minDelta: 0, colWidth,
                  target: e.currentTarget as HTMLElement };
    window.addEventListener('pointermove', this.onMove);
    window.addEventListener('pointerup', this.onUp, { once: true });
    window.addEventListener('pointercancel', this.onCancel, { once: true });
  }
  private dragMove(e: PointerEvent) {
    const d = this.drag;
    if (!d) return;
    const dx = e.clientX - d.startX, dy = e.clientY - d.startY;
    const moved = d.moved || Math.abs(dx) > 4 || Math.abs(dy) > 4;
    const minDelta = Math.round((dy / HOUR * 60) / SNAP_MIN) * SNAP_MIN;
    const dayDelta = d.mode === 'move' ? Math.round(dx / d.colWidth) : 0;
    if (moved !== d.moved || minDelta !== d.minDelta || dayDelta !== d.dayDelta) this.drag = { ...d, moved, minDelta, dayDelta };
  }
  private dragEnd() {
    const d = this.drag;
    this.detach();
    this.drag = null;
    if (!d) return;
    if (!d.moved) { this.sel(d.ev, d.target); return; }
    this.justDragged = true;
    setTimeout(() => (this.justDragged = false), 50);
    const { start, end } = this.preview(d);
    if (start.getTime() === d.ev.start.getTime() && (end?.getTime() ?? 0) === (d.ev.end?.getTime() ?? 0)) return;
    fire(this, 'cal-move', { ev: d.ev, start, end });
  }
  private preview(d: Drag): { start: Date; end: Date | null } {
    if (d.mode === 'resize' && d.ev.end) {
      const end = snap(addMinutes(d.ev.end, d.minDelta), SNAP_MIN);
      return { start: d.ev.start, end: end > addMinutes(d.ev.start, SNAP_MIN) ? end : addMinutes(d.ev.start, SNAP_MIN) };
    }
    const start = addDays(addMinutes(d.ev.start, d.minDelta), d.dayDelta);
    const end = d.ev.end ? new Date(d.ev.end.getTime() + (start.getTime() - d.ev.start.getTime())) : null;
    return { start, end };
  }
  private detach() {
    window.removeEventListener('pointermove', this.onMove); window.removeEventListener('pointerup', this.onUp);
    window.removeEventListener('pointercancel', this.onCancel);
  }

  private ghost() {
    const d = this.drag;
    if (!d || !d.moved) return nothing;
    const { start, end } = this.preview(d);
    const i = this.days.findIndex(x => startOfDay(x).getTime() === startOfDay(start).getTime());
    if (i < 0) return nothing;
    const top = minutesOfDay(start) / 60 * HOUR;
    const e = end ?? addMinutes(start, MIN_BLOCK_MIN);
    const height = Math.max(18, (e.getTime() - start.getTime()) / 3600000 * HOUR);
    const n = this.days.length;
    return html`<div class="ghost" style="top:${top}px;height:${height}px;left:calc(${GUTTER}px + (100% - ${GUTTER}px) / ${n} * ${i} + 2px);width:calc((100% - ${GUTTER}px) / ${n} - 4px)">
      ${fmt.time(start)}${end ? ' – ' + fmt.time(end) : ''}</div>`;
  }

  private bands(i: number) {
    const dragId = this.drag?.ev.id;
    return this.segs.bands[i].map(b => {
      const st = `--c:${b.ev.color}`, cls = `${b.ev.occ.skipped ? 'skipped' : ''} ${b.ev.occ.status === 'paused' ? 'paused' : ''} ${dragId === b.ev.id ? 'dragging' : ''}`;
      const rz = html`<div class="rz" @pointerdown=${(e: PointerEvent) => this.startDrag(e, b.ev, 'resize')}></div>`;
      if (this.windowsMode === 'lane') return html`
        <div class="tint" style="top:${b.top}px;height:${b.height}px;${st}"></div>
        <div class="lane ${cls}" style="top:${b.top}px;height:${b.height}px;left:${b.lane * LANE}px;${st}" title=${`Finestra · ${b.ev.occ.title} · ${this.time(b.ev)}`}
             @pointerdown=${(e: PointerEvent) => this.startDrag(e, b.ev, 'move')} @click=${(e: Event) => e.stopPropagation()}>${rz}</div>
        <div class="lane-label ${b.ev.occ.status === 'paused' ? 'paused' : ''}" style="top:${this.labelTop(b)}px;left:${this.segs.lanes[i] * LANE + 2}px;${st}"
             @pointerdown=${(e: PointerEvent) => this.startDrag(e, b.ev, 'move')} @click=${(e: Event) => e.stopPropagation()}>
          <b>${this.segTime(b)}</b> ${b.ev.occ.title}</div>`;
      return html`<div class="band ${cls}" style="top:${b.top}px;height:${b.height}px;left:${b.lane * 6}px;${st}" title=${`${b.ev.occ.title} — ${this.time(b.ev)}`}
          @pointerdown=${(e: PointerEvent) => this.startDrag(e, b.ev, 'move')} @click=${(e: Event) => e.stopPropagation()}>
        <div class="band-label">${ic('window', 12)}<b>${this.segTime(b)}</b>&nbsp;${b.ev.occ.title}</div>${rz}</div>`;
    });
  }

  private blocks(i: number) {
    const off = this.segs.lanes[i] * LANE, dragId = this.drag?.ev.id;
    return this.segs.blocks[i].map(p => {
      const o = p.ev.occ, failed = o.run?.ok === false;
      return html`<div class="blk ${p.instant ? 'instant' : ''} ${o.skipped ? 'skipped' : ''} ${o.status === 'completed' || o.status === 'cancelled' ? 'done' : ''}
          ${o.status === 'paused' ? 'paused' : ''} ${o.moved ? 'moved' : ''} ${failed ? 'failed' : ''} ${dragId === p.ev.id ? 'dragging' : ''}"
          style="top:${p.top}px;height:${p.height}px;left:calc(${off}px + (100% - ${off}px) * ${p.col / p.cols} + 2px);width:calc((100% - ${off}px) / ${p.cols} - 4px);--c:${p.ev.color}"
          @pointerdown=${(e: PointerEvent) => this.startDrag(e, p.ev, 'move')} @click=${(e: Event) => e.stopPropagation()}>
        <div class="bt">${ic(failed ? 'alert' : TYPE_META[o.type]?.icon ?? 'event', 12)}<span class="tr">${o.title}</span>
          ${(p.ev.failedCount ?? 0) > 1 ? html`<span class="fx">×${p.ev.failedCount}</span>` : nothing}</div>
        ${p.height > 34 ? html`<div class="bm">${this.time(p.ev)}</div>` : nothing}
        ${!p.instant ? html`<div class="rz" @pointerdown=${(e: PointerEvent) => this.startDrag(e, p.ev, 'resize')}></div>` : nothing}
      </div>`;
    });
  }

  render() {
    const cols = this.cols(), hours = Array.from({ length: 24 }, (_, h) => h);
    const hasSummary = this.segs.groups.some(g => g.length);
    return html`
      <div class="head" style="grid-template-columns:${cols}"><div></div>
        ${this.days.map(d => html`<button class="dh ${isToday(d) ? 'today' : ''} ${this.days.length > 1 && isSameDay(d, this.focusDay) ? 'sel' : ''}"
          @click=${() => fire(this, 'cal-day', d)} title=${'Apri ' + fmt.dayLong(d)}><span class="wd">${fmt.weekdayShort(d)}</span><span class="dn">${d.getDate()}</span></button>`)}
      </div>
      ${hasSummary ? html`<div class="sum" style="grid-template-columns:${cols}">
        <div class="sum-h" title="Attività che si ripetono spesso, raggruppate (Vista → Ricorrenze frequenti)">Ricorrenti</div>
        ${this.days.map((_, i) => html`<div class="sum-c">${this.segs.groups[i].map(g => {
          const l = g.group ?? [g];
          return html`<button class="schip ${g.occ.status === 'paused' ? 'paused' : ''}" style="--c:${g.color}" @click=${(e: Event) => this.sel(g, e.currentTarget as HTMLElement)}
            title=${`${g.occ.title} · ${l.length} volte: ${fmt.time(l[0].start)}–${fmt.time(l[l.length - 1].start)}`}>
            <span class="dot"></span><span class="tr">${g.occ.title}</span><span class="x">×${l.length}</span></button>`; })}</div>`)}
      </div>` : nothing}
      <div class="scroll" @scroll=${(e: Event) => (this.scrollY = (e.target as HTMLElement).scrollTop)}>
        <div class="grid" style="grid-template-columns:${cols};height:${24 * HOUR}px">
          <div class="gutter">${hours.map(h => html`<div class="hl" style="top:${h * HOUR}px"><span>${h ? String(h).padStart(2, '0') + ':00' : ''}</span></div>`)}</div>
          ${this.days.map(d => {
            const o = this.offHours(d);
            return html`<div class="col ${isToday(d) ? 'today' : ''}" @click=${(e: MouseEvent) => this.slotClick(e, d)}>
              ${o ? (o.all ? html`<div class="off" style="top:0;height:${24 * HOUR}px"></div>`
                : html`<div class="off" style="top:0;height:${o.start * HOUR}px"></div><div class="off" style="top:${o.end * HOUR}px;height:${(24 - o.end) * HOUR}px"></div>`) : nothing}
              ${hours.map(h => html`<div class="line" style="top:${h * HOUR}px"></div><div class="half" style="top:${h * HOUR + HOUR / 2}px"></div>`)}
              ${isToday(d) ? html`<div class="now" style="top:${this.nowTop()}px"><span></span></div>` : nothing}
            </div>`; })}
          <div class="layer" style="grid-template-columns:${cols}"><div></div>${this.days.map((_, i) => html`<div class="lcol">${this.bands(i)}</div>`)}</div>
          <div class="layer" style="grid-template-columns:${cols}"><div></div>${this.days.map((_, i) => html`<div class="lcol">${this.blocks(i)}</div>`)}</div>
          ${this.ghost()}
        </div>
      </div>`;
  }
}

/** Side-by-side columns for overlapping blocks (Google-like). */
export function layoutColumns(list: Placed[]) {
  list.sort((a, b) => a.top - b.top || b.height - a.height);
  let cluster: Placed[] = [];
  let clusterEnd = -1;
  const flush = () => {
    const colsEnd: number[] = [];
    for (const p of cluster) {
      let c = colsEnd.findIndex(end => end <= p.top + 0.5);
      if (c < 0) { c = colsEnd.length; colsEnd.push(0); }
      colsEnd[c] = p.top + p.height;
      p.col = c;
    }
    for (const p of cluster) p.cols = colsEnd.length;
    cluster = [];
  };
  for (const p of list) {
    if (cluster.length && p.top >= clusterEnd) { flush(); clusterEnd = -1; }
    cluster.push(p);
    clusterEnd = Math.max(clusterEnd, p.top + p.height);
  }
  if (cluster.length) flush();
}

/** Overlapping windows get a small left offset so all stay visible. */
function layoutLanes(list: Band[]) {
  list.sort((a, b) => a.top - b.top);
  const lanesEnd: number[] = [];
  for (const b of list) {
    let l = lanesEnd.findIndex(end => end <= b.top);
    if (l < 0) { l = lanesEnd.length; lanesEnd.push(0); }
    lanesEnd[l] = b.top + b.height;
    b.lane = l;
  }
}
