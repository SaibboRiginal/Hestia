import { ChangeDetectionStrategy, Component, ElementRef, HostListener, OnDestroy, OnInit, computed, inject, signal, viewChild } from '@angular/core';
import { ActivatedRoute, ParamMap, Router } from '@angular/router';
import { Subscription } from 'rxjs';
import { BadgeComponent, IconComponent, ResizeHandleComponent, savedWidth } from '../../ui';
import { ModuleInfo } from './central-settings.api';
import { CentralSettingsStore, moduleLabel } from './central-settings.store';
import { PERSONAL_SECTIONS, PersonalSettingsComponent, personalHits } from './personal-settings.component';
import { HEALTH, SystemSettingsComponent } from './system-settings.component';
import { PluginSettingsComponent } from '../plugins/plugin-settings.component';
import { TransferSettingsComponent } from './transfer-settings.component';

/**
 * Impostazioni, VS Code-like: one search box over every setting (personal and system), a
 * resizable sidebar (Personali sections, then Sistema: overview + modules with their state and
 * the number of matches while searching), and the content in the same rows everywhere.
 * Deep links: /settings?tab=system&module=oracle · /settings?section=assistente · /settings?key=<central setting>
 * and /settings?section=messaggi&row=notice_mode: the last two open the right view, scroll to that one setting and
 * highlight it (the target of every <hx-setting-link>, the palette and the modules' host.openSetting).
 */

/** Central settings that Personali edits with its own row. */
const KEY_ROWS: Record<string, string> = { 'oracle.chat.tone': 'tone', 'oracle.chat.instructions': 'instructions' };

@Component({
  selector: 'app-settings-page',
  imports: [BadgeComponent, IconComponent, ResizeHandleComponent, PersonalSettingsComponent, SystemSettingsComponent, PluginSettingsComponent, TransferSettingsComponent],
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
        <div class="head">Dati</div>
        <button class="item" [class.on]="!searching() && view() === 'transfer'" (click)="open('transfer')">
          <hx-icon name="download" [size]="15" /><span class="hx-grow">Esporta e importa</span>
        </button>
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
        } @else if (view() === 'transfer') {
          <app-transfer-settings />
        } @else if (view() === 'p:plugin') {
          <app-plugin-settings />
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

  private sub?: Subscription;
  private host = inject(ElementRef<HTMLElement>);

  ngOnInit() {
    void this.store.init();
    this.sub = this.route.queryParamMap.subscribe(p => void this.follow(p));
  }
  ngOnDestroy() { this.sub?.unsubscribe(); this.store.stopPolling(); }

  /** The address decides the view (also while the page is open: a shortcut from the palette lands here). */
  private async follow(p: ParamMap) {
    const key = p.get('key'), module = p.get('module'), section = p.get('section'), row = p.get('row');
    if (key) { await this.goToKey(key); return; }
    const view = module ? module : p.get('tab') === 'system' ? 'system' : p.get('tab') === 'transfer' ? 'transfer'
      : section && PERSONAL_SECTIONS.some(s => s.id === section) ? 'p:' + section : '';
    if (view && view !== this.view()) this.open(view, false);
    if (row) {
      this.flash(`[data-row="${row}"]`);
      void this.router.navigate([], { queryParams: { row: null }, queryParamsHandling: 'merge', replaceUrl: true });
    }
  }

  /** One central setting: its module (or Personali for a personal one), filters out of the way, highlighted. */
  private async goToKey(key: string) {
    await this.store.init();
    if (!this.store.items().length) await this.store.loadItems();
    const item = this.store.items().find(i => i.key === key);
    const personal = item?.scope === 'user';
    const module = item?.module ?? key.split('.')[0];
    if (item) this.store.reveal(item);
    const view = personal ? 'p:assistente' : this.store.modules().some(m => m.module === module) ? module : 'system';
    this.open(view, false);
    const queryParams = personal ? { key: null, section: 'assistente', tab: null, module: null }
      : { key: null, tab: 'system', module: view === 'system' ? null : view, section: null };
    void this.router.navigate([], { queryParams, queryParamsHandling: 'merge', replaceUrl: true });
    if (item) this.flash(KEY_ROWS[key] ? `[data-row="${KEY_ROWS[key]}"]` : `[data-setting="${key}"]`);
  }

  /** Scrolls to an element of the content once it is drawn and marks it for a moment. */
  private flash(selector: string, tries = 30) {
    const el = this.host.nativeElement.querySelector(selector) as HTMLElement | null;
    if (!el) { if (tries > 0) setTimeout(() => this.flash(selector, tries - 1), 100); return; }
    el.scrollIntoView({ block: 'center', behavior: 'smooth' });
    el.classList.add('hx-flash');
    setTimeout(() => el.classList.remove('hx-flash'), 3600);
  }

  open(view: string, navigate = true) {
    this.view.set(view);
    this.store.select(view === 'system' || view === 'transfer' || view.startsWith('p:') ? null : view);
    if (!navigate) return;
    const queryParams = view === 'transfer' ? { tab: 'transfer', module: null, section: null } : view.startsWith('p:') ? { section: view.slice(2), tab: null, module: null }
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
