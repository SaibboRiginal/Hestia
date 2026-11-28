import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { RouterLink } from '@angular/router';
import { UI } from '../../ui';
import { NavService } from '../../layout/nav.service';
import { PluginsService } from '../plugins/plugins.service';
import { TrPipe } from '../../core/i18n';

/** «Spaces» (docs/work/2026-11-27-webui-rethink §3.2): every space as a tile, the same list as the panel. On a phone it
 *  is what the «Spaces» tab opens. */
@Component({
  selector: 'app-spaces-page',
  imports: [TrPipe, RouterLink, ...UI],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <hx-page-header [title]="'Spaces' | tr" [subtitle]="'Everything {assistant} follows for you' | tr" />
    <div class="body">
      @if (!plugins.catalog() && !plugins.catalogError()) {
        <div class="center"><hx-spinner /></div>
      } @else if (!nav.spaces().length) {
        <hx-empty icon="grid" [title]="'No space yet' | tr">{{ "The modules you install add their space here." | tr }}</hx-empty>
      } @else {
        <div class="grid">
          @for (s of nav.spaces(); track s.id) {
            <a class="tile hx-glass" [routerLink]="s.link" [class.off]="!s.online" [style.--h]="s.color">
              <span class="ic"><hx-icon [name]="s.icon" [size]="22" /></span>
              <b>{{ s.label }}</b>
              @if (s.badge) { <span class="count">{{ s.badge }}</span> }
            </a>
          }
        </div>
      }
    </div>`,
  styles: [`
    :host { display: flex; flex-direction: column; flex: 1; min-height: 0; overflow: auto; }
    .body { padding: 8px 24px 32px; }
    .center { display: grid; place-items: center; padding: 48px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 12px; }
    .tile { position: relative; display: flex; flex-direction: column; align-items: flex-start; gap: 12px; padding: 16px; min-height: 112px;
            background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-lg); color: var(--text);
            text-decoration: none !important; box-shadow: var(--shadow-1); transition: transform var(--dur) var(--ease), border-color var(--dur) var(--ease); }
    .tile:hover { transform: translateY(-2px); border-color: color-mix(in srgb, var(--h) 45%, var(--border)); }
    .tile.off { opacity: .55; }
    .ic { width: 42px; height: 42px; border-radius: var(--radius-md); display: grid; place-items: center;
          background: color-mix(in srgb, var(--h) 16%, transparent); color: var(--h); }
    b { font: 600 15px var(--font-sans); }
    .count { position: absolute; top: 12px; right: 12px; min-width: 20px; height: 20px; padding: 0 6px; border-radius: var(--radius-full);
             background: var(--accent); color: var(--accent-contrast); font: 600 11.5px/20px var(--font-sans); text-align: center; }
    @media (max-width: 860px) { .body { padding: 8px 12px 24px; } .grid { grid-template-columns: repeat(2, 1fr); gap: 10px; } }
  `],
})
export class SpacesPageComponent {
  nav = inject(NavService);
  plugins = inject(PluginsService);
}
