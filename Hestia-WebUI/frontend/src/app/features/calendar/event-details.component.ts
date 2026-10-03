import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { CalEvent, STATUS_META, TYPE_META, ownerLabel } from './calendar.models';
import { fmt } from './date-utils';
import { describeRRule } from './rrule';
import { BadgeComponent, ButtonComponent, IconComponent, MenuComponent, MenuItem } from '../../ui';

export type DetailAction = 'edit' | 'skip' | 'unskip' | 'run' | 'pause' | 'resume' | 'cancel' | 'restore' | 'reset-move' | 'duplicate';

/** Content of the event popover: everything about one occurrence + its rule, with actions. */
@Component({
  selector: 'cal-event-details',
  imports: [IconComponent, ButtonComponent, BadgeComponent, MenuComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @let e = ev();
    <div class="top" [style.--c]="e.color">
      <span class="sw"></span>
      <div class="hx-grow">
        <h3>{{ e.occ.title }}</h3>
        <div class="when">{{ when() }}</div>
      </div>
      <button hx-btn variant="ghost" size="sm" icon="edit" iconOnly aria-label="Modifica" (click)="act.emit('edit')"></button>
      <hx-menu [items]="menu()" (select)="act.emit($any($event))">
        <button hx-btn variant="ghost" size="sm" icon="more" iconOnly trigger aria-label="Altro"></button>
      </hx-menu>
      <button hx-btn variant="ghost" size="sm" icon="x" iconOnly aria-label="Chiudi" (click)="close.emit()"></button>
    </div>

    <div class="badges">
      <hx-badge [color]="e.color" dot>{{ owner() }}</hx-badge>
      <hx-badge><hx-icon [name]="typeMeta().icon" [size]="11" /> {{ typeMeta().label }}</hx-badge>
      <hx-badge [tone]="status().tone">{{ status().label }}</hx-badge>
      @if (e.occ.skipped) { <hx-badge tone="warning">occorrenza saltata</hx-badge> }
      @if (e.occ.moved) { <hx-badge tone="info">spostata</hx-badge> }
      @if (e.item?.user_modified) { <hx-badge tone="accent">modificata da te</hx-badge> }
    </div>

    <dl>
      @if (e.occ.recurring) { <dt><hx-icon name="repeat" [size]="14" /></dt><dd>{{ rule() }}</dd> }
      @if (e.item?.description) { <dt><hx-icon name="list" [size]="14" /></dt><dd class="desc">{{ e.item?.description }}</dd> }
      @if (e.item?.action; as a) {
        <dt><hx-icon name="zap" [size]="14" /></dt>
        <dd><code>{{ a.method || 'POST' }} {{ a.service }}{{ a.path }}</code></dd>
      }
      @if (e.item?.last_result; as r) {
        <dt><hx-icon [name]="r.ok ? 'check' : 'alert'" [size]="14" /></dt>
        <dd [class.err]="!r.ok">Ultima esecuzione {{ rel(r.at) }}: {{ r.ok ? 'ok' : 'fallita' }}
          @if (!r.ok) { <span class="detail">{{ r.detail }}</span> }</dd>
      }
      <dt><hx-icon name="info" [size]="14" /></dt><dd class="key"><code>{{ e.occ.key }}</code></dd>
    </dl>

    <div class="actions">
      @if (e.occ.skipped) {
        <button hx-btn size="sm" icon="undo" (click)="act.emit('unskip')">Ripristina</button>
      } @else if (e.occ.status !== 'cancelled' && e.occ.status !== 'completed') {
        <button hx-btn size="sm" icon="skip" (click)="act.emit('skip')">{{ e.occ.recurring ? 'Salta questa' : 'Ignora' }}</button>
      }
      @if (e.item?.action && e.occ.status !== 'cancelled') {
        <button hx-btn size="sm" icon="play" (click)="act.emit('run')">Esegui ora</button>
      }
      @if (e.occ.status === 'paused') {
        <button hx-btn size="sm" variant="primary" icon="play" (click)="act.emit('resume')">Riattiva</button>
      }
      @if (e.occ.status === 'cancelled') {
        <button hx-btn size="sm" variant="primary" icon="undo" (click)="act.emit('restore')">Ripristina regola</button>
      }
    </div>
  `,
  styles: [`
    :host { display: block; padding: 12px 12px 14px 16px; }
    .top { display: flex; align-items: flex-start; gap: 8px; }
    .sw { width: 12px; height: 12px; border-radius: 4px; background: var(--c); margin-top: 6px; flex-shrink: 0; }
    h3 { font-size: 16px; font-weight: 600; line-height: 1.3; }
    .when { font-size: 13px; color: var(--text-2); margin-top: 2px; }
    .badges { display: flex; flex-wrap: wrap; gap: 5px; margin: 10px 0 8px 20px; }
    dl { display: grid; grid-template-columns: 20px 1fr; gap: 6px 8px; font-size: 13px; color: var(--text-2); margin-left: -2px; }
    dt { color: var(--text-3); padding-top: 1px; }
    dd { min-width: 0; word-wrap: break-word; }
    .desc { white-space: pre-wrap; }
    .err { color: var(--danger); }
    .detail { display: block; color: var(--text-3); font-size: 12px; }
    .key code { font-size: 11.5px; }
    .actions { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; padding-left: 20px; }
  `],
})
export class EventDetailsComponent {
  ev = input.required<CalEvent>();
  act = output<DetailAction>();
  close = output<void>();

  typeMeta = computed(() => TYPE_META[this.ev().occ.type] ?? TYPE_META.event);
  status = computed(() => STATUS_META[this.ev().occ.status ?? 'confirmed'] ?? STATUS_META.confirmed);
  owner = computed(() => ownerLabel(this.ev().occ.owner));
  rule = computed(() => describeRRule(this.ev().item?.recurrence));
  when = computed(() => {
    const e = this.ev();
    const day = fmt.dayLong(e.start);
    if (!e.end) return `${day} · ${fmt.time(e.start)}`;
    const sameDay = e.start.toDateString() === e.end.toDateString();
    return sameDay ? `${day} · ${fmt.time(e.start)} – ${fmt.time(e.end)}`
                   : `${fmt.dateTime(e.start)} → ${fmt.dateTime(e.end)}`;
  });

  menu = computed<MenuItem[]>(() => {
    const e = this.ev();
    const active = e.occ.status !== 'cancelled' && e.occ.status !== 'completed';
    return [
      { id: 'edit', label: 'Modifica', icon: 'edit' },
      { id: 'duplicate', label: 'Duplica', icon: 'copy' },
      ...(e.occ.moved ? [{ id: 'reset-move', label: 'Ripristina orario originale', icon: 'undo' }] : []),
      ...(active && e.occ.status !== 'paused' && e.occ.recurring ? [{ id: 'pause', label: 'Metti in pausa la regola', icon: 'pause' }] : []),
      ...(e.occ.status === 'paused' ? [{ id: 'resume', label: 'Riattiva', icon: 'play' }] : []),
      { id: 'd', label: '', divider: true },
      ...(active ? [{ id: 'cancel', label: e.occ.recurring ? 'Annulla tutta la regola' : 'Annulla', icon: 'trash', danger: true }] : []),
      ...(e.occ.status === 'cancelled' ? [{ id: 'restore', label: 'Ripristina', icon: 'undo' }] : []),
    ];
  });

  rel(iso: string) { return fmt.relative(new Date(iso)); }
}
