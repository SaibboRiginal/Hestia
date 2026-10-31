import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { map } from 'rxjs';
import { UI, DialogService, ToastService } from '../../ui';
import { uid } from '../../core/uid';
import { AssistantService } from '../../services/assistant.service';
import { LiveVoiceService } from '../../services/live-voice.service';
import { PluginOutletComponent } from './plugin-outlet.component';
import { QuickStripComponent } from './quick-strip.component';
import { AdessoRowComponent } from './adesso-row.component';
import { SetupCardComponent } from '../setup/setup-card.component';
import { PluginsService, SIZE_SPAN } from './plugins.service';
import { Dashboard, DashboardItem, PluginWidget, WidgetSize } from './plugins.types';

const SIZE_LABEL: Record<WidgetSize, string> = { s: 'Piccolo', m: 'Medio', l: 'Grande', xl: 'Intero' };

/**
 * Home and dashboards (SPEC §4.6, §4.8): «Adesso» and quick actions on top (Home), widgets of every module in a grid.
 * Edit mode: add from the catalog, drag to reorder, size, per-widget params and title, remove.
 * Saved as this client's setting `webui.dashboards` (Themis history/undo).
 */
@Component({
  selector: 'app-dashboard-page',
  imports: [...UI, FormsModule, RouterLink, PluginOutletComponent, QuickStripComponent, AdessoRowComponent, SetupCardComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <hx-page-header [title]="current()?.title || 'Home'" [subtitle]="subtitle()">
      @if (editing()) {
        <button hx-btn variant="secondary" icon="plus" (click)="adding.set(true)">Aggiungi widget</button>
        <button hx-btn variant="ghost" (click)="cancelEdit()">Annulla</button>
        <button hx-btn variant="primary" icon="check" [loading]="saving()" (click)="saveEdit()">Salva</button>
      } @else {
        @if (isHome()) {
          <button hx-btn [variant]="live.on ? 'primary' : 'ghost'" icon="waveform" (click)="toggleLive()" [attr.aria-pressed]="live.on"
                  [attr.aria-label]="live.on ? 'Ferma Parla' : 'Parla'"
                  title="Parla con Hestia a voce (Ctrl+Shift+Spazio)"><span class="lbl">{{ live.on ? 'Ferma' : 'Parla' }}</span></button>
        }
        <button hx-btn variant="ghost" icon="sparkle" class="ask" (click)="askHestia()">Crea con Hestia</button>
        <button hx-btn variant="secondary" icon="edit" (click)="startEdit()">Modifica</button>
        <hx-menu [items]="menuItems()" (select)="onMenu($event)">
          <button hx-btn variant="ghost" icon="more" iconOnly aria-label="Altre azioni" trigger></button>
        </hx-menu>
      }
    </hx-page-header>

    @if (plugins.dashboards().length > 1) {
      <nav class="tabs" aria-label="Dashboard">
        @for (d of plugins.dashboards(); track d.id) {
          <a [routerLink]="d.id === 'home' ? '/home' : '/d/' + d.id" [class.on]="d.id === current()?.id">
            {{ d.title }}@if (d.created_by === 'oracle') { <hx-icon name="sparkle" [size]="12" title="Creata da Hestia" /> }
          </a>
        }
      </nav>
    }

    <div class="body">
      @if (isHome() && !editing()) { <hx-setup-card /><hx-adesso-row /><hx-quick-strip /> }

      @if (!plugins.catalog() && !plugins.catalogError()) {
        <div class="center"><hx-spinner /></div>
      } @else if (!items().length) {
        <hx-empty icon="grid" title="Nessun widget">
          I moduli con un'interfaccia mettono qui i loro widget. Puoi aggiungerli tu o chiedere a Hestia di comporre una dashboard.
          <button hx-btn variant="primary" icon="plus" (click)="startEdit(); adding.set(true)">Aggiungi widget</button>
        </hx-empty>
      } @else {
        <div class="grid" [class.editing]="editing()">
          @for (it of items(); track it.widget + $index; let i = $index) {
            @let w = plugins.widget(it.widget);
            <article class="cell" [style.grid-column]="'span ' + span(it).c" [style.grid-row]="'span ' + span(it).r"
                     [attr.draggable]="editing()" (dragstart)="dragFrom = i" (dragover)="$event.preventDefault()" (drop)="dropOn(i)"
                     [class.offline]="w && !w.online" [class.empty]="!editing() && empty().has(it.widget + i)"
                     (hestia-widget-empty)="setEmpty(it.widget + i, $any($event).detail)">
              <header>
                @if (editing()) { <hx-icon name="selector" [size]="15" class="grip" title="Trascina per spostare" /> }
                <span class="wt">{{ it.title || w?.label || it.widget }}</span>
                @if (w && !w.online) { <hx-badge tone="warning">offline</hx-badge> }
                @if (!editing() && w?.open_page) {
                  <a class="open" [routerLink]="plugins.link(w!.module, w!.open_page)" title="Apri"><hx-icon name="chevron-right" [size]="15" /></a>
                }
                @if (editing()) {
                  <select class="hx-select sz" [ngModel]="it.size" (ngModelChange)="setSize(i, $event)" aria-label="Misura">
                    @for (s of (w?.sizes ?? ['m']); track s) { <option [value]="s">{{ sizeLabel[s] }}</option> }
                  </select>
                  <button hx-btn variant="ghost" size="sm" icon="settings" iconOnly aria-label="Impostazioni widget" (click)="configure(i)"></button>
                  <button hx-btn variant="ghost" size="sm" icon="trash" iconOnly aria-label="Rimuovi" (click)="remove(i)"></button>
                }
              </header>
              <div class="wb">
                @if (w) {
                  <hx-plugin-outlet [module]="w.module" [element]="w.element" [ctx]="ctxFor(w, it)" />
                } @else {
                  <div class="gone">Widget non più disponibile</div>
                }
              </div>
            </article>
          }
        </div>
      }
    </div>

    <hx-modal [open]="adding()" title="Aggiungi widget" size="lg" (closed)="adding.set(false)">
      <input class="hx-input" placeholder="Cerca…" [ngModel]="filter()" (ngModelChange)="filter.set($event)" aria-label="Cerca widget">
      @for (g of catalogGroups(); track g.module) {
        <h3 class="gh">{{ g.title }}</h3>
        <div class="cat">
          @for (w of g.widgets; track w.id) {
            <button class="ci" (click)="add(w)">
              <span class="cl">{{ w.label }}</span>
              @if (w.help) { <span class="ch">{{ w.help }}</span> }
              <span class="cs">{{ sizeLabel[w.size] }}@if (!w.online) { · offline }</span>
            </button>
          }
        </div>
      } @empty { <hx-empty icon="puzzle" title="Nessun widget disponibile">Nessun modulo con interfaccia è registrato.</hx-empty> }
    </hx-modal>

    <hx-modal [open]="!!nameDlg()" [title]="nameDlg()?.mode === 'new' ? 'Nuova dashboard' : 'Rinomina dashboard'" size="sm" (closed)="nameDlg.set(null)">
      @if (nameDlg(); as n) {
        <hx-field label="Nome"><input class="hx-input" [ngModel]="n.value" (ngModelChange)="nameDlg.set({ mode: n.mode, value: $event })"
          (keydown.enter)="confirmName()" autofocus></hx-field>
      }
      <ng-container footer>
        <button hx-btn variant="ghost" (click)="nameDlg.set(null)">Annulla</button>
        <button hx-btn variant="primary" [disabled]="!nameDlg()?.value?.trim()" (click)="confirmName()">{{ nameDlg()?.mode === 'new' ? 'Crea' : 'Rinomina' }}</button>
      </ng-container>
    </hx-modal>

    <hx-modal [open]="cfgIndex() !== null" title="Impostazioni widget" size="sm" (closed)="cfgIndex.set(null)">
      @if (cfgIndex() !== null) {
        <div class="form">
          <hx-field label="Titolo" hint="Vuoto = quello del modulo"><input class="hx-input" [(ngModel)]="cfgTitle"></hx-field>
          @for (p of cfgParams(); track p.name) {
            <hx-field [label]="p.spec.label">
              @if (p.spec.type === 'enum') {
                <select class="hx-select" [(ngModel)]="cfgValues[p.name]"><option value=""></option>
                  @for (o of p.spec.options ?? []; track o) { <option [value]="o">{{ o }}</option> }</select>
              } @else if (p.spec.type === 'int' || p.spec.type === 'float') {
                <input class="hx-input" type="number" [(ngModel)]="cfgValues[p.name]">
              } @else if (p.spec.type === 'bool') {
                <input class="hx-check" type="checkbox" [(ngModel)]="cfgValues[p.name]">
              } @else {
                <input class="hx-input" [(ngModel)]="cfgValues[p.name]">
              }
            </hx-field>
          }
        </div>
      }
      <ng-container footer>
        <button hx-btn variant="ghost" (click)="cfgIndex.set(null)">Annulla</button>
        <button hx-btn variant="primary" (click)="applyConfig()">Applica</button>
      </ng-container>
    </hx-modal>`,
  styles: [`
    :host { display: flex; flex-direction: column; flex: 1; min-height: 0; }
    .ask { color: var(--accent); }
    .tabs { display: flex; gap: 4px; padding: 8px 24px 0; border-bottom: 1px solid var(--border); overflow-x: auto; flex-shrink: 0; }
    .tabs a { padding: 6px 10px; border-bottom: 2px solid transparent; color: var(--text-2); white-space: nowrap; text-decoration: none;
              display: inline-flex; align-items: center; gap: 5px; margin-bottom: -1px; }
    .tabs a.on { color: var(--text); border-bottom-color: var(--accent); font-weight: 500; }
    .body { flex: 1; overflow: auto; padding: 18px 24px 32px; display: flex; flex-direction: column; gap: 18px; }
    .center { display: grid; place-items: center; padding: 40px; }
    .grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); grid-auto-rows: 170px; gap: 14px; grid-auto-flow: dense; }
    .cell { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-lg); display: flex; flex-direction: column;
            min-height: 0; overflow: hidden; }
    .cell.offline { opacity: .75; }
    /* a widget with nothing to show (SDK markEmpty) takes one cell, its text muted */
    .cell.empty { grid-column: span 1 !important; grid-row: span 1 !important; }
    .cell.empty .wb { color: var(--text-3); }
    .editing .cell { border-style: dashed; cursor: grab; }
    header { display: flex; align-items: center; gap: 6px; padding: 10px 12px 4px 14px; min-height: 38px; }
    .wt { flex: 1; min-width: 0; font-weight: 600; font-size: 13.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .open { color: var(--text-3); display: inline-flex; } .open:hover { color: var(--accent); }
    .grip { color: var(--text-3); }
    .sz { width: auto; padding: 3px 24px 3px 8px; font-size: 12.5px; }
    .wb { flex: 1; min-height: 0; overflow: auto; display: flex; flex-direction: column; padding: 4px 12px 12px; }
    .gone { margin: auto; color: var(--text-3); font-size: 13px; }
    .gh { font-size: 13px; color: var(--text-2); margin: 14px 0 6px; font-weight: 600; }
    .cat { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 8px; }
    .ci { text-align: left; border: 1px solid var(--border); border-radius: var(--radius-md); padding: 10px 12px; background: var(--surface);
          display: flex; flex-direction: column; gap: 3px; }
    .ci:hover { border-color: var(--accent); background: var(--accent-soft); }
    .cl { font-weight: 500; } .ch { font-size: 12px; color: var(--text-3); } .cs { font-size: 11.5px; color: var(--text-3); }
    .form { display: flex; flex-direction: column; gap: 12px; }
    @media (max-width: 1100px) { .grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
    @media (max-width: 860px) {
      hx-page-header { padding-left: 56px; }
      .ask, .lbl { display: none; }
      .body { padding: 14px 12px 28px; }
      .tabs { padding: 6px 12px 0; }
      .grid { grid-template-columns: minmax(0, 1fr); grid-auto-rows: auto; }
      .cell { grid-column: span 1 !important; grid-row: span 1 !important; min-height: 150px; }
      .cell.empty { min-height: 0; }
    }
  `],
})
export class DashboardPageComponent {
  plugins = inject(PluginsService);
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private dialogs = inject(DialogService);
  private assistant = inject(AssistantService);
  private toasts = inject(ToastService);
  live = inject(LiveVoiceService);
  readonly sizeLabel = SIZE_LABEL;

  /** «Parla» from the Home (brainstorm C12): the live overlay follows you on every page. */
  toggleLive(): void {
    if (this.live.on) { this.live.stop(); return; }
    void this.live.start().then(() => { if (this.live.error()) this.toasts.error(this.live.error()); });
  }

  private routeId = toSignal(this.route.paramMap.pipe(map(p => p.get('id') ?? 'home')), { initialValue: 'home' });
  readonly current = computed<Dashboard | undefined>(() =>
    this.plugins.dashboards().find(d => d.id === this.routeId()) ?? (this.routeId() === 'home' ? this.plugins.dashboards()[0] : undefined));
  readonly isHome = computed(() => this.current()?.id === 'home');
  readonly editing = signal(false);
  readonly saving = signal(false);
  readonly draft = signal<DashboardItem[]>([]);
  readonly items = computed(() => this.editing() ? this.draft() : this.current()?.items ?? []);
  readonly subtitle = computed(() => {
    const d = this.current();
    if (!d) return 'Dashboard non trovata';
    if (d.created_by === 'oracle') return 'Creata da Hestia';
    return this.isHome() ? 'Le tue azioni rapide e i widget dei moduli' : '';
  });
  readonly menuItems = computed(() => [
    ...(this.phone() ? [{ id: 'ask', label: 'Crea con Hestia', icon: 'sparkle' }] : []),
    { id: 'new', label: 'Nuova dashboard', icon: 'plus' },
    ...(this.current() && !this.isHome() ? [{ id: 'rename', label: 'Rinomina', icon: 'edit' }, { id: 'delete', label: 'Elimina', icon: 'trash', danger: true }] : []),
  ]);

  readonly phone = signal(typeof matchMedia !== 'undefined' && matchMedia('(max-width: 860px)').matches);
  adding = signal(false);
  filter = signal('');
  nameDlg = signal<{ mode: 'new' | 'rename'; value: string } | null>(null);
  dragFrom = -1;
  cfgIndex = signal<number | null>(null);
  cfgTitle = '';
  cfgValues: Record<string, unknown> = {};

  readonly catalogGroups = computed(() => {
    const q = this.filter().trim().toLowerCase();
    const groups = new Map<string, PluginWidget[]>();
    for (const w of this.plugins.widgets()) {
      if (q && !`${w.label} ${w.help ?? ''} ${w.module}`.toLowerCase().includes(q)) continue;
      groups.set(w.module, [...(groups.get(w.module) ?? []), w]);
    }
    return [...groups.entries()].map(([module, widgets]) => ({ module, title: this.plugins.modules().get(module)?.title ?? module, widgets }));
  });
  readonly cfgParams = computed(() => {
    const i = this.cfgIndex();
    const w = i === null ? undefined : this.plugins.widget(this.draft()[i]?.widget);
    return Object.entries(w?.params ?? {}).map(([name, spec]) => ({ name, spec }));
  });

  span(it: DashboardItem) { return SIZE_SPAN[it.size] ?? SIZE_SPAN.m; }

  /** Cells whose widget said «nothing to show» (SDK `markEmpty`): one cell instead of their size. */
  readonly empty = signal<Set<string>>(new Set());
  setEmpty(key: string, isEmpty: boolean): void {
    const next = new Set(this.empty());
    if (isEmpty) next.add(key); else next.delete(key);
    this.empty.set(next);
  }

  private ctxCache = new Map<string, { key: string; ctx: object }>();
  /** Stable ctx object per item (a new object would re-set el.ctx on every change detection). */
  ctxFor(w: PluginWidget, it: DashboardItem): object {
    const key = JSON.stringify([it.size, it.params ?? {}, it.title ?? '', this.plugins.online()]);
    const id = `${w.id}|${JSON.stringify(it.params ?? {})}`;
    const hit = this.ctxCache.get(id);
    if (hit && hit.key === key) return hit.ctx;
    const ctx = this.plugins.context(w.module, 'widget', w.local_id, { params: it.params ?? {}, size: it.size, title: it.title });
    this.ctxCache.set(id, { key, ctx });
    return ctx;
  }

  // ── edit mode ────────────────────────────────────────────────────────
  startEdit() { this.draft.set([...(this.current()?.items ?? [])]); this.editing.set(true); }
  cancelEdit() { this.editing.set(false); this.adding.set(false); }

  add(w: PluginWidget) {
    this.draft.update(list => [...list, { widget: w.id, size: w.size }]);
    this.adding.set(false);
  }
  remove(i: number) { this.draft.update(list => list.filter((_, j) => j !== i)); }
  setSize(i: number, size: WidgetSize) { this.draft.update(list => list.map((it, j) => j === i ? { ...it, size } : it)); }
  dropOn(i: number) {
    const from = this.dragFrom;
    this.dragFrom = -1;
    if (from < 0 || from === i) return;
    this.draft.update(list => { const next = [...list]; const [moved] = next.splice(from, 1); next.splice(i, 0, moved); return next; });
  }

  configure(i: number) {
    const it = this.draft()[i];
    this.cfgTitle = it.title ?? '';
    this.cfgValues = { ...(it.params ?? {}) };
    this.cfgIndex.set(i);
  }
  applyConfig() {
    const i = this.cfgIndex();
    if (i === null) return;
    const params = Object.fromEntries(Object.entries(this.cfgValues).filter(([, v]) => v !== '' && v !== null && v !== undefined));
    this.draft.update(list => list.map((it, j) => j === i ? { ...it, title: this.cfgTitle.trim() || undefined, params } : it));
    this.cfgIndex.set(null);
  }

  async saveEdit() {
    const cur = this.current();
    if (!cur) return;
    this.saving.set(true);
    const items = this.draft();
    const kept = new Set(items.map(i => i.widget));
    // An automatic Home stays automatic, remembering the auto widgets the user removed.
    const dismissed = cur.auto
      ? [...new Set([...(cur.dismissed ?? []), ...cur.items.map(i => i.widget).filter(w => !kept.has(w))])].filter(w => !kept.has(w))
      : cur.dismissed;
    const next: Dashboard = { ...cur, items, dismissed };
    const list = this.plugins.dashboards().map(d => d.id === cur.id ? next : d);
    const ok = await this.plugins.saveDashboards(list);
    this.saving.set(false);
    if (ok) this.editing.set(false);
  }

  // ── dashboards ───────────────────────────────────────────────────────
  async onMenu(id: string) {
    const cur = this.current();
    if (id === 'ask') this.askHestia();
    else if (id === 'new') this.nameDlg.set({ mode: 'new', value: '' });
    else if (id === 'rename' && cur) this.nameDlg.set({ mode: 'rename', value: cur.title });
    else if (id === 'delete' && cur && !this.isHome()) {
      if (!(await this.dialogs.confirm(`Eliminare «${cur.title}»?`, 'I widget restano disponibili nel catalogo.', 'Elimina', true))) return;
      if (await this.plugins.saveDashboards(this.plugins.dashboards().filter(d => d.id !== cur.id))) await this.router.navigate(['/home']);
    }
  }

  async confirmName() {
    const n = this.nameDlg();
    const title = n?.value.trim();
    if (!n || !title) return;
    this.nameDlg.set(null);
    const cur = this.current();
    if (n.mode === 'rename' && cur) {
      await this.plugins.saveDashboards(this.plugins.dashboards().map(d => d.id === cur.id ? { ...d, title } : d));
      return;
    }
    const d: Dashboard = { id: uid().slice(0, 8), title, icon: 'grid', created_by: 'user', items: [] };
    if (await this.plugins.saveDashboards([...this.plugins.dashboards(), d])) {
      await this.router.navigate(['/d', d.id]);
      this.startEdit();
      this.adding.set(true);
    }
  }

  askHestia() {
    const cur = this.current();
    this.assistant.open({
      page: 'dashboard', intent: 'create', label: cur ? `Dashboard · ${cur.title}` : 'Dashboard',
      hints: { dashboard: cur?.id ?? 'home', widgets: this.plugins.widgets().length },
      suggestions: ['Creami una dashboard con le case a Milano', 'Aggiungi alla Home le statistiche delle case'],
    });
  }
}
