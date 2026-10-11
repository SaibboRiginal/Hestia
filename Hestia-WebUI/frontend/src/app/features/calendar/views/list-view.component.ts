import { NgTemplateOutlet } from '@angular/common';
import { ChangeDetectionStrategy, Component, DestroyRef, ElementRef, computed, effect, inject, input, output, signal, viewChild } from '@angular/core';
import { CalEvent, STATUS_META, TYPE_META, ownerLabel } from '../calendar.models';
import { dayKey, fmt, isSameDay, isToday } from '../date-utils';
import { describeRRule } from '../rrule';
import { BadgeComponent, EmptyStateComponent, IconComponent } from '../../../ui';
import { SelectRequest } from './time-grid.component';

type Tone = 'neutral' | 'success' | 'warning' | 'danger' | 'info' | 'accent';
interface Outcome { label: string; tone: Tone; detail?: string; }
interface Group { key: string; label: string; today: boolean; events: CalEvent[]; nowBefore: boolean; nowAt: string | null; nowAfter: boolean; }

/**
 * Agenda list grouped by day (31 days from the anchor). A "Adesso" divider marks the current time
 * (the list scrolls to it); past rows show the outcome of their run (ok / fallito + detail).
 */
@Component({
  selector: 'cal-list-view',
  imports: [NgTemplateOutlet, IconComponent, BadgeComponent, EmptyStateComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (groups().length === 0) {
      <hx-empty icon="calendar" title="Niente in programma">Nessuna voce nel periodo con i filtri attuali.</hx-empty>
    }
    @for (g of groups(); track g.key) {
      @if (g.nowBefore) { <ng-container [ngTemplateOutlet]="nowLine" /> }
      <section>
        <h3 [class.today]="g.today">{{ g.label }}</h3>
        @for (ev of g.events; track ev.id) {
          @if (g.nowAt === ev.id) { <ng-container [ngTemplateOutlet]="nowLine" /> }
          @let o = outcome(ev);
          <button class="row" [class.past]="isPast(ev)" [class.skipped]="ev.occ.skipped"
                  [class.done]="ev.occ.status === 'completed' || ev.occ.status === 'cancelled'"
                  (click)="selected.emit({ ev, rect: $any($event.currentTarget).getBoundingClientRect() })">
            <span class="time">{{ time(ev) }}</span>
            <span class="bar" [style.background]="ev.color"></span>
            <span class="main">
              <span class="title"><hx-icon [name]="icon(ev)" [size]="14" /> {{ ev.occ.title }}</span>
              <span class="meta">{{ owner(ev) }} · {{ typeLabel(ev) }}@if (ev.occ.recurring) { · {{ rule(ev) }} }</span>
              @if (o?.detail) { <span class="detail" [class.err]="o!.tone === 'danger'" [attr.title]="o!.detail">{{ o!.detail }}</span> }
            </span>
            @if (o) { <hx-badge [tone]="o.tone">{{ o.label }}</hx-badge> }
          </button>
        }
        @if (g.nowAfter) { <ng-container [ngTemplateOutlet]="nowLine" /> }
      </section>
    }
    <ng-template #nowLine>
      <div class="now" #now><span class="dot"></span><span class="lbl">Adesso · {{ nowLabel() }}</span><span class="line"></span></div>
    </ng-template>
  `,
  styles: [`
    :host { display: block; position: relative; overflow-y: auto; flex: 1; padding: 8px 24px 40px; }
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
    .detail { font-size: 12px; color: var(--text-2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .detail.err { color: var(--danger); }
    .row.past .time, .row.past .title { color: var(--text-3); }
    .row.skipped .title { text-decoration: line-through; }
    .row.skipped, .row.done { opacity: .6; }
    .now { max-width: 920px; margin: 4px auto; display: flex; align-items: center; gap: 8px; padding: 2px 4px; }
    .now .dot { width: 10px; height: 10px; border-radius: 50%; background: var(--danger); flex-shrink: 0; }
    .now .lbl { font-size: 12px; font-weight: 600; color: var(--danger); white-space: nowrap; font-variant-numeric: tabular-nums; }
    .now .line { flex: 1; border-top: 2px solid var(--danger); }
    @media (max-width: 720px) { :host { padding: 6px 10px 30px; } .time { width: 76px; } }
  `],
})
export class ListViewComponent {
  events = input.required<CalEvent[]>();
  /** First day of the list (store range start): items that began earlier are listed under it. */
  from = input.required<Date>();
  selected = output<SelectRequest>();

  private host = inject(ElementRef<HTMLElement>);
  private nowEl = viewChild<ElementRef<HTMLElement>>('now');
  readonly nowTick = signal(Date.now());
  private scrolled = false;

  constructor() {
    const timer = setInterval(() => this.nowTick.set(Date.now()), 60_000);
    inject(DestroyRef).onDestroy(() => clearInterval(timer));
    // first time the divider appears, bring it near the top (a few past rows stay visible above it)
    effect(() => {
      const el = this.nowEl()?.nativeElement;
      if (!el || this.scrolled) return;
      this.scrolled = true;
      const host = this.host.nativeElement as HTMLElement;
      host.scrollTop = Math.max(0, el.offsetTop - 140);
    });
  }

  nowLabel = computed(() => fmt.time(new Date(this.nowTick())));

  groups = computed<Group[]>(() => {
    const now = this.nowTick();
    const from = this.from();
    const map = new Map<string, Group>();
    const sorted = [...this.events()].sort((a, b) => a.start.getTime() - b.start.getTime());
    for (const ev of sorted) {
      const day = ev.start < from ? from : ev.start;   // began before the list (e.g. a window from yesterday)
      const k = dayKey(day);
      if (!map.has(k)) map.set(k, { key: k, label: fmt.dayLong(day), today: isToday(day), events: [], nowBefore: false, nowAt: null, nowAfter: false });
      map.get(k)!.events.push(ev);
    }
    const groups = [...map.values()];
    if (!groups.length || from.getTime() > now) return groups;   // list starts in the future: no "now"
    // divider before the first item that has not started yet
    const first = sorted.find(e => e.start.getTime() > now);
    const today = groups.find(g => g.today);
    if (!first) groups[groups.length - 1].nowAfter = true;
    else {
      const g = groups.find(x => x.events.includes(first))!;
      if (g.today) g.nowAt = first.id;
      else if (today) today.nowAfter = true;
      else g.nowBefore = true;
    }
    return groups;
  });

  isPast = (ev: CalEvent) => (ev.end ?? ev.start).getTime() < this.nowTick();

  /** Badge (+ detail line) for a row: the run result for past items, the state for upcoming ones. */
  outcome(ev: CalEvent): Outcome | null {
    const o = ev.occ, now = this.nowTick();
    if (o.skipped) return { label: 'saltata', tone: 'neutral' };
    const started = ev.start.getTime() <= now, ended = (ev.end ?? ev.start).getTime() < now;
    if (o.run) {
      if (!o.run.ok) return { label: 'fallito' + ((ev.failedCount ?? 0) > 1 ? ' ×' + ev.failedCount : ''), tone: 'danger', detail: o.run.detail || undefined };
      return { label: 'ok' + (o.run.duration_ms ? ' · ' + dur(o.run.duration_ms) : ''), tone: 'success', detail: o.run.detail || undefined };
    }
    if (o.status && o.status !== 'confirmed') {
      const s = STATUS_META[o.status] ?? STATUS_META.confirmed;
      return { label: s.label, tone: s.tone };
    }
    if (started && !ended) return { label: 'in corso', tone: 'accent' };
    if (ended) {
      if (!ev.item?.action) return { label: 'concluso', tone: 'neutral' };
      // one-off item: its result is the rule's last result
      const lr = !o.recurring ? ev.item.last_result : null;
      if (lr) return lr.ok ? { label: 'ok', tone: 'success', detail: lr.detail || undefined } : { label: 'fallito', tone: 'danger', detail: lr.detail || undefined };
      return { label: 'nessun esito', tone: 'warning' };
    }
    if (o.moved) return { label: 'spostata', tone: 'info' };
    return null;
  }

  time = (ev: CalEvent) => {
    const from = this.from();
    const s = ev.start < from && !isSameDay(ev.start, from) ? fmt.dateTime(ev.start) : fmt.time(ev.start);
    return `${s}${ev.end ? ' – ' + fmt.time(ev.end) : ''}`;
  };
  icon = (ev: CalEvent) => TYPE_META[ev.occ.type]?.icon ?? 'event';
  typeLabel = (ev: CalEvent) => TYPE_META[ev.occ.type]?.label ?? ev.occ.type;
  owner = (ev: CalEvent) => ownerLabel(ev.occ.owner);
  rule = (ev: CalEvent) => describeRRule(ev.item?.recurrence);
}

function dur(ms: number): string {
  return ms < 1000 ? `${ms} ms` : ms < 60_000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms / 60_000)} min`;
}
