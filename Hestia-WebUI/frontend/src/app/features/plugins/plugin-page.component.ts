import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router } from '@angular/router';
import { filter, map, startWith } from 'rxjs';
import { EmptyStateComponent, SpinnerComponent } from '../../ui';
import { PluginOutletComponent } from './plugin-outlet.component';
import { PluginsService } from './plugins.service';

/** A module's page (SPEC §4.3): the plugin element fills the page; the shell gives only the frame. */
@Component({
  selector: 'app-plugin-page',
  imports: [PluginOutletComponent, EmptyStateComponent, SpinnerComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (!plugins.catalog()) {
      <div class="center">@if (plugins.catalogError()) { <hx-empty icon="offline" title="Catalogo dei moduli non raggiungibile" /> } @else { <hx-spinner /> }</div>
    } @else {
      @if (match(); as m) {
        <hx-plugin-outlet [module]="route().module" [element]="m.page.element" [ctx]="ctx()" />
      } @else {
        <div class="center"><hx-empty icon="puzzle" title="Pagina non trovata">
          {{ moduleTitle() }} non ha questa pagina, oppure il modulo non è installato.</hx-empty></div>
      }
    }`,
  styles: [`
    :host { display: flex; flex-direction: column; flex: 1; min-height: 0; overflow: auto; }
    .center { flex: 1; display: grid; place-items: center; padding: 24px; }
    /* Phone: the shell's menu button sits on the title line of the plugin page (SDK .page > :first-child reads
       --head-inset), not on a row of its own. */
    @media (max-width: 860px) { :host { --head-inset: 44px; } }
  `],
})
export class PluginPageComponent {
  plugins = inject(PluginsService);
  private router = inject(Router);

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
