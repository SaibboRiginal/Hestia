import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { CalEvent, STATUS_META, TYPE_META, ownerLabel } from '../calendar.models';
import { dayKey, fmt, isToday } from '../date-utils';
import { describeRRule } from '../rrule';
import { BadgeComponent, EmptyStateComponent, IconComponent } from '../../../ui';
import { SelectRequest } from './time-grid.component';

/** Agenda list grouped by day (next 31 days from the anchor). */
@Component({
  selector: 'cal-list-view',
  imports: [IconComponent, BadgeComponent, EmptyStateComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (groups().length === 0) {
      <hx-empty icon="calendar" title="Niente in programma">Nessuna voce nel periodo con i filtri attuali.</hx-empty>
    }
    @for (g of groups(); track g.key) {
      <section>
        <h3 [class.today]="g.today">{{ g.label }}</h3>
        @for (ev of g.events; track ev.id) {
          <button class="row" [class.skipped]="ev.occ.skipped" [class.done]="ev.occ.status === 'completed' || ev.occ.status === 'cancelled'"
                  (click)="selected.emit({ ev, rect: $any($event.currentTarget).getBoundingClientRect() })">
            <span class="time">{{ time(ev) }}</span>
            <span class="bar" [style.background]="ev.color"></span>
            <span class="main">
              <span class="title"><hx-icon [name]="icon(ev)" [size]="14" /> {{ ev.occ.title }}</span>
              <span class="meta">{{ owner(ev) }} · {{ typeLabel(ev) }}@if (ev.occ.recurring) { · {{ rule(ev) }} }</span>
            </span>
            @if (ev.occ.skipped) { <hx-badge>saltata</hx-badge> }
            @else if (ev.occ.moved) { <hx-badge tone="info">spostata</hx-badge> }
            @else if (ev.occ.status && ev.occ.status !== 'confirmed') { <hx-badge [tone]="status(ev).tone">{{ status(ev).label }}</hx-badge> }
          </button>
        }
      </section>
    }
  `,
  styles: [`
    :host { display: block; overflow-y: auto; flex: 1; padding: 8px 24px 40px; }
    section { max-width: 920px; margin: 0 auto 18px; }
    h3 { font-size: 13px; font-weight: 600; color: var(--text-2); padding: 10px 4px 6px; position: sticky; top: 0; background: var(--bg); z-index: 1; }
    h3.today { color: var(--accent); }
    .row { width: 100%; display: flex; align-items: center; gap: 12px; padding: 9px 10px; border-radius: var(--radius-md); text-align: left; }
    .row:hover { background: var(--surface-2); }
    .time { width: 104px; flex-shrink: 0; font-size: 12.5px; color: var(--text-2); font-variant-numeric: tabular-nums; }
    .bar { width: 4px; align-self: stretch; border-radius: 2px; flex-shrink: 0; }
    .main { flex: 1; min-width: 0; display: flex; flex-direction: column; }
    .title { font-size: 14px; display: flex; align-items: center; gap: 6px; color: var(--text); }
    .meta { font-size: 12px; color: var(--text-3); }
    .row.skipped .title { text-decoration: line-through; }
    .row.skipped, .row.done { opacity: .6; }
    @media (max-width: 720px) { :host { padding: 6px 10px 30px; } .time { width: 76px; } }
  `],
})
export class ListViewComponent {
  events = input.required<CalEvent[]>();
  selected = output<SelectRequest>();

  groups = computed(() => {
    const map = new Map<string, { key: string; label: string; today: boolean; events: CalEvent[] }>();
    for (const ev of [...this.events()].sort((a, b) => a.start.getTime() - b.start.getTime())) {
      const k = dayKey(ev.start);
      if (!map.has(k)) map.set(k, { key: k, label: fmt.dayLong(ev.start), today: isToday(ev.start), events: [] });
      map.get(k)!.events.push(ev);
    }
    return [...map.values()];
  });

  time = (ev: CalEvent) => `${fmt.time(ev.start)}${ev.end ? ' – ' + fmt.time(ev.end) : ''}`;
  icon = (ev: CalEvent) => TYPE_META[ev.occ.type]?.icon ?? 'event';
  typeLabel = (ev: CalEvent) => TYPE_META[ev.occ.type]?.label ?? ev.occ.type;
  owner = (ev: CalEvent) => ownerLabel(ev.occ.owner);
  rule = (ev: CalEvent) => describeRRule(ev.item?.recurrence);
  status = (ev: CalEvent) => STATUS_META[ev.occ.status ?? 'confirmed'] ?? STATUS_META.confirmed;
}
