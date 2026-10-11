import { ChangeDetectionStrategy, Component, ElementRef, HostListener, OnDestroy, OnInit, computed, inject, signal, viewChild } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { BadgeComponent, IconComponent, ResizeHandleComponent, savedWidth } from '../../ui';
import { ModuleInfo } from './central-settings.api';
import { CentralSettingsStore, moduleLabel } from './central-settings.store';
import { PERSONAL_SECTIONS, PersonalSettingsComponent, personalHits } from './personal-settings.component';
import { HEALTH, SystemSettingsComponent } from './system-settings.component';

/**
 * Impostazioni, VS Code-like: one search box over every setting (personal and system), a
 * resizable sidebar (Personali sections, then Sistema: overview + modules with their state and
 * the number of matches while searching), and the content in the same rows everywhere.
 * Deep links: /settings?tab=system&module=oracle · /settings?section=assistente
 */
@Component({
  selector: 'app-settings-page',
  imports: [BadgeComponent, IconComponent, ResizeHandleComponent, PersonalSettingsComponent, SystemSettingsComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <header class="top">
      <h1>Impostazioni</h1>
      <label class="search">
        <hx-icon name="search" [size]="16" />
        <input #q class="hx-input" type="search" placeholder="Cerca in tutte le impostazioni (Ctrl+F)" [value]="store.query()"
               (input)="store.search($any($event.target).value)" (keydown.escape)="store.search('')" aria-label="Cerca impostazioni" />
        @if (store.query()) { <span class="count">{{ totalHits() === 1 ? '1 risultato' : totalHits() + ' risultati' }}</span> }
      </label>
    </header>

    <div class="layout">
      <aside class="side" [style.width.px]="width()">
        <div class="head">Personali</div>
        @for (s of personal; track s.id) {
          <button class="item" [class.on]="!searching() && view() === 'p:' + s.id" [class.none]="searching() && !pHits().get(s.id)"
                  (click)="open('p:' + s.id)">
            <hx-icon [name]="s.icon" [size]="15" /><span class="hx-grow">{{ s.label }}</span>
            @if (searching() && pHits().get(s.id)) { <span class="n">{{ pHits().get(s.id) }}</span> }
          </button>
        }
        <div class="head">Sistema</div>
        <button class="item" [class.on]="!searching() && view() === 'system'" (click)="open('system')">
          <hx-icon name="grid" [size]="15" /><span class="hx-grow">Panoramica</span>
          @if (store.proposals().length) { <hx-badge tone="accent" title="Proposte in attesa">{{ store.proposals().length }}</hx-badge> }
        </button>
        @for (m of store.modules(); track m.module) {
          <button class="item" [class.on]="!searching() && view() === m.module" [class.none]="searching() && !store.hitsByModule().get(m.module)"
                  (click)="open(m.module)">
            <span class="dot" [attr.data-tone]="health(m).tone" [title]="health(m).label"></span>
            <span class="hx-grow">{{ name(m.module) }}</span>
            @if (searching()) { @if (store.hitsByModule().get(m.module); as n) { <span class="n">{{ n }}</span> } }
            @else if (m.pending_proposals) { <hx-badge tone="accent" title="Proposte in attesa">{{ m.pending_proposals }}</hx-badge> }
            @else { <span class="n">{{ m.definitions }}</span> }
          </button>
        }
      </aside>
      <hx-resize [(width)]="width" [inline]="true" [min]="180" [max]="420" [def]="240" key="settings-side" />

      <main class="main">
        @if (searching()) {
          @if (pTotal()) {
            <h3 class="sec">Personali</h3>
            <app-personal-settings [query]="store.query()" />
          }
          @if (store.visible().length || store.hiddenAdvanced() || store.onlyModified() || !pTotal()) { <app-system-settings /> }
        } @else if (view().startsWith('p:')) {
          <app-personal-settings [section]="view().slice(2)" />
        } @else {
          <app-system-settings />
        }
      </main>
    </div>`,
  styles: [`
    :host { display: flex; flex-direction: column; flex: 1; min-height: 0; }
    .top { display: flex; align-items: center; gap: 18px; padding: 16px 24px 14px 24px; border-bottom: 1px solid var(--border); flex-shrink: 0; flex-wrap: wrap; }
    @media (max-width: 860px) { .top { padding-left: 56px; } }
    h1 { font-family: var(--font-serif); font-weight: 500; font-size: 22px; color: var(--text); }
    .search { position: relative; flex: 1; min-width: 220px; max-width: 720px; display: block; }
    .search hx-icon { position: absolute; left: 11px; top: 50%; transform: translateY(-50%); color: var(--text-3); }
    .search .hx-input { padding-left: 34px; padding-right: 96px; height: 38px; }
    .count { position: absolute; right: 12px; top: 50%; transform: translateY(-50%); font-size: 12px; color: var(--text-3); }
    .layout { flex: 1; display: flex; min-height: 0; }
    .side { flex-shrink: 0; border-right: 1px solid var(--border); padding: 12px 10px; overflow-y: auto;
            display: flex; flex-direction: column; gap: 1px; }
    .head { font-size: 11.5px; font-weight: 600; letter-spacing: .04em; text-transform: uppercase; color: var(--text-3); padding: 12px 10px 6px; }
    .head:first-child { padding-top: 2px; }
    .item { display: flex; align-items: center; gap: 9px; padding: 7px 10px; border-radius: var(--radius-md); font-size: 13.5px;
            color: var(--text-2); text-align: left; }
    .item:hover { background: var(--surface-2); color: var(--text); }
    .item.on { background: var(--accent-soft); color: var(--accent); }
    .item.none { opacity: .45; }
    .n { font-size: 11.5px; color: var(--text-3); font-variant-numeric: tabular-nums; }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--text-3); flex-shrink: 0; margin: 0 3px; }
    .dot[data-tone=success] { background: var(--success); }
    .dot[data-tone=warning] { background: var(--warning); }
    .dot[data-tone=danger] { background: var(--danger); }
    .main { flex: 1; min-width: 0; overflow-y: auto; padding: 16px 24px 40px; display: flex; flex-direction: column; gap: 14px; }
    .sec { font-family: var(--font-serif); font-size: 17px; font-weight: 500; }
    @media (max-width: 760px) {
      .layout { flex-direction: column; }
      .side { width: auto !important; flex-direction: row; overflow-x: auto; border-right: 0; border-bottom: 1px solid var(--border); padding: 8px; }
      .head { display: none; }
      .item { white-space: nowrap; }
      .main { padding: 14px 14px 40px; }
    }
  `],
})
export class SettingsPageComponent implements OnInit, OnDestroy {
  readonly store = inject(CentralSettingsStore);
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private searchBox = viewChild<ElementRef<HTMLInputElement>>('q');

  readonly personal = PERSONAL_SECTIONS;
  /** 'p:<section>' (personal) · 'system' (overview) · module id */
  readonly view = signal('p:aspetto');
  readonly searching = computed(() => !!this.store.query().trim());
  readonly pHits = computed(() => {
    const hits = personalHits(this.store.query());
    const extra = this.store.personalExtra().length;
    if (extra) hits.set('assistente', (hits.get('assistente') ?? 0) + extra);
    return hits;
  });
  readonly pTotal = computed(() => this.store.onlyModified() ? 0 : [...this.pHits().values()].reduce((a, b) => a + b, 0));
  readonly totalHits = computed(() => this.pTotal() + this.store.visible().length);

  ngOnInit() {
    const p = this.route.snapshot.queryParamMap;
    const module = p.get('module'), section = p.get('section');
    if (module) this.open(module, false);
    else if (p.get('tab') === 'system') this.open('system', false);
    else if (section && PERSONAL_SECTIONS.some(s => s.id === section)) this.open('p:' + section, false);
    void this.store.init();
  }
  ngOnDestroy() { this.store.stopPolling(); }

  open(view: string, navigate = true) {
    this.view.set(view);
    this.store.select(view === 'system' || view.startsWith('p:') ? null : view);
    if (!navigate) return;
    const queryParams = view.startsWith('p:') ? { section: view.slice(2), tab: null, module: null }
      : { tab: 'system', module: view === 'system' ? null : view, section: null };
    void this.router.navigate([], { queryParams, queryParamsHandling: 'merge', replaceUrl: true });
  }

  name = moduleLabel;
  health(m: ModuleInfo) { return HEALTH[m.health ?? 'unknown'] ?? HEALTH['unknown']; }

  /** Ctrl/⌘+F focuses the settings search (like VS Code). */
  @HostListener('document:keydown', ['$event'])
  onKey(e: KeyboardEvent) {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'f') {
      e.preventDefault();
      this.searchBox()?.nativeElement.focus();
      this.searchBox()?.nativeElement.select();
    }
  }

  /** Sidebar width (<hx-resize>), kept per browser. */
  readonly width = signal(savedWidth('settings-side', 240));
}
