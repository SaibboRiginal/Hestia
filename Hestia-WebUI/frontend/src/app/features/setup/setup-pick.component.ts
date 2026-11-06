import { ChangeDetectionStrategy, Component, computed, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { UI } from '../../ui';

/** One choice of the setup's picker: a model, a voice, a program's model… */
export interface PickItem { id: string; title: string; note?: string; warn?: boolean; tag?: string; icon?: string; }

/**
 * The one selector of the guided setup (docs/work/2026-10-30-setup-un-click): cards, a search box when the list is long,
 * the first few shown and «Mostra tutti». Used for local models, the memory's model, cloud models and voices, so every
 * choice looks and works the same. ``multi``: several chosen in order (``chosen``), each card shows its place
 * (1º, 2º…): the first is used, the next ones take over when it fails; a click adds or removes one.
 */
@Component({
  selector: 'app-setup-pick',
  imports: [...UI, FormsModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (items().length > searchFrom) {
      <label class="search">
        <hx-icon name="search" [size]="15" tone="muted" />
        <input class="hx-input" type="search" [placeholder]="placeholder()" [ngModel]="query()" (ngModelChange)="query.set($event)" autocomplete="off" spellcheck="false" />
      </label>
    }
    <div class="choices" [attr.role]="multi() ? 'group' : 'radiogroup'">
      @for (it of visible(); track it.id) {
        <button type="button" class="choice" [attr.role]="multi() ? 'checkbox' : 'radio'" [attr.aria-checked]="on(it.id)" [class.sel]="on(it.id)" (click)="picked.emit(it.id)">
          <hx-icon [name]="multi() && on(it.id) ? 'check-circle' : it.warn ? 'alert' : (it.icon || 'host')" [size]="18" [tone]="on(it.id) ? 'accent' : (it.warn ? 'warning' : 'muted')" />
          <span class="ct"><b>{{ it.title }}</b>@if (place(it.id); as n) { <span class="rec">{{ n }}º</span> } @else if (it.tag) { <span class="rec">{{ it.tag }}</span> }
            @if (it.note) { <small>{{ it.note }}</small> }</span>
        </button>
      } @empty {
        <p class="none">{{ query() ? 'Nessun risultato.' : empty() }}</p>
      }
    </div>
    @if (hidden() > 0) {
      <button type="button" class="more" (click)="all.set(true)">Mostra tutti ({{ filtered().length }})</button>
    }
  `,
  styles: [`
    :host { display: flex; flex-direction: column; gap: 8px; }
    .search { display: flex; align-items: center; gap: 8px; border: 1px solid var(--border); border-radius: var(--radius-md); padding: 0 10px; background: var(--surface); }
    .search input { border: 0; background: none; box-shadow: none; padding-left: 0; flex: 1; min-width: 0; }
    .choices { display: flex; flex-direction: column; gap: 6px; }
    .choice { display: flex; gap: 10px; align-items: flex-start; text-align: left; padding: 11px 12px; border: 1px solid var(--border);
              border-radius: var(--radius-md); background: var(--surface); color: var(--text); width: 100%;
              transition: border-color var(--dur-fast) var(--ease), background var(--dur-fast) var(--ease); }
    .choice:hover { border-color: var(--border-strong); }
    .choice.sel { border-color: var(--accent); background: var(--accent-soft); }
    .ct { display: flex; flex-direction: column; gap: 2px; flex: 1; min-width: 0; }
    .ct b { font-weight: 600; font-size: 14px; overflow-wrap: anywhere; }
    .ct small { color: var(--text-3); font-size: 12px; line-height: 1.4; }
    .rec { align-self: flex-start; font-size: 11px; font-weight: 600; color: var(--accent); background: var(--accent-soft); padding: 1px 7px; border-radius: var(--radius-full); }
    .more { align-self: flex-start; background: none; border: 0; color: var(--accent); font-size: 13px; padding: 2px 0; }
    .none { font-size: 13px; color: var(--text-3); }
  `],
})
export class SetupPickComponent {
  items = input<PickItem[]>([]);
  selected = input<string>('');
  /** Several in order instead of one. */
  multi = input<boolean>(false);
  chosen = input<string[]>([]);
  placeholder = input<string>('Cerca');
  empty = input<string>('Niente da scegliere.');
  /** Cards before «Mostra tutti». */
  limit = input<number>(5);
  picked = output<string>();
  readonly searchFrom = 6;
  query = signal('');
  all = signal(false);

  on(id: string): boolean { return this.multi() ? this.chosen().includes(id) : id === this.selected(); }
  /** The place of a chosen card when more than one is chosen (0 = none). */
  place(id: string): number { return this.multi() && this.chosen().length > 1 ? this.chosen().indexOf(id) + 1 : 0; }

  filtered = computed(() => {
    const q = this.query().trim().toLowerCase();
    return q ? this.items().filter(i => `${i.title} ${i.note || ''}`.toLowerCase().includes(q)) : this.items();
  });
  visible = computed(() => {
    const list = this.filtered();
    if (this.all() || this.query().trim() || list.length <= this.limit()) return list;
    const head = list.slice(0, this.limit());
    const sel = list.filter(i => this.on(i.id) && !head.includes(i));   // the chosen ones always stay in sight
    return [...head, ...sel];
  });
  hidden = computed(() => this.filtered().length - this.visible().length);
}
