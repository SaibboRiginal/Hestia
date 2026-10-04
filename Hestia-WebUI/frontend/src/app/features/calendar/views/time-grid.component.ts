import {
  AfterViewInit, ChangeDetectionStrategy, Component, ElementRef, OnDestroy, computed, input, output, signal, viewChild,
} from '@angular/core';
import { CalEvent, TYPE_META } from '../calendar.models';
import { DAY_MS, addDays, addMinutes, fmt, isSameDay, isToday, minutesOfDay, snap, startOfDay } from '../date-utils';
import { FrequentMode, WindowsMode } from '../calendar.prefs';
import { IconComponent } from '../../../ui';

const HOUR_PX = 48;
const MIN_BLOCK_MIN = 22;            // instants and very short items still get a clickable block
const SNAP_MIN = 15;
const LANE_PX = 10;                  // window lane width (strip 7px + gap)

interface Placed { ev: CalEvent; dayIdx: number; top: number; height: number; col: number; cols: number; instant: boolean; segStart: Date; segEnd: Date; }
interface Band { ev: CalEvent; dayIdx: number; top: number; height: number; lane: number; segStart: Date; segEnd: Date; }
export interface MoveRequest { ev: CalEvent; start: Date; end: Date | null; }
export interface SelectRequest { ev: CalEvent; rect: DOMRect; }

interface DragState {
  ev: CalEvent; mode: 'move' | 'resize'; startX: number; startY: number; moved: boolean;
  dayDelta: number; minDelta: number; colWidth: number; target: HTMLElement;
}

/**
 * Week (7 days) / day (1 day) time grid.
 * - windows (type=window): 'lane' = clickable strip at the column's left edge spanning exactly the window
 *   hours + "01:00–07:00" label + faint tint across the column; 'band' = full-width translucent band
 * - frequent rules in 'compact' mode → one summary chip per rule per day in the top "Ricorrenti" row
 *   (failed runs always stay as their own blocks)
 * - drag a block to move (15-min snap, across days), drag its bottom edge to resize
 * - click an empty slot → (createAt) ; click a block → (selected)
 */
@Component({
  selector: 'cal-time-grid',
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="head" [style.grid-template-columns]="cols()">
      <div class="gutter-h"></div>
      @for (d of days(); track d.getTime(); let i = $index) {
        <button class="dh" [class.today]="isToday(d)" [class.sel]="days().length > 1 && isSameDay(d, focusDay())"
                (click)="dayClick.emit(d)" [attr.title]="'Apri ' + longDay(d)">
          <span class="wd">{{ weekday(d) }}</span><span class="dn">{{ d.getDate() }}</span>
        </button>
      }
    </div>
    @if (hasSummary()) {
      <div class="sum" [style.grid-template-columns]="cols()">
        <div class="sum-h" title="Attività che si ripetono spesso, raggruppate (Vista → Ricorrenze frequenti)">Ricorrenti</div>
        @for (d of days(); track d.getTime(); let i = $index) {
          <div class="sum-c">
            @for (g of summaryFor(i); track g.id) {
              <button class="schip" [style.--c]="g.color" [class.paused]="g.occ.status === 'paused'"
                      (click)="selected.emit({ ev: g, rect: $any($event.currentTarget).getBoundingClientRect() })"
                      [attr.title]="g.occ.title + ' · ' + g.group!.length + ' volte: ' + groupRange(g)">
                <span class="dot"></span><span class="hx-truncate">{{ g.occ.title }}</span><span class="x">×{{ g.group!.length }}</span>
              </button>
            }
          </div>
        }
      </div>
    }
    <div class="scroll" #scroller (scroll)="scrollTop.set($any($event.target).scrollTop)">
      <div class="grid" [style.grid-template-columns]="cols()" [style.height.px]="24 * HOUR">
        <div class="gutter">
          @for (h of hours; track h) { <div class="hl" [style.top.px]="h * HOUR"><span>{{ h ? pad(h) + ':00' : '' }}</span></div> }
        </div>
        @for (d of days(); track d.getTime(); let i = $index) {
          <div class="col" [class.today]="isToday(d)" (click)="slotClick($event, d)">
            @if (offHours(d); as o) {
              @if (o.all) { <div class="off" [style.top.px]="0" [style.height.px]="24 * HOUR"></div> }
              @else {
                <div class="off" [style.top.px]="0" [style.height.px]="o.start * HOUR"></div>
                <div class="off" [style.top.px]="o.end * HOUR" [style.height.px]="(24 - o.end) * HOUR"></div>
              }
            }
            @for (h of hours; track h) { <div class="line" [style.top.px]="h * HOUR"></div><div class="half" [style.top.px]="h * HOUR + HOUR / 2"></div> }
            @if (isToday(d)) { <div class="now" [style.top.px]="nowTop()"><span></span></div> }
          </div>
        }
        <!-- bands (windows) -->
        <div class="layer" [style.grid-template-columns]="cols()">
          <div></div>
          @for (d of days(); track d.getTime(); let i = $index) {
            <div class="lcol">
              @for (b of bandsFor(i); track b.ev.id + b.segStart.getTime()) {
                @if (windowsMode() === 'lane') {
                  <div class="tint" [style.top.px]="b.top" [style.height.px]="b.height" [style.--c]="b.ev.color"></div>
                  <div class="lane" [style.top.px]="b.top" [style.height.px]="b.height" [style.left.px]="b.lane * LANE"
                       [style.--c]="b.ev.color" [class.skipped]="b.ev.occ.skipped" [class.paused]="b.ev.occ.status === 'paused'"
                       [class.dragging]="drag()?.ev?.id === b.ev.id"
                       (pointerdown)="startDrag($event, b.ev, 'move')" (click)="$event.stopPropagation()"
                       [attr.title]="'Finestra · ' + b.ev.occ.title + ' · ' + time(b.ev)">
                    <div class="rz" (pointerdown)="startDrag($event, b.ev, 'resize')"></div>
                  </div>
                  <div class="lane-label" [style.top.px]="labelTop(b)" [style.left.px]="laneCount(i) * LANE + 2" [style.--c]="b.ev.color"
                       [class.paused]="b.ev.occ.status === 'paused'"
                       (pointerdown)="startDrag($event, b.ev, 'move')" (click)="$event.stopPropagation()">
                    <b>{{ segTime(b) }}</b> {{ b.ev.occ.title }}
                  </div>
                } @else {
                  <div class="band" [style.top.px]="b.top" [style.height.px]="b.height" [style.left.px]="b.lane * 6"
                       [style.--c]="b.ev.color" [class.skipped]="b.ev.occ.skipped" [class.paused]="b.ev.occ.status === 'paused'"
                       [class.dragging]="drag()?.ev?.id === b.ev.id"
                       (pointerdown)="startDrag($event, b.ev, 'move')" (click)="$event.stopPropagation()"
                       [attr.title]="b.ev.occ.title + ' — ' + time(b.ev)">
                    <div class="band-label"><hx-icon name="window" [size]="12" /><b>{{ segTime(b) }}</b>&nbsp;{{ b.ev.occ.title }}</div>
                    <div class="rz" (pointerdown)="startDrag($event, b.ev, 'resize')"></div>
                  </div>
                }
              }
            </div>
          }
        </div>
        <!-- blocks -->
        <div class="layer blocks" [style.grid-template-columns]="cols()">
          <div></div>
          @for (d of days(); track d.getTime(); let i = $index) {
            <div class="lcol">
              @for (p of placedFor(i); track p.ev.id + p.segStart.getTime()) {
                <div class="blk" [class.instant]="p.instant" [class.skipped]="p.ev.occ.skipped"
                     [class.done]="p.ev.occ.status === 'completed' || p.ev.occ.status === 'cancelled'"
                     [class.paused]="p.ev.occ.status === 'paused'" [class.moved]="p.ev.occ.moved"
                     [class.failed]="p.ev.occ.run?.ok === false"
                     [class.dragging]="drag()?.ev?.id === p.ev.id"
                     [style.top.px]="p.top" [style.height.px]="p.height"
                     [style.left]="'calc(' + off(i) + 'px + (100% - ' + off(i) + 'px) * ' + (p.col / p.cols) + ' + 2px)'"
                     [style.width]="'calc((100% - ' + off(i) + 'px) / ' + p.cols + ' - 4px)'" [style.--c]="p.ev.color"
                     (pointerdown)="startDrag($event, p.ev, 'move')" (click)="$event.stopPropagation()">
                  <div class="bt"><hx-icon [name]="p.ev.occ.run?.ok === false ? 'alert' : icon(p.ev)" [size]="12" />
                    <span class="hx-truncate">{{ p.ev.occ.title }}</span>
                    @if ((p.ev.failedCount ?? 0) > 1) { <span class="fx">×{{ p.ev.failedCount }}</span> }</div>
                  @if (p.height > 34) { <div class="bm">{{ time(p.ev) }}</div> }
                  @if (!p.instant) { <div class="rz" (pointerdown)="startDrag($event, p.ev, 'resize')"></div> }
                </div>
              }
            </div>
          }
        </div>
        @if (ghost(); as g) {
          <div class="ghost" [style.top.px]="g.top" [style.height.px]="g.height"
               [style.left]="'calc(56px + (100% - 56px) / ' + days().length + ' * ' + g.dayIdx + ' + 2px)'"
               [style.width]="'calc((100% - 56px) / ' + days().length + ' - 4px)'">
            {{ g.label }}
          </div>
        }
      </div>
    </div>
  `,
  styles: [`
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
    .scroll { flex: 1; overflow-y: auto; overflow-x: hidden; position: relative; }
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
    .blk.failed hx-icon { color: var(--danger); }
    .blk.dragging, .band.dragging, .lane.dragging { opacity: .35; }
    .rz { position: absolute; left: 0; right: 0; bottom: 0; height: 7px; cursor: ns-resize; }
    .ghost { position: absolute; z-index: 10; pointer-events: none; border: 2px dashed var(--accent); border-radius: var(--radius-sm);
             background: var(--accent-soft); color: var(--accent); font-size: 11.5px; font-weight: 600; padding: 3px 6px; }
  `],
})
export class TimeGridComponent implements AfterViewInit, OnDestroy {
  readonly HOUR = HOUR_PX;
  readonly LANE = LANE_PX;
  readonly hours = Array.from({ length: 24 }, (_, i) => i);
  days = input.required<Date[]>();
  events = input.required<CalEvent[]>();
  selected = output<SelectRequest>();
  createAt = output<Date>();
  moved = output<MoveRequest>();
  dayClick = output<Date>();
  windowsMode = input<WindowsMode>('lane');
  frequentMode = input<FrequentMode>('compact');
  focusDay = input<Date>(new Date());
  scrollHour = input(7);
  /** Working hours [start, end) Mon–Fri; outside is shaded (weekends fully). end <= start = no shading. */
  workHours = input<[number, number]>([9, 18]);
  private scroller = viewChild<ElementRef<HTMLElement>>('scroller');

  readonly drag = signal<DragState | null>(null);
  readonly nowTick = signal(Date.now());
  /** Window labels stick to the top of the viewport while their window is on screen. */
  readonly scrollTop = signal(0);
  labelTop(b: Band) { return Math.min(Math.max(b.top, this.scrollTop() + 2), Math.max(b.top, b.top + b.height - 17)); }
  private timer: ReturnType<typeof setInterval> | null = null;

  offHours(d: Date): { all: boolean; start: number; end: number } | null {
    const [s, e] = this.workHours();
    if (!(e > s)) return null;
    const wd = d.getDay();
    return { all: wd === 0 || wd === 6, start: Math.max(0, s), end: Math.min(24, e) };
  }

  cols = computed(() => `56px repeat(${this.days().length}, minmax(0, 1fr))`);
  nowTop = computed(() => { this.nowTick(); return minutesOfDay(new Date()) / 60 * HOUR_PX; });

  /** Per-day segments, windows split from blocks. */
  private segments = computed(() => {
    const days = this.days();
    const bands: Band[][] = days.map(() => []);
    const blocks: Placed[][] = days.map(() => []);
    const summary: CalEvent[][] = days.map(() => []);
    const compact = this.frequentMode() === 'compact';
    for (const ev of this.events()) {
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
        const top = minutesOfDay(segStart) / 60 * HOUR_PX;
        const rawH = ((segEnd.getTime() - segStart.getTime()) / 60000) / 60 * HOUR_PX;
        if (ev.occ.type === 'window') {
          bands[i].push({ ev, dayIdx: i, top, height: Math.max(rawH, 18), lane: 0, segStart, segEnd });
        } else {
          blocks[i].push({ ev, dayIdx: i, top, height: Math.max(rawH, MIN_BLOCK_MIN / 60 * HOUR_PX), col: 0, cols: 1,
                           instant: !ev.end, segStart, segEnd });
        }
      });
    }
    bands.forEach(list => layoutLanes(list));
    blocks.forEach(list => layoutColumns(list));
    const lanes = bands.map(list => this.windowsMode() === 'lane' && list.length ? Math.max(...list.map(b => b.lane)) + 1 : 0);
    // one summary chip per rule per day
    const groups = summary.map((list, i) => {
      const byKey = new Map<string, CalEvent[]>();
      for (const ev of list) (byKey.get(ev.occ.key) ?? byKey.set(ev.occ.key, []).get(ev.occ.key)!).push(ev);
      return [...byKey.values()].map(g => {
        g.sort((a, b) => a.start.getTime() - b.start.getTime());
        return { ...g[0], id: `${g[0].occ.key}|sum|${i}`, group: g } as CalEvent;
      });
    });
    return { bands, blocks, lanes, groups };
  });

  bandsFor(i: number) { return this.segments().bands[i]; }
  placedFor(i: number) { return this.segments().blocks[i]; }
  summaryFor(i: number) { return this.segments().groups[i]; }
  hasSummary = computed(() => this.segments().groups.some(g => g.length));
  laneCount(i: number) { return this.segments().lanes[i]; }
  /** Left offset of blocks so window lanes stay clickable. */
  off(i: number) { return this.laneCount(i) * LANE_PX; }
  segTime = (b: Band) => `${fmt.time(b.ev.start)}–${b.ev.end ? fmt.time(b.ev.end) : ''}`;
  groupRange = (g: CalEvent) => { const l = g.group ?? [g]; return `${fmt.time(l[0].start)}–${fmt.time(l[l.length - 1].start)}`; };
  longDay = (d: Date) => fmt.dayLong(d);
  isSameDay = isSameDay;

  /** Drag preview. */
  ghost = computed(() => {
    const d = this.drag();
    if (!d || !d.moved) return null;
    const { start, end } = this.preview(d);
    const dayIdx = this.days().findIndex(x => startOfDay(x).getTime() === startOfDay(start).getTime());
    if (dayIdx < 0) return null;
    const top = minutesOfDay(start) / 60 * HOUR_PX;
    const e = end ?? addMinutes(start, MIN_BLOCK_MIN);
    const height = Math.max(18, (e.getTime() - start.getTime()) / 3600000 * HOUR_PX);
    return { dayIdx, top, height, label: `${fmt.time(start)}${end ? ' – ' + fmt.time(end) : ''}` };
  });

  ngAfterViewInit() {
    const el = this.scroller()?.nativeElement;
    if (el) {
      const target = this.days().some(isToday) ? Math.max(0, this.nowTop() - 160) : this.scrollHour() * HOUR_PX;
      el.scrollTop = target;
      this.scrollTop.set(el.scrollTop);
    }
    this.timer = setInterval(() => this.nowTick.set(Date.now()), 60_000);
  }

  ngOnDestroy() {
    if (this.timer) clearInterval(this.timer);
    this.detach();
  }

  // ── helpers for template ───────────────────────────────────────────────
  isToday = isToday;
  pad = (n: number) => String(n).padStart(2, '0');
  weekday = (d: Date) => fmt.weekdayShort(d);
  icon = (ev: CalEvent) => TYPE_META[ev.occ.type]?.icon ?? 'event';
  time = (ev: CalEvent) => `${fmt.time(ev.start)}${ev.end ? ' – ' + fmt.time(ev.end) : ''}`;

  slotClick(e: MouseEvent, day: Date) {
    if (this.justDragged) { this.justDragged = false; return; }
    const col = e.currentTarget as HTMLElement;
    const y = e.clientY - col.getBoundingClientRect().top;
    const minutes = Math.floor((y / HOUR_PX * 60) / 30) * 30;
    this.createAt.emit(addMinutes(startOfDay(day), minutes));
  }

  // ── drag & drop (pointer events) ───────────────────────────────────────
  private justDragged = false;
  private onMove = (e: PointerEvent) => this.dragMove(e);
  private onUp = (e: PointerEvent) => this.dragEnd(e);

  startDrag(e: PointerEvent, ev: CalEvent, mode: 'move' | 'resize') {
    if (e.button !== 0) return;
    e.stopPropagation();
    if (mode === 'resize' && !ev.end) return;
    const grid = this.scroller()?.nativeElement.querySelector('.grid') as HTMLElement | null;
    const colWidth = grid ? (grid.clientWidth - 56) / this.days().length : 100;
    this.drag.set({ ev, mode, startX: e.clientX, startY: e.clientY, moved: false, dayDelta: 0, minDelta: 0, colWidth,
                    target: e.currentTarget as HTMLElement });
    window.addEventListener('pointermove', this.onMove);
    window.addEventListener('pointerup', this.onUp, { once: true });
  }

  private dragMove(e: PointerEvent) {
    const d = this.drag();
    if (!d) return;
    const dx = e.clientX - d.startX, dy = e.clientY - d.startY;
    const moved = d.moved || Math.abs(dx) > 4 || Math.abs(dy) > 4;
    const minDelta = Math.round((dy / HOUR_PX * 60) / SNAP_MIN) * SNAP_MIN;
    const dayDelta = d.mode === 'move' ? Math.round(dx / d.colWidth) : 0;
    if (moved !== d.moved || minDelta !== d.minDelta || dayDelta !== d.dayDelta) this.drag.set({ ...d, moved, minDelta, dayDelta });
  }

  private dragEnd(_e: PointerEvent) {
    const d = this.drag();
    this.detach();
    this.drag.set(null);
    if (!d) return;
    if (!d.moved) {
      this.selected.emit({ ev: d.ev, rect: d.target.getBoundingClientRect() });
      return;
    }
    this.justDragged = true;
    setTimeout(() => (this.justDragged = false), 50);
    const { start, end } = this.preview(d);
    if (start.getTime() === d.ev.start.getTime() && (end?.getTime() ?? 0) === (d.ev.end?.getTime() ?? 0)) return;
    this.moved.emit({ ev: d.ev, start, end });
  }

  private preview(d: DragState): { start: Date; end: Date | null } {
    if (d.mode === 'resize' && d.ev.end) {
      const end = snap(addMinutes(d.ev.end, d.minDelta), SNAP_MIN);
      return { start: d.ev.start, end: end > addMinutes(d.ev.start, SNAP_MIN) ? end : addMinutes(d.ev.start, SNAP_MIN) };
    }
    const start = addDays(addMinutes(d.ev.start, d.minDelta), d.dayDelta);
    const end = d.ev.end ? new Date(d.ev.end.getTime() + (start.getTime() - d.ev.start.getTime())) : null;
    return { start, end };
  }

  private detach() {
    window.removeEventListener('pointermove', this.onMove);
    window.removeEventListener('pointerup', this.onUp);
  }
}

/** Side-by-side columns for overlapping blocks (Google-like). */
function layoutColumns(list: Placed[]) {
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
