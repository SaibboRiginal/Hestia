import { ChangeDetectionStrategy, Component, computed, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { UI } from '../../ui';

/** One choice of the setup's picker: a model, a voice, a program's model… */
export interface PickItem { id: string; title: string; note?: string; warn?: boolean; tag?: string; icon?: string;
  /** The filter chip it belongs to (model family, program, engine): chips appear when a long list has two or more. */
  group?: string;
  /** The language it speaks (voices): the list then shows a language selector instead of the language in every name. */
  lang?: string; langLabel?: string; }

/** A model's family for the filter chips, read from its name (any service): «gemini-2.5-flash-lite-preview» →
 * «Gemini Flash Lite», «qwen3:14b» → «Qwen3». Version numbers, dates and «preview/exp/latest» do not count. */
export function family(id: string): string {
  const words = id.toLowerCase().replace(/^models\//, '').split(/[-_:/. ]+/)
    .filter(w => w && !/^\d/.test(w) && !/^v\d/.test(w) && !['preview', 'exp', 'experimental', 'latest', 'it', 'instruct', 'chat', 'gguf', 'q4', 'k', 'm'].includes(w) && !/^\d+[bkm]$/.test(w));
  const name = words.slice(0, 3).join(' ');
  return name ? name.replace(/\b\w/g, c => c.toUpperCase()) : 'Altri';
}

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
    @if (items().length) {
      <div class="tools">
        <label class="search">
          <hx-icon name="search" [size]="15" tone="muted" />
          <input class="hx-input" type="search" [placeholder]="placeholder()" [ngModel]="query()" (ngModelChange)="query.set($event)" autocomplete="off" spellcheck="false" />
        </label>
        @if (langs().length > 1) {
          <select class="hx-select lang" aria-label="Lingua" [value]="langNow()" (change)="lang.set($any($event.target).value)">
            @for (l of langs(); track l.id) { <option [value]="l.id" [selected]="l.id === langNow()">{{ l.label }}</option> }
          </select>
        }
      </div>
    }
    @if (groups().length > 1 && items().length > searchFrom) {
      <div class="chips" role="group" aria-label="Filtra">
        <button type="button" class="chip" [class.on]="!group()" (click)="group.set('')">Tutti</button>
        @for (g of groups(); track g) { <button type="button" class="chip" [class.on]="group() === g" (click)="group.set(group() === g ? '' : g)">{{ g }}</button> }
      </div>
    }
    <div class="choices" [attr.role]="multi() ? 'group' : 'radiogroup'">
      @for (it of visible(); track it.id) {
        <div class="item">
          <button type="button" class="choice" [attr.role]="multi() ? 'checkbox' : 'radio'" [attr.aria-checked]="on(it.id)" [class.sel]="on(it.id)" (click)="picked.emit(it.id)">
            <hx-icon [name]="multi() && on(it.id) ? 'check-circle' : it.warn ? 'alert' : (it.icon || 'host')" [size]="18" [tone]="on(it.id) ? 'accent' : (it.warn ? 'warning' : 'muted')" />
            <span class="ct"><b>{{ it.title }}</b>@if (place(it.id); as n) { <span class="rec">{{ n }}º</span> } @else if (it.tag) { <span class="rec">{{ it.tag }}</span> }
              @if (it.note) { <small>{{ it.note }}</small> }
              @if (trying(it.id)?.text; as t) { <small class="heard">{{ t }}</small> }</span>
          </button>
          @if (trial()) {
            @if (trying(it.id)?.busy) { <span class="try"><hx-spinner /></span> }
            @else {
              <button type="button" class="try" [class.rec]="!!trying(it.id)?.recording" (click)="tried.emit(it.id)"
                      [attr.aria-label]="trial() === 'voce' ? 'Ascolta ' + it.title : (trying(it.id)?.recording ? 'Ferma e prova' : 'Prova a parlare con ' + it.title)">
                <hx-icon [name]="trying(it.id)?.recording || trying(it.id)?.playing ? 'stop' : (trial() === 'voce' ? 'play' : 'mic')" [size]="16" />
              </button>
            }
          }
        </div>
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
    .tools { display: flex; gap: 8px; }
    .tools .search { flex: 1; min-width: 0; }
    .lang { flex: none; width: auto; max-width: 45%; }
    .search { display: flex; align-items: center; gap: 8px; border: 1px solid var(--border); border-radius: var(--radius-md); padding: 0 10px; background: var(--surface); }
    .search input { border: 0; background: none; box-shadow: none; padding-left: 0; flex: 1; min-width: 0; }
    .choices { display: flex; flex-direction: column; gap: 6px; }
    .item { display: flex; gap: 6px; align-items: stretch; }
    .try { flex: none; display: grid; place-items: center; width: 42px; border: 1px solid var(--border); border-radius: var(--radius-md);
           background: var(--surface); color: var(--text-2); }
    .try:hover { border-color: var(--border-strong); color: var(--accent); }
    .try.rec { border-color: var(--danger); color: var(--danger); }
    .heard { color: var(--text-2) !important; }
    .choice { display: flex; gap: 10px; align-items: flex-start; text-align: left; padding: 11px 12px; border: 1px solid var(--border);
              border-radius: var(--radius-md); background: var(--surface); color: var(--text); width: 100%;
              transition: border-color var(--dur-fast) var(--ease), background var(--dur-fast) var(--ease); }
    .choice:hover { border-color: var(--border-strong); }
    .choice.sel { border-color: var(--accent); background: var(--accent-soft); }
    .ct { display: flex; flex-direction: column; gap: 2px; flex: 1; min-width: 0; }
    .ct b { font-weight: 600; font-size: 14px; overflow-wrap: anywhere; }
    .ct small { color: var(--text-3); font-size: 12px; line-height: 1.4; }
    .rec { align-self: flex-start; font-size: 11px; font-weight: 600; color: var(--accent); background: var(--accent-soft); padding: 1px 7px; border-radius: var(--radius-full); }
    .chips { display: flex; gap: 6px; flex-wrap: wrap; }
    .chip { font-size: 12px; padding: 3px 10px; border-radius: var(--radius-full); border: 1px solid var(--border); background: var(--surface); color: var(--text-2); }
    .chip.on { border-color: var(--accent); background: var(--accent-soft); color: var(--accent); font-weight: 600; }
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
  /** A try button on every card: «voce» = hear it, «ascolto» = speak and see what it understood ('' = none). */
  trial = input<'voce' | 'ascolto' | ''>('');
  /** The try in progress or just done, by card id. */
  trialState = input<{ id: string; busy?: boolean; recording?: boolean; playing?: boolean; text?: string } | null>(null);
  tried = output<string>();
  trying(id: string) { const t = this.trialState(); return t && t.id === id ? t : null; }
  /** Chips only on lists long enough to need them (the search box is always there: every list looks the same). */
  readonly searchFrom = 6;
  query = signal('');
  all = signal(false);
  /** The filter chip on ('' = all). */
  group = signal('');
  /** Chips: the groups of the list in order of first appearance (at most 8; the rest go under «Tutti»). */
  groups = computed(() => [...new Set(this.items().map(i => i.group || '').filter(Boolean))].slice(0, 8));

  /** The language selector: the languages of the list in order of appearance (only when the items have one). */
  lang = signal('');
  langs = computed(() => {
    const seen = new Map<string, string>();
    for (const i of this.items()) if (i.lang && !seen.has(i.lang)) seen.set(i.lang, i.langLabel || i.lang);
    return [...seen].map(([id, label]) => ({ id, label }));
  });
  /** The language shown: the one picked, else the chosen item's, else the first of the list. */
  langNow = computed(() => {
    const ls = this.langs().map(l => l.id);
    if (ls.includes(this.lang())) return this.lang();
    const sel = this.items().find(i => this.on(i.id) && i.lang);
    return sel?.lang || ls[0] || '';
  });

  on(id: string): boolean { return this.multi() ? this.chosen().includes(id) : id === this.selected(); }
  /** The place of a chosen card when more than one is chosen (0 = none). */
  place(id: string): number { return this.multi() && this.chosen().length > 1 ? this.chosen().indexOf(id) + 1 : 0; }

  filtered = computed(() => {
    const q = this.query().trim().toLowerCase();
    const g = this.groups().includes(this.group()) ? this.group() : '';
    const l = this.langs().length > 1 ? this.langNow() : '';
    const byLang = l ? this.items().filter(i => !i.lang || i.lang === l) : this.items();
    const list = g ? byLang.filter(i => i.group === g) : byLang;
    return q ? list.filter(i => `${i.title} ${i.note || ''}`.toLowerCase().includes(q)) : list;
  });
  visible = computed(() => {
    const list = this.filtered();
    if (this.all() || this.query().trim() || this.group() || list.length <= this.limit()) return list;
    const head = list.slice(0, this.limit());
    const sel = list.filter(i => this.on(i.id) && !head.includes(i));   // the chosen ones always stay in sight
    return [...head, ...sel];
  });
  hidden = computed(() => this.filtered().length - this.visible().length);
}
