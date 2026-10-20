import { ChangeDetectionStrategy, Component, OnInit, computed, effect, inject, signal, untracked } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ButtonComponent, DateFieldComponent, FieldComponent, IconComponent, PopoverComponent, SpinnerComponent, Anchor } from '../../ui';
import { PluginsService } from './plugins.service';
import { QuickActionsService } from './quick-actions.service';
import { QuickChipView } from './plugins.types';

const today = () => { const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 10); };

/**
 * Home strip of one-tap quick actions (SPEC §4.2b): tap = done (toast with «Annulla»), ★ pins (WebUI setting
 * webui.home.quick), ⋯ another day / note / params. Drawn by the WebUI, so it is instant even before any bundle loads.
 */
@Component({
  selector: 'hx-quick-strip',
  imports: [FormsModule, ButtonComponent, IconComponent, SpinnerComponent, PopoverComponent, DateFieldComponent, FieldComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (qa.chips().length || qa.loading()) {
      <section class="strip" aria-label="Azioni rapide">
        @for (c of shown(); track c.key) {
          <div class="chip" role="button" tabindex="0" [attr.data-state]="c.state || 'todo'" [attr.aria-busy]="qa.busy() === c.key"
               [attr.title]="moduleTitle(c)" (click)="tap(c)" (keydown.enter)="tap(c)" (keydown.space)="$event.preventDefault(); tap(c)">
            @if (c.state === 'done') { <hx-icon name="check" [size]="16" /> } @else if (c.icon) { <hx-icon [name]="c.icon" [size]="16" /> }
            <span class="txt"><span class="lab">{{ c.label }}</span>@if (c.hint) {<span class="hint">{{ c.hint }}</span>}</span>
            <button class="mini" [class.pinned]="isPinned(c)" (click)="$event.stopPropagation(); plugins.togglePin(c.key)"
                    [attr.aria-label]="isPinned(c) ? 'Togli dalla Home' : 'Fissa in Home'" [attr.title]="isPinned(c) ? 'Fissata' : 'Fissa in Home'">
              <hx-icon name="star" [size]="13" />
            </button>
            <button class="mini" (click)="openMore($event, c)" aria-label="Altro giorno o dettagli" title="Altro giorno o dettagli">
              <hx-icon name="more" [size]="15" />
            </button>
          </div>
        }
        @if (qa.secondary().length) {
          <button class="chip more-toggle" (click)="showAll.set(!showAll())">
            {{ showAll() ? 'Meno' : 'Altre (' + qa.secondary().length + ')' }}
          </button>
        }
        @if (qa.loading() && !qa.chips().length) { <hx-spinner [size]="16" /> }
      </section>
    }
    <hx-popover [open]="!!more()" [anchor]="anchor()" [width]="280" (closed)="more.set(null)">
      @if (more(); as c) {
        <div class="sheet">
          <div class="st">{{ c.label }}</div>
          <hx-field label="Giorno"><hx-date [(value)]="date" /></hx-field>
          @for (p of params(); track p.name) {
            <hx-field [label]="p.spec.label">
              @if (p.spec.type === 'enum') {
                <select class="hx-select" [(ngModel)]="values[p.name]">@for (o of p.spec.options ?? []; track o) { <option [value]="o">{{ o }}</option> }</select>
              } @else if (p.spec.type === 'int' || p.spec.type === 'float') {
                <input class="hx-input" type="number" [(ngModel)]="values[p.name]">
              } @else if (p.spec.type === 'bool') {
                <input class="hx-check" type="checkbox" [(ngModel)]="values[p.name]">
              } @else {
                <input class="hx-input" [(ngModel)]="values[p.name]">
              }
            </hx-field>
          }
          <hx-field label="Nota"><input class="hx-input" [(ngModel)]="note" placeholder="facoltativa"></hx-field>
          <button hx-btn variant="primary" size="sm" icon="check" (click)="submitMore(c)">Segna</button>
        </div>
      }
    </hx-popover>`,
  styles: [`
    .strip { display: flex; flex-wrap: wrap; gap: 8px; }
    .chip { display: inline-flex; align-items: center; gap: 8px; min-height: 44px; padding: 6px 4px 6px 14px; border-radius: var(--radius-full);
            border: 1px solid var(--border-strong); background: var(--surface); color: var(--text); cursor: pointer; font-size: 14px;
            transition: background var(--dur-fast) var(--ease), border-color var(--dur-fast) var(--ease); user-select: none; }
    .chip:hover { background: var(--surface-2); }
    .chip:focus-visible { outline: none; box-shadow: 0 0 0 3px var(--focus-ring); }
    .chip[data-state=done] { background: var(--success-soft); border-color: transparent; color: var(--success); }
    .chip[data-state=late] { border-color: var(--warning); }
    .chip[aria-busy=true] { opacity: .55; pointer-events: none; }
    .txt { display: flex; flex-direction: column; line-height: 1.15; }
    .lab { font-weight: 500; } .hint { font-size: 11.5px; color: var(--text-3); }
    .chip[data-state=done] .hint { color: inherit; opacity: .8; }
    .mini { width: 28px; height: 28px; border-radius: 50%; display: grid; place-items: center; color: var(--text-3); }
    .mini:hover { background: var(--surface-3); color: var(--text); }
    .mini.pinned { color: var(--warning); }
    .more-toggle { padding: 6px 14px; color: var(--text-2); font-weight: 500; }
    .sheet { padding: 12px; display: flex; flex-direction: column; gap: 10px; }
    .st { font-weight: 600; }
  `],
})
export class QuickStripComponent implements OnInit {
  plugins = inject(PluginsService);
  qa = inject(QuickActionsService);
  showAll = signal(false);
  more = signal<QuickChipView | null>(null);
  anchor = signal<Anchor>(null);
  date = signal(today());
  note = '';
  values: Record<string, unknown> = {};

  readonly shown = computed(() => this.showAll() ? this.qa.sorted() : this.qa.primary());
  readonly params = computed(() => Object.entries(this.more()?.action.params ?? {}).map(([name, spec]) => ({ name, spec })));

  constructor() {
    effect(() => { this.plugins.quickActions(); untracked(() => void this.qa.reload()); });
  }

  ngOnInit(): void { void this.qa.reload(true); }

  isPinned(c: QuickChipView) { return this.plugins.quickPins().includes(c.key); }
  moduleTitle(c: QuickChipView) { return this.plugins.modules().get(c.action.module)?.title ?? c.action.module; }

  tap(c: QuickChipView): void {
    if (Object.keys(c.action.params ?? {}).length) { this.openAt(c, null); return; }   // needs values: open the sheet
    void this.qa.run(c);
  }

  openMore(ev: MouseEvent, c: QuickChipView): void {
    ev.stopPropagation();
    this.openAt(c, (ev.currentTarget as HTMLElement).getBoundingClientRect());
  }

  private openAt(c: QuickChipView, rect: DOMRect | null): void {
    this.date.set(today());
    this.note = '';
    this.values = Object.fromEntries(Object.entries(c.action.params ?? {}).map(([k, s]) => [k, s.default ?? '']));
    this.anchor.set(rect ?? { x: window.innerWidth / 2 - 140, y: 120, width: 0, height: 0 });
    this.more.set(c);
  }

  submitMore(c: QuickChipView): void {
    const body: Record<string, unknown> = { ...this.values, date: this.date() };
    if (this.note.trim()) body['note'] = this.note.trim();
    this.more.set(null);
    void this.qa.run(c, body);
  }
}
