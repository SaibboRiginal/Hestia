import { ChangeDetectionStrategy, Component, computed, input, output, signal } from '@angular/core';
import { CalEvent, TYPE_META } from '../calendar.models';
import { DAY_MS, addDays, dayKey, fmt, isSameDay, isToday, monthGrid, startOfDay } from '../date-utils';

import { MoveRequest, SelectRequest } from './time-grid.component';

const MAX_CHIPS = 3;
const WD = ['Lun', 'Mar', 'Mer', 'Gio', 'Ven', 'Sab', 'Dom'];

/** Month grid: chips per day (windows first, as thin bars), "+N altri", drag a chip to another day. */
@Component({
  selector: 'cal-month-view',
  imports: [],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="wds">@for (w of wd; track w) { <div>{{ w }}</div> }</div>
    <div class="grid">
      @for (d of cells(); track d.getTime()) {
        <div class="cell" [class.out]="d.getMonth() !== anchor().getMonth()" [class.today]="isToday(d)"
             [class.sel]="isSameDay(d, anchor())"
             [class.drop]="dropKey() === key(d)"
             (click)="createAt.emit(at9(d))"
             (dragover)="$event.preventDefault(); dropKey.set(key(d))" (dragleave)="dropKey.set(null)"
             (drop)="onDrop($event, d)">
          <button class="num" (click)="$event.stopPropagation(); dayClick.emit(d)" title="Apri il giorno">{{ d.getDate() }}</button>
          @if (windows(d).length) {
            <div class="wins">
              @for (w of windows(d); track w.id) {
                <span class="win" [style.--c]="w.color" [class.skipped]="w.occ.skipped" [class.paused]="w.occ.status === 'paused'"
                      [attr.title]="'Finestra ' + time(w) + (w.end ? '–' + endTime(w) : '') + ' · ' + w.occ.title"
                      (click)="$event.stopPropagation(); selected.emit({ ev: w, rect: $any($event.currentTarget).getBoundingClientRect() })"></span>
              }
            </div>
          }
          <div class="chips">
            @for (g of visible(d); track g.ev.id) {
              @let ev = g.ev;
              <div class="chip" [class.skipped]="ev.occ.skipped" [class.failed]="ev.occ.run?.ok === false"
                   [class.done]="ev.occ.status === 'completed' || ev.occ.status === 'cancelled'"
                   [class.paused]="ev.occ.status === 'paused'" [style.--c]="ev.color"
                   draggable="true" (dragstart)="onDragStart($event, ev)" (dragend)="dropKey.set(null)"
                   (click)="$event.stopPropagation(); selected.emit({ ev, rect: $any($event.currentTarget).getBoundingClientRect() })"
                   [attr.title]="ev.occ.title + (g.count > 1 ? ' (' + g.count + ' volte oggi)' : '')">
                <span class="dot"></span>
                <span class="t">{{ time(ev) }}</span>
                <span class="hx-truncate">{{ ev.occ.title }}</span>
                @if (g.count > 1) { <span class="x">×{{ g.count }}</span> }
                @else if ((ev.failedCount ?? 0) > 1) { <span class="x">fallito ×{{ ev.failedCount }}</span> }
              </div>
            }
            @if (hidden(d) > 0) {
              <button class="more" (click)="$event.stopPropagation(); dayClick.emit(d)">+{{ hidden(d) }} altri</button>
            }
          </div>
        </div>
      }
    </div>
  `,
  styles: [`
    :host { display: flex; flex-direction: column; flex: 1; min-height: 0; }
    .wds { display: grid; grid-template-columns: repeat(7, 1fr); border-bottom: 1px solid var(--border); }
    .wds div { padding: 8px 10px; font-size: 11.5px; color: var(--text-3); text-transform: uppercase; letter-spacing: .04em; }
    .grid { flex: 1; display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); grid-template-rows: repeat(6, minmax(0, 1fr)); min-height: 0; }
    .cell { border-right: 1px solid var(--border); border-bottom: 1px solid var(--border); padding: 4px; min-height: 0; overflow: hidden;
            display: flex; flex-direction: column; gap: 2px; cursor: cell; }
    .cell:nth-child(7n) { border-right: 0; }
    .cell.out { background: color-mix(in srgb, var(--surface-2) 40%, transparent); }
    .cell.out .num { color: var(--text-3); }
    .cell.drop { background: var(--accent-soft); }
    .num { align-self: flex-start; width: 26px; height: 26px; border-radius: 50%; font-size: 12.5px; color: var(--text-2); }
    .num:hover { background: var(--surface-2); }
    .today .num { background: var(--accent); color: var(--accent-contrast); font-weight: 600; }
    .cell.sel { box-shadow: inset 0 0 0 2px var(--accent); }
    .chip.failed { color: var(--danger); } .chip.failed .dot { background: var(--danger); }
    .chips { display: flex; flex-direction: column; gap: 2px; min-height: 0; }
    .chip { display: flex; align-items: center; gap: 5px; font-size: 11.5px; padding: 1px 6px; border-radius: var(--radius-xs, 4px);
            cursor: pointer; color: var(--text); min-width: 0; }
    .chip:hover { background: var(--surface-2); }
    .wins { display: flex; flex-direction: column; gap: 2px; padding: 0 2px 2px; }
    .win { display: block; height: 4px; border-radius: 2px; background: color-mix(in srgb, var(--c) 55%, transparent); cursor: pointer; }
    .win:hover { height: 6px; background: var(--c); }
    .win.skipped { background: repeating-linear-gradient(90deg, var(--c) 0 4px, transparent 4px 7px); opacity: .6; }
    .win.paused { filter: grayscale(1); opacity: .5; }
    .x { margin-left: auto; font-size: 10.5px; color: var(--text-3); flex-shrink: 0; padding-left: 4px; }
    .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--c); flex-shrink: 0; }
    .t { color: var(--text-3); flex-shrink: 0; }
    .chip.skipped { text-decoration: line-through; opacity: .55; }
    .chip.done { opacity: .55; }
    .chip.paused { filter: grayscale(.8); }
    .more { font-size: 11.5px; color: var(--text-2); text-align: left; padding: 1px 6px; border-radius: 4px; font-weight: 500; }
    .more:hover { background: var(--surface-2); }
  `],
})
export class MonthViewComponent {
  readonly wd = WD;
  anchor = input.required<Date>();
  events = input.required<CalEvent[]>();
  selected = output<SelectRequest>();
  createAt = output<Date>();
  moved = output<MoveRequest>();
  dayClick = output<Date>();
  dropKey = signal<string | null>(null);
  private dragged: CalEvent | null = null;

  cells = computed(() => monthGrid(this.anchor()));

  /** day key → events overlapping that day (windows first, then by time). */
  private byDay = computed(() => {
    const map = new Map<string, CalEvent[]>();
    const cells = this.cells();
    const first = cells[0], last = addDays(cells[41], 1);
    for (const ev of this.events()) {
      const end = ev.end ?? ev.start;
      let d = startOfDay(ev.start < first ? first : ev.start);
      while (d < last && d.getTime() <= end.getTime()) {
        const k = dayKey(d);
        // a window ending exactly at midnight does not belong to the next day
        if (!(ev.end && ev.end.getTime() === d.getTime() && ev.start < d)) (map.get(k) ?? map.set(k, []).get(k)!).push(ev);
        d = new Date(d.getTime() + DAY_MS);
        if (!ev.end) break;
      }
    }
    for (const list of map.values()) {
      list.sort((a, b) => (a.occ.type === 'window' ? 0 : 1) - (b.occ.type === 'window' ? 0 : 1) || a.start.getTime() - b.start.getTime());
    }
    return map;
  });

  /** Windows → thin bars; other items grouped by rule (same key on the same day → one chip ×N). */
  private split = computed(() => {
    const out = new Map<string, { wins: CalEvent[]; groups: { ev: CalEvent; count: number }[] }>();
    for (const [k, list] of this.byDay()) {
      const wins: CalEvent[] = [];
      const byKey = new Map<string, { ev: CalEvent; count: number }>();
      for (const ev of list) {
        if (ev.occ.type === 'window') { wins.push(ev); continue; }
        const g = byKey.get(ev.occ.key);
        g ? g.count++ : byKey.set(ev.occ.key, { ev, count: 1 });
      }
      out.set(k, { wins: wins.slice(0, 5), groups: [...byKey.values()] });
    }
    return out;
  });
  windows(d: Date) { return this.split().get(dayKey(d))?.wins ?? []; }
  visible(d: Date) { return (this.split().get(dayKey(d))?.groups ?? []).slice(0, MAX_CHIPS); }
  hidden(d: Date) { return Math.max(0, (this.split().get(dayKey(d))?.groups.length ?? 0) - MAX_CHIPS); }
  endTime = (ev: CalEvent) => ev.end ? fmt.time(ev.end) : '';
  key = dayKey;
  isToday = isToday;
  isSameDay = isSameDay;
  time = (ev: CalEvent) => fmt.time(ev.start);
  icon = (ev: CalEvent) => TYPE_META[ev.occ.type]?.icon ?? 'event';
  at9 = (d: Date) => { const x = startOfDay(d); x.setHours(9); return x; };

  onDragStart(e: DragEvent, ev: CalEvent) {
    this.dragged = ev;
    e.dataTransfer?.setData('text/plain', ev.id);
    if (e.dataTransfer) e.dataTransfer.effectAllowed = 'move';
  }

  onDrop(e: DragEvent, day: Date) {
    e.preventDefault();
    this.dropKey.set(null);
    const ev = this.dragged;
    this.dragged = null;
    if (!ev) return;
    const days = Math.round((startOfDay(day).getTime() - startOfDay(ev.start).getTime()) / DAY_MS);
    if (!days) return;
    const start = addDays(ev.start, days);
    const end = ev.end ? addDays(ev.end, days) : null;
    this.moved.emit({ ev, start, end });
  }
}
