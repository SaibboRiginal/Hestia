import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router, RouterLink } from '@angular/router';
import { filter, map, startWith } from 'rxjs';
import { EmptyStateComponent, SettingLinkComponent, SpinnerComponent } from '../../ui';
import { CentralSettingsStore } from '../settings/central-settings.store';
import { PluginOutletComponent } from './plugin-outlet.component';
import { PluginsService } from './plugins.service';
import { NavService } from '../../layout/nav.service';
import { IconComponent } from '../../ui';
import { TrPipe } from '../../core/i18n';

/** A module's page (SPEC §4.3): the plugin element fills the page; the shell gives only the frame, and one gear in
 *  the top right corner that opens the settings of the module the page belongs to (when it has any): the same
 *  shortcut on every module page, drawn once here (dossier docs/work/2026-11-12-context-and-shortcuts §3.3). */
@Component({
  selector: 'app-plugin-page',
  imports: [TrPipe, RouterLink, IconComponent, PluginOutletComponent, EmptyStateComponent, SettingLinkComponent, SpinnerComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (!plugins.catalog()) {
      <div class="center">@if (plugins.catalogError()) { <hx-empty icon="offline"  [title]="'Module catalog not reachable' | tr" /> } @else { <hx-spinner /> }</div>
    } @else {
      @if (match(); as m) {
        @if (nav.family(); as f) {
          @if (f.tabs.length) {
            <nav class="tabs" [attr.aria-label]="f.top.label">
              @for (t of f.tabs; track t.id) {
                <a [routerLink]="t.link" [class.on]="t.id === f.active" [attr.aria-current]="t.id === f.active ? 'page' : null">
                  <hx-icon [name]="t.icon" [size]="15" />{{ t.label }}
                  @if (t.badge) { <b>{{ t.badge > 99 ? '99+' : t.badge }}</b> }
                </a>
              }
            </nav>
          }
        }
        @if (hasSettings()) {
          <hx-setting-link class="gear" [module]="route().module" label="" [title]="('Settings of ' | tr) + moduleTitle()" />
        }
        <hx-plugin-outlet [module]="route().module" [element]="m.page.element" [ctx]="ctx()" />
      } @else {
        <div class="center"><hx-empty icon="puzzle"  [title]="'Page not found' | tr">
          {{ moduleTitle() }} {{ "doesn't have this page, or the module is not installed." | tr }}</hx-empty></div>
      }
    }`,
  styles: [`
    :host { display: flex; flex-direction: column; flex: 1; min-height: 0; overflow: auto; position: relative;
            --head-inset-end: 34px; }   /* the SDK keeps the title line clear of the gear */
    .gear { position: absolute; top: 18px; right: 14px; z-index: 5; }
    /* Sub-pages are tabs of their page (docs/work/2026-11-27-webui-rethink §3.4), the same strip for every module. */
    .tabs { display: flex; gap: 2px; padding: 10px 56px 0 24px; padding-left: max(24px, var(--head-inset, 0px)); border-bottom: 1px solid var(--border);
            overflow-x: auto; flex-shrink: 0; scrollbar-width: none; }
    .tabs a { display: inline-flex; align-items: center; gap: 6px; padding: 8px 11px; border-bottom: 2px solid transparent; margin-bottom: -1px;
              color: var(--text-2); white-space: nowrap; text-decoration: none; font-size: 13.5px; border-radius: var(--radius-sm) var(--radius-sm) 0 0; }
    .tabs a:hover { color: var(--text); background: var(--surface-2); }
    .tabs a.on { color: var(--text); border-bottom-color: var(--accent); font-weight: 600; }
    .tabs a.on hx-icon { color: var(--accent); }
    .tabs b { min-width: 16px; height: 16px; padding: 0 4px; border-radius: var(--radius-full); background: var(--accent); color: var(--accent-contrast); font: 600 10px/16px var(--font-sans); text-align: center; }
    :host:has(.tabs) .gear { top: 12px; }
    :host:has(.tabs) { --head-inset: 0px; }
    @media (max-width: 860px) { .tabs { padding: 8px 44px 0 52px; } }
    @media (max-width: 860px) { .gear { top: 14px; right: 6px; } }
    .center { flex: 1; display: grid; place-items: center; padding: 24px; }
    /* Phone: the shell's menu button sits on the title line of the plugin page (SDK .page > :first-child reads
       --head-inset), not on a row of its own. */
    @media (max-width: 860px) { :host { --head-inset: 44px; } }
  `],
})
export class PluginPageComponent {
  plugins = inject(PluginsService);
  nav = inject(NavService);
  private router = inject(Router);
  private settings = inject(CentralSettingsStore);

  constructor() {
    if (!this.settings.modules().length) void this.settings.loadModules();   // which modules have settings
  }
  readonly hasSettings = computed(() => this.settings.modulesById().has(this.route().module));

  private url = toSignal(this.router.events.pipe(
    filter(e => e instanceof NavigationEnd), map(() => this.router.url), startWith(this.router.url)), { initialValue: this.router.url });

  readonly route = computed(() => {
    const tree = this.router.parseUrl(this.url());
    const segs = tree.root.children['primary']?.segments.map(s => s.path) ?? [];
    return { module: decodeURIComponent(segs[1] ?? ''), path: segs.slice(2).join('/'), query: { ...tree.queryParams } as Record<string, string> };
  });
  readonly match = computed(() => (this.plugins.catalog(), this.plugins.matchPage(this.route().module, this.route().path)));
  readonly moduleTitle = computed(() => this.plugins.modules().get(this.route().module)?.title ?? this.route().module);
  readonly ctx = computed(() => {
    const m = this.match();
    return m ? this.plugins.context(this.route().module, 'page', m.page.local_id, { params: m.params, query: this.route().query }) : {};
  });
}
