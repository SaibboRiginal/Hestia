import { ChangeDetectionStrategy, Component, HostListener, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { CalendarStore } from './calendar.store';
import { AgendaType, CalEvent, CalView, TYPE_META, ownerLabel } from './calendar.models';
import { addDays, addMinutes, dayKey, startOfWeek } from './date-utils';
import { TimeGridComponent, MoveRequest, SelectRequest } from './views/time-grid.component';
import { MonthViewComponent } from './views/month-view.component';
import { ListViewComponent } from './views/list-view.component';
import { MiniCalendarComponent } from './mini-calendar.component';
import { DetailAction, EventDetailsComponent } from './event-details.component';
import { EditorResult, EditorSeed, EventEditorComponent } from './event-editor.component';
import {
  ButtonComponent, DialogService, IconComponent, PopoverComponent, SegmentedComponent, SegmentOption, SpinnerComponent,
  ToggleComponent,
} from '../../ui';

/**
 * Hestia's own calendar (assistant agenda): month / week / day / list, sidebar with mini calendar,
 * layers and filters, popover details, editor, drag & drop. Keys: T oggi · M/W/D/L viste · N nuovo · ←/→.
 */
@Component({
  selector: 'app-calendar-page',
  imports: [
    FormsModule, ButtonComponent, IconComponent, SegmentedComponent, SpinnerComponent, ToggleComponent, PopoverComponent,
    TimeGridComponent, MonthViewComponent, ListViewComponent, MiniCalendarComponent, EventDetailsComponent, EventEditorComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="page">
      <aside class="side" [class.open]="sideOpen()">
        <button hx-btn variant="primary" icon="plus" class="new" (click)="newAt(defaultStart())">Nuovo</button>
        <cal-mini [selected]="store.anchor()" [marked]="markedDays()" (pick)="store.goto($event)" />

        <section>
          <h4>Calendari</h4>
          @for (s of store.sources(); track s.id) {
            <label class="flt"><input type="checkbox" class="hx-check" [checked]="s.enabled" (change)="toggleSource(s.id)" />
              <span class="sw ai"></span><span class="hx-grow">{{ s.label }}</span></label>
          }
          <p class="hint">I tuoi calendari Google/Outlook arriveranno qui come livelli separati.</p>
        </section>

        <section>
          <h4>Moduli</h4>
          @for (o of store.owners(); track o.owner) {
            <label class="flt" [title]="'Doppio clic: mostra solo ' + label(o.owner)" (dblclick)="store.onlyOwner(o.owner)">
              <input type="checkbox" class="hx-check" [style.accent-color]="o.color"
                     [checked]="!store.hiddenOwners().has(o.owner)" (change)="store.toggleOwner(o.owner)" />
              <span class="sw" [style.background]="o.color"></span>
              <span class="hx-grow hx-truncate">{{ label(o.owner) }}</span>
              <span class="cnt">{{ o.count }}</span>
            </label>
          } @empty { <p class="hint">Nessun modulo ha ancora pianificato nulla.</p> }
        </section>

        <section>
          <h4>Tipi</h4>
          @for (t of types; track t) {
            <label class="flt"><input type="checkbox" class="hx-check" [checked]="!store.hiddenTypes().has(t)" (change)="store.toggleType(t)" />
              <hx-icon [name]="typeIcon(t)" [size]="14" /><span class="hx-grow">{{ typeLabel(t) }}</span></label>
          }
        </section>

        <section class="opts">
          <hx-toggle label="Mostra occorrenze saltate" [checked]="store.showSkipped()" (changed)="store.setShowSkipped($event)" />
          <hx-toggle label="Mostra completate/annullate" [checked]="store.showDone()" (changed)="store.setShowDone($event)" />
        </section>
      </aside>
      <div class="scrim" (click)="sideOpen.set(false)"></div>

      <section class="main">
        <header class="bar">
          <button hx-btn variant="ghost" icon="sidebar" iconOnly class="side-btn" aria-label="Filtri" (click)="sideOpen.set(!sideOpen())"></button>
          <button hx-btn variant="secondary" size="sm" (click)="store.today()">Oggi</button>
          <div class="nav">
            <button hx-btn variant="ghost" size="sm" icon="chevron-left" iconOnly aria-label="Indietro" (click)="store.step(-1)"></button>
            <button hx-btn variant="ghost" size="sm" icon="chevron-right" iconOnly aria-label="Avanti" (click)="store.step(1)"></button>
          </div>
          <h2>{{ store.title() }}</h2>
          @if (store.loading()) { <hx-spinner [size]="16" /> }
          <div class="hx-grow"></div>
          <div class="search">
            <hx-icon name="search" [size]="15" />
            <input class="hx-input" placeholder="Cerca…" [ngModel]="store.search()" (ngModelChange)="store.search.set($event)" />
          </div>
          <button hx-btn variant="ghost" size="sm" icon="refresh" iconOnly aria-label="Aggiorna" (click)="store.load()"></button>
          <hx-segmented [options]="viewOptions" [value]="store.view()" (changed)="store.setView($event)" />
        </header>

        @if (store.error()) {
          <div class="err"><hx-icon name="alert" [size]="16" /> {{ store.error() }}
            <button hx-btn size="sm" variant="ghost" (click)="store.load()">Riprova</button></div>
        }

        @switch (store.view()) {
          @case ('month') {
            <cal-month-view [anchor]="store.anchor()" [events]="store.events()" (selected)="select($event)"
                            (createAt)="newAt($event)" (moved)="onMove($event)" (dayClick)="openDay($event)" />
          }
          @case ('list') { <cal-list-view [events]="store.events()" (selected)="select($event)" /> }
          @default {
            <cal-time-grid [days]="gridDays()" [events]="store.events()" (selected)="select($event)"
                           (createAt)="newAt($event)" (moved)="onMove($event)" (dayClick)="openDay($event)" />
          }
        }
      </section>
    </div>

    <hx-popover [open]="!!sel()" [anchor]="selRect()" [width]="360" (closed)="sel.set(null)">
      @if (sel(); as s) { <cal-event-details [ev]="s" (act)="onAction($event)" (close)="sel.set(null)" /> }
    </hx-popover>

    <cal-event-editor [seed]="editor()" (saved)="onSave($event)" (cancel)="editor.set(null)" />
  `,
  styles: [`
    :host { display: flex; flex: 1; min-height: 0; }
    .page { display: flex; flex: 1; min-height: 0; }
    .side { width: 256px; flex-shrink: 0; border-right: 1px solid var(--border); padding: 14px 12px; overflow-y: auto;
            display: flex; flex-direction: column; gap: 16px; background: var(--bg); }
    .new { align-self: flex-start; padding: 0 18px; height: 40px; border-radius: var(--radius-lg); box-shadow: var(--shadow-1); }
    section h4 { font-size: 11.5px; text-transform: uppercase; letter-spacing: .05em; color: var(--text-3); font-weight: 600; margin: 0 0 6px 4px; }
    .flt { display: flex; align-items: center; gap: 8px; padding: 4px 6px; border-radius: var(--radius-sm); font-size: 13.5px; cursor: pointer; user-select: none; }
    .flt:hover { background: var(--surface-2); }
    .sw { width: 10px; height: 10px; border-radius: 3px; flex-shrink: 0; }
    .sw.ai { background: linear-gradient(135deg, var(--cal-1), var(--cal-2)); }
    .cnt { font-size: 11.5px; color: var(--text-3); }
    .hint { font-size: 12px; color: var(--text-3); padding: 2px 6px; }
    .opts { display: flex; flex-direction: column; gap: 10px; padding: 0 4px; }
    .opts hx-toggle ::ng-deep .lbl { font-size: 13px; }
    .main { flex: 1; min-width: 0; display: flex; flex-direction: column; }
    .bar { display: flex; align-items: center; gap: 8px; padding: 12px 16px; border-bottom: 1px solid var(--border); flex-wrap: wrap; }
    .bar h2 { font-family: var(--font-serif); font-weight: 500; font-size: 20px; white-space: nowrap; }
    .nav { display: flex; }
    .search { position: relative; width: 200px; }
    .search hx-icon { position: absolute; left: 9px; top: 50%; transform: translateY(-50%); color: var(--text-3); }
    .search .hx-input { padding-left: 30px; height: 32px; }
    .side-btn { display: none; }
    .err { margin: 10px 16px 0; padding: 8px 12px; border-radius: var(--radius-md); background: var(--danger-soft); color: var(--danger);
           display: flex; align-items: center; gap: 8px; font-size: 13.5px; }
    .scrim { display: none; }
    @media (max-width: 1100px) {
      .side { position: fixed; z-index: 700; inset: 0 auto 0 0; transform: translateX(-100%); transition: transform var(--dur) var(--ease); box-shadow: var(--shadow-3); }
      .side.open { transform: none; }
      .side.open + .scrim { display: block; position: fixed; inset: 0; background: var(--overlay); z-index: 690; }
      .side-btn { display: inline-flex; }
      .search { width: 140px; }
    }
    @media (max-width: 720px) { .bar { padding: 10px 10px 10px 50px; } .bar h2 { font-size: 16px; } .search { display: none; } }
  `],
})
export class CalendarPageComponent implements OnInit {
  store = inject(CalendarStore);
  private dialogs = inject(DialogService);

  readonly types: AgendaType[] = ['event', 'task', 'job', 'window'];
  readonly viewOptions: SegmentOption<CalView>[] = [
    { value: 'day', label: 'Giorno', title: 'Giorno (D)' },
    { value: 'week', label: 'Settimana', title: 'Settimana (W)' },
    { value: 'month', label: 'Mese', title: 'Mese (M)' },
    { value: 'list', label: 'Elenco', icon: 'list', title: 'Elenco (L)' },
  ];

  sideOpen = signal(false);
  sel = signal<CalEvent | null>(null);
  selRect = signal<DOMRect | null>(null);
  editor = signal<EditorSeed | null>(null);

  gridDays = computed(() => {
    const a = this.store.anchor();
    if (this.store.view() === 'day') return [a];
    const s = startOfWeek(a);
    return Array.from({ length: 7 }, (_, i) => addDays(s, i));
  });
  markedDays = computed(() => new Set(this.store.events().map(e => dayKey(e.start))));

  ngOnInit() { void this.store.load(); }

  label = ownerLabel;
  typeIcon = (t: AgendaType) => TYPE_META[t].icon;
  typeLabel = (t: AgendaType) => TYPE_META[t].label;

  toggleSource(id: string) {
    this.store.sources.update(list => list.map(s => s.id === id ? { ...s, enabled: !s.enabled } : s));
  }

  defaultStart(): Date {
    const d = new Date(this.store.anchor());
    const now = new Date();
    d.setHours(now.getHours() + 1, 0, 0, 0);
    return d;
  }

  select(r: SelectRequest) { this.selRect.set(r.rect); this.sel.set(r.ev); }
  openDay(d: Date) { this.store.anchor.set(d); this.store.setView('day'); }
  newAt(d: Date) { this.sel.set(null); this.editor.set({ start: d, end: addMinutes(d, 60), type: 'event' }); }

  async onMove(m: MoveRequest) {
    let scope: 'one' | 'all' = 'one';
    if (m.ev.occ.recurring) {
      const r = await this.dialogs.choose<'one' | 'all'>('Spostare la voce ricorrente', `"${m.ev.occ.title}"`, [
        { value: 'one', label: 'Solo questa', variant: 'secondary' },
        { value: 'all', label: 'Tutta la serie', variant: 'primary' },
      ]);
      if (!r) return;
      scope = r;
    }
    await this.store.move(m.ev, m.start, m.end, scope);
  }

  async onAction(a: DetailAction) {
    const ev = this.sel();
    if (!ev) return;
    switch (a) {
      case 'edit': if (ev.item) this.editor.set({ start: ev.start, end: ev.end, item: ev.item }); break;
      case 'duplicate': if (ev.item) this.editor.set({ start: ev.start, end: ev.end, item: ev.item, duplicate: true }); break;
      case 'skip': await this.store.skip(ev); break;
      case 'unskip': await this.store.unskip(ev); break;
      case 'run': await this.store.run(ev); break;
      case 'pause': await this.store.pause(ev, true); break;
      case 'resume': await this.store.pause(ev, false); break;
      case 'restore': await this.store.update(ev.occ.key, { status: 'confirmed' }, 'Regola ripristinata'); break;
      case 'reset-move': await this.store.resetMove(ev); break;
      case 'cancel': {
        const ok = await this.dialogs.confirm(ev.occ.recurring ? 'Annullare tutta la regola?' : 'Annullare la voce?',
          ev.occ.recurring ? 'Nessuna occorrenza futura verrà eseguita. Per saltarne solo una usa "Salta questa".' : '',
          'Annulla regola', true);
        if (ok) await this.store.cancel(ev);
        break;
      }
    }
    if (a !== 'edit' && a !== 'duplicate') this.sel.set(null);
    else this.sel.set(null);
  }

  async onSave(r: EditorResult) {
    this.editor.set(null);
    if (r.key) await this.store.update(r.key, r.body, 'Modifiche salvate');
    else await this.store.create(r.body);
  }

  @HostListener('document:keydown', ['$event'])
  onKey(e: KeyboardEvent) {
    const t = e.target as HTMLElement;
    if (e.ctrlKey || e.metaKey || e.altKey || ['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName) || this.editor()) return;
    const map: Record<string, () => void> = {
      t: () => this.store.today(), m: () => this.store.setView('month'), w: () => this.store.setView('week'),
      d: () => this.store.setView('day'), l: () => this.store.setView('list'), n: () => this.newAt(this.defaultStart()),
      ArrowLeft: () => this.store.step(-1), ArrowRight: () => this.store.step(1),
    };
    const fn = map[e.key];
    if (fn) { e.preventDefault(); fn(); }
  }
}
