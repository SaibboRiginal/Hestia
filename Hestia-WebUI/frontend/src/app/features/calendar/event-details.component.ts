import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { CalEvent, STATUS_META, TYPE_META, ownerLabel } from './calendar.models';
import { fmt } from './date-utils';
import { describeRRule } from './rrule';
import { RouterLink } from '@angular/router';
import { BadgeComponent, ButtonComponent, IconComponent, MenuComponent, MenuItem } from '../../ui';

export type DetailAction = 'edit' | 'skip' | 'unskip' | 'run' | 'pause' | 'resume' | 'cancel' | 'restore' | 'reset-move' | 'duplicate' | 'ask' | 'logs';

/** Plain-language meaning of a window, by module (fallback: generic). */
const WINDOW_TEXT: Record<string, string> = {
  athena: 'Athena può lavorare (consolidare memoria, analisi) solo in questo intervallo, di solito quando sei inattivo. Fuori dalla finestra non parte.',
  metis: 'Metis può addestrare i modelli solo in questo intervallo, per non rallentare il PC mentre lo usi.',
  hephaestus: 'Forge può usare il motore indicato (es. Claude Pro) solo in questo intervallo.',
};

/** Content of the event popover: everything about one occurrence + its rule, with actions. */
@Component({
  selector: 'cal-event-details',
  imports: [IconComponent, ButtonComponent, BadgeComponent, MenuComponent, RouterLink],
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

    @if (e.group?.length) {
      <div class="grp">
        <div class="grp-h">{{ e.group!.length }} esecuzioni il {{ day() }} · {{ rule() }}</div>
        <div class="grp-l">
          @for (g of e.group!; track g.id) {
            <button class="gi" [class.ko]="g.occ.run?.ok === false" [class.ok]="g.occ.run?.ok === true" [class.sk]="g.occ.skipped"
                    (click)="pick.emit(g)" [attr.title]="g.occ.run ? (g.occ.run.ok ? 'ok' : 'fallita: ' + (g.occ.run.detail || '')) : 'non ancora eseguita'">
              {{ t(g.start) }}
            </button>
          }
        </div>
        <div class="grp-n">Clic su un orario per aprire quella singola esecuzione.</div>
      </div>
    }

    @if (e.occ.type === 'window') {
      <p class="explain"><hx-icon name="window" [size]="14" /> <span><b>Finestra {{ t(e.start) }}–{{ e.end ? t(e.end) : '' }}.</b> {{ windowText() }}</span></p>
    }

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
      @if (e.occ.run; as r) {
        <dt><hx-icon [name]="r.ok ? 'check' : 'alert'" [size]="14" /></dt>
        <dd [class.err]="!r.ok">Questa esecuzione: {{ r.ok ? 'ok' : 'fallita' }}{{ r.duration_ms ? ' · ' + r.duration_ms + ' ms' : '' }}
          @if ((e.failedCount ?? 0) > 1) { · fallita {{ e.failedCount }} volte negli ultimi giorni }
          @if (!r.ok && r.detail) { <span class="detail">{{ r.detail }}</span> }</dd>
      } @else if (e.item?.last_result) {
        @let lr = e.item!.last_result!;
        <dt><hx-icon [name]="lr.ok ? 'check' : 'alert'" [size]="14" /></dt>
        <dd [class.err]="!lr.ok">Ultima esecuzione della regola {{ rel(lr.at) }}: {{ lr.ok ? 'ok' : 'fallita' }}
          @if (!lr.ok) { <span class="detail">{{ lr.detail }}</span> }</dd>
      }
      @if (e.item?.parent; as p) {
        <dt><hx-icon name="branch" [size]="14" /></dt><dd>Collegata a <code>{{ p }}</code>: se annulli quella, si annulla anche questa</dd>
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
      @if (forgeTask(); as id) {
        <a hx-btn size="sm" icon="code" [routerLink]="['/forge']" [queryParams]="{ task: id }">Apri in Sviluppo</a>
      }
      <button hx-btn size="sm" variant="ghost" icon="sparkle" class="ask" (click)="act.emit('ask')" title="Modifica o spiega questa voce a parole">Chiedi a Hestia</button>
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
    .grp { margin: 10px 0 4px 20px; }
    .grp-h { font-size: 12.5px; color: var(--text-2); margin-bottom: 6px; }
    .grp-l { display: flex; flex-wrap: wrap; gap: 4px; max-height: 120px; overflow-y: auto; }
    .gi { font-size: 11.5px; font-variant-numeric: tabular-nums; padding: 2px 7px; border-radius: var(--radius-full); background: var(--surface-2); color: var(--text-2); }
    .gi:hover { background: var(--surface-3); color: var(--text); }
    .gi.ok { box-shadow: inset 0 -2px 0 var(--success); } .gi.ko { background: var(--danger-soft); color: var(--danger); } .gi.sk { text-decoration: line-through; opacity: .6; }
    .grp-n { font-size: 11.5px; color: var(--text-3); margin-top: 5px; }
    .explain { display: flex; gap: 7px; margin: 10px 0 2px 20px; font-size: 13px; color: var(--text-2); line-height: 1.45; }
    .explain hx-icon { color: var(--c, var(--accent)); margin-top: 2px; flex-shrink: 0; }
    .ask { color: var(--accent); }
    .actions { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; padding-left: 20px; }
  `],
})
export class EventDetailsComponent {
  ev = input.required<CalEvent>();
  act = output<DetailAction>();
  /** A single occurrence picked from a summary chip's list. */
  pick = output<CalEvent>();
  close = output<void>();

  /** Forge mirrors every task as `forge.task.<id>`: link to its page (conversation, diff, tests, logs). */
  forgeTask = computed(() => /^forge\.task\.([0-9a-f]{6,})$/.exec(this.ev().occ.key)?.[1] ?? null);
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
      { id: 'ask', label: 'Chiedi a Hestia…', icon: 'sparkle' },
      ...(e.item?.action || e.occ.run ? [{ id: 'logs', label: 'Log del modulo', icon: 'terminal' }] : []),
      ...(e.occ.moved ? [{ id: 'reset-move', label: 'Ripristina orario originale', icon: 'undo' }] : []),
      ...(active && e.occ.status !== 'paused' && e.occ.recurring ? [{ id: 'pause', label: 'Metti in pausa la regola', icon: 'pause' }] : []),
      ...(e.occ.status === 'paused' ? [{ id: 'resume', label: 'Riattiva', icon: 'play' }] : []),
      { id: 'd', label: '', divider: true },
      ...(active ? [{ id: 'cancel', label: e.occ.recurring ? 'Annulla tutta la regola' : 'Annulla', icon: 'trash', danger: true }] : []),
      ...(e.occ.status === 'cancelled' ? [{ id: 'restore', label: 'Ripristina', icon: 'undo' }] : []),
    ];
  });

  rel(iso: string) { return fmt.relative(new Date(iso)); }
  t = (d: Date) => fmt.time(d);
  day = computed(() => fmt.dayLong(this.ev().start));
  windowText = computed(() => WINDOW_TEXT[this.ev().occ.owner]
    ?? `${ownerLabel(this.ev().occ.owner)} può lavorare solo in questo intervallo; fuori dalla finestra le sue attività aspettano.`);
}
