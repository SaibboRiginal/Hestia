import { ChangeDetectionStrategy, Component, computed, effect, input, output, signal } from '@angular/core';
import { addMonths, dayKey, fmt, isSameDay, isToday, monthGrid } from './date-utils';
import { IconComponent } from '../../ui';

/** Small month navigator for the sidebar. Highlights today, the selected day and days with items. */
@Component({
  selector: 'cal-mini',
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="hd">
      <span>{{ title() }}</span>
      <button (click)="shift(-1)" aria-label="Mese precedente"><hx-icon name="chevron-left" [size]="15" /></button>
      <button (click)="shift(1)" aria-label="Mese successivo"><hx-icon name="chevron-right" [size]="15" /></button>
    </div>
    <div class="grid">
      @for (w of wd; track $index) { <span class="wd">{{ w }}</span> }
      @for (d of cells(); track d.getTime()) {
        <button class="d" [class.out]="d.getMonth() !== month().getMonth()" [class.today]="isToday(d)"
                [class.sel]="isSameDay(d, selected())" (click)="pick.emit(d)">
          {{ d.getDate() }}
          @if (marked().has(key(d))) { <i></i> }
        </button>
      }
    </div>`,
  styles: [`
    :host { display: block; }
    .hd { display: flex; align-items: center; gap: 2px; padding: 0 2px 6px 6px; font-size: 13px; font-weight: 600; }
    .hd span { flex: 1; }
    .hd button { width: 26px; height: 26px; display: grid; place-items: center; border-radius: var(--radius-sm); color: var(--text-3); }
    .hd button:hover { background: var(--surface-2); color: var(--text); }
    .grid { display: grid; grid-template-columns: repeat(7, 1fr); gap: 1px; }
    .wd { font-size: 10.5px; color: var(--text-3); text-align: center; padding: 2px 0; }
    .d { position: relative; height: 28px; border-radius: 50%; font-size: 12px; color: var(--text-2); }
    .d:hover { background: var(--surface-2); }
    .d.out { color: var(--text-3); opacity: .6; }
    .d.today { color: var(--accent); font-weight: 700; }
    .d.sel { background: var(--accent); color: var(--accent-contrast); }
    .d i { position: absolute; bottom: 3px; left: 50%; width: 4px; height: 4px; margin-left: -2px; border-radius: 50%; background: var(--accent); }
    .d.sel i { background: var(--accent-contrast); }
  `],
})
export class MiniCalendarComponent {
  readonly wd = ['L', 'M', 'M', 'G', 'V', 'S', 'D'];
  selected = input.required<Date>();
  marked = input<Set<string>>(new Set());
  pick = output<Date>();
  month = signal(new Date());
  cells = computed(() => monthGrid(this.month()));
  title = computed(() => fmt.monthYear(this.month()));
  isToday = isToday;
  isSameDay = isSameDay;
  key = dayKey;

  constructor() {
    effect(() => this.month.set(new Date(this.selected())), { allowSignalWrites: true });
  }

  shift(n: number) { this.month.set(addMonths(this.month(), n)); }
}
