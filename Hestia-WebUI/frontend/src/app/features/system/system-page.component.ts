import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { RouterLink } from '@angular/router';
import { UI } from '../../ui';
import { PluginsService } from '../plugins/plugins.service';
import { PluginPage } from '../plugins/plugins.types';

/**
 * «Sistema» (brainstorm C13, W7): the one sidebar entry of the system modules. Every page of the core modules,
 * grouped by module with its counter, plus the ready-made *Sistema* dashboard. A page can still be pinned in the
 * sidebar from here (it then shows in «Fissati»).
 */
@Component({
  selector: 'app-system-page',
  imports: [...UI, RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <hx-page-header title="Sistema" subtitle="Come sta Hestia e come lavora: salute, modelli, notifiche, agenda, impostazioni, sviluppo">
      <a hx-btn size="sm" variant="ghost" icon="download" routerLink="/download">Download</a>
      @if (hasDashboard()) { <a hx-btn size="sm" icon="grid" routerLink="/d/sistema">Dashboard</a> }
    </hx-page-header>
    <div class="body">
      @for (g of groups(); track g.module) {
        <section class="mod">
          <h2><hx-icon [name]="g.icon" [size]="16" />{{ g.title }}
            @if (!g.online) { <hx-badge tone="warning">non raggiungibile</hx-badge> }</h2>
          @if (g.description) { <p class="d">{{ g.description }}</p> }
          <div class="pages">
            @for (p of g.pages; track p.id) {
              <div class="pg">
                <a class="open" [routerLink]="link(p)" [class.child]="!!p.parent">
                  <hx-icon [name]="p.icon || 'puzzle'" [size]="16" /><span>{{ p.label }}</span>
                  @if (badge(p); as n) { <b class="count">{{ n > 99 ? '99+' : n }}</b> }
                </a>
                <button class="pin" [class.on]="pinned(p)" (click)="plugins.toggleNavPin(p.id)"
                        [attr.aria-label]="pinned(p) ? 'Togli da Fissati' : 'Fissa nella barra laterale'" [attr.title]="pinned(p) ? 'In Fissati' : 'Fissa nella barra laterale'">
                  <hx-icon name="pin" [size]="14" /></button>
              </div>
            }
          </div>
        </section>
      } @empty {
        <hx-empty icon="host" title="Nessun modulo di sistema">I moduli compaiono qui quando si registrano.</hx-empty>
      }
    </div>`,
  styles: [`
    :host { display: flex; flex-direction: column; flex: 1; min-height: 0; }
    .body { flex: 1; overflow: auto; padding: 18px 24px 32px; display: grid; gap: 14px; grid-template-columns: repeat(auto-fill, minmax(min(100%, 300px), 1fr)); align-content: start; }
    .mod { border: 1px solid var(--border); border-radius: var(--radius-lg); background: var(--surface); padding: 12px 14px; display: flex; flex-direction: column; gap: 6px; }
    h2 { display: flex; align-items: center; gap: 8px; font-size: 15px; font-weight: 600; } h2 hx-icon { color: var(--accent); }
    .d { font-size: 12.5px; color: var(--text-3); }
    .pages { display: flex; flex-direction: column; gap: 2px; margin-top: 2px; }
    .pg { display: flex; align-items: center; gap: 2px; border-radius: var(--radius-md); }
    .pg:hover { background: var(--surface-2); }
    .open { flex: 1; min-width: 0; display: flex; align-items: center; gap: 10px; padding: 7px 8px; color: var(--text-2); text-decoration: none !important; font-size: 14px; }
    .open.child { padding-left: 30px; font-size: 13.5px; }
    .open:hover { color: var(--text); } .open hx-icon { color: var(--text-3); }
    .count { margin-left: auto; min-width: 18px; height: 18px; padding: 0 5px; border-radius: var(--radius-full); background: var(--accent);
             color: var(--accent-contrast); font: 600 11px/18px var(--font-sans); text-align: center; }
    .pin { width: 28px; height: 28px; border-radius: var(--radius-md); display: grid; place-items: center; color: var(--text-3); opacity: 0; }
    .pg:hover .pin, .pin:focus-visible, .pin.on { opacity: 1; } .pin.on { color: var(--accent); }
    .pin:hover { background: var(--surface-3); color: var(--text); }
    @media (hover: none) { .pin { opacity: .6; } }
    @media (max-width: 720px) { .body { padding: 14px 12px 28px; } }
    @media (max-width: 860px) { hx-page-header { padding-left: 56px; } }   /* room for the shell's menu button */
  `],
})
export class SystemPageComponent {
  plugins = inject(PluginsService);
  readonly hasDashboard = computed(() => this.plugins.dashboards().some(d => d.id === 'sistema'));
  readonly groups = computed(() => {
    const mods = this.plugins.modules();
    const pages = this.plugins.navPages().filter(p => mods.get(p.module)?.kind === 'core');
    const by = new Map<string, PluginPage[]>();
    for (const p of pages) by.set(p.module, [...(by.get(p.module) ?? []), p]);
    return [...by.entries()].map(([module, list]) => {
      const m = mods.get(module);
      const top = list.filter(p => !p.parent || !list.some(x => x.local_id === p.parent));
      const ordered = top.flatMap(p => [p, ...list.filter(c => c.parent === p.local_id)]);
      return { module, title: m?.title || module, icon: m?.icon || 'puzzle', description: m?.description || '', online: m?.online !== false,
               pages: ordered, order: Math.min(...list.map(p => p.order)) };
    }).sort((a, b) => a.order - b.order);
  });

  link(p: PluginPage): string { return this.plugins.link(p.module, p.local_id); }
  badge(p: PluginPage): number { return this.plugins.badges()[p.id] ?? 0; }
  pinned(p: PluginPage): boolean { return this.plugins.navPinned().includes(p.id); }
}
