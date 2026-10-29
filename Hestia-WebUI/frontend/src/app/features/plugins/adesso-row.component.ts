import { ChangeDetectionStrategy, Component, OnInit, computed, effect, inject, untracked } from '@angular/core';
import { IconComponent } from '../../ui';
import { AdessoItem, MetisService } from '../../services/metis.service';
import { PluginsService } from './plugins.service';

const SOURCE_ICON: Record<string, string> = { agenda: 'calendar', habit: 'repeat', recent: 'history', idea: 'sparkle' };

/**
 * Home row «Adesso» (dossier 2026-10-24-tutto-brainstorm-cindy C11, W7): what makes sense now, from the agenda,
 * habits, recent use and a few ideas, each with its reason. A tap opens the tool (run at once when it needs nothing
 * more) and is remembered, so the row learns. Hidden when there is nothing to suggest.
 */
@Component({
  selector: 'hx-adesso-row',
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (items().length) {
      <section class="row" aria-label="Adesso">
        <div class="h"><hx-icon name="zap" [size]="14" /><span>Adesso</span></div>
        <div class="list">
          @for (it of items(); track it.tool + it.title) {
            <button class="card" (click)="open(it)" [attr.title]="it.reason || it.title">
              <hx-icon [name]="icon(it)" [size]="16" />
              <span class="txt"><span class="t">{{ it.title }}</span>@if (it.reason) {<span class="r">{{ it.reason }}</span>}</span>
            </button>
          }
        </div>
      </section>
    }`,
  styles: [`
    .row { display: flex; flex-direction: column; gap: 8px; }
    .h { display: flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 600; color: var(--text-3); text-transform: uppercase; letter-spacing: .03em; }
    .h hx-icon { color: var(--accent); }
    .list { display: grid; gap: 8px; grid-template-columns: repeat(auto-fill, minmax(min(100%, 220px), 1fr)); }
    .card { display: flex; align-items: flex-start; gap: 10px; text-align: left; padding: 10px 12px; min-height: 44px; border-radius: var(--radius-lg);
            border: 1px solid var(--border); background: var(--surface); color: var(--text); cursor: pointer;
            transition: background var(--dur-fast) var(--ease), border-color var(--dur-fast) var(--ease); }
    .card:hover { background: var(--surface-2); border-color: var(--border-strong); }
    .card:focus-visible { outline: none; box-shadow: 0 0 0 3px var(--focus-ring); }
    .card hx-icon { color: var(--accent); flex: none; margin-top: 2px; }
    .txt { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
    .t { font-weight: 550; overflow-wrap: anywhere; }
    .r { font-size: 12px; color: var(--text-3); overflow-wrap: anywhere; }
  `],
})
export class AdessoRowComponent implements OnInit {
  private metis = inject(MetisService);
  private plugins = inject(PluginsService);
  readonly items = computed(() => this.metis.adesso());

  constructor() {
    // The catalog arrives after the first paint: read again once Metis is known.
    effect(() => { if (this.plugins.modules().has('metis')) untracked(() => void this.metis.loadAdesso()); });
  }

  ngOnInit(): void { void this.metis.loadAdesso(); }

  icon(it: AdessoItem): string { return this.plugins.modules().get(it.module)?.icon || SOURCE_ICON[it.source] || 'zap'; }

  open(it: AdessoItem): void { this.metis.open(it.tool, it.args ?? {}, it.title); }
}
