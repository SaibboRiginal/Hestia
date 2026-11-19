import { ChangeDetectionStrategy, Component, ElementRef, OnDestroy, computed, effect, inject, input, signal, untracked, viewChild } from '@angular/core';
import { IconComponent, SpinnerComponent } from '../../ui';
import { PluginsService } from '../plugins/plugins.service';
import { TrPipe } from '../../core/i18n';

type ConnectionsElement = HTMLElement & { sources?: unknown[]; place?: string; open?: string; load?: () => Promise<void> };

/**
 * <hx-connections> — every external service of every module (catalog type «connection», hestia_common.connections)
 * drawn by ONE kit element, `<hxk-connections>` of the plugin SDK, with each module's own host (its API through the
 * WebUI proxy). Used by the «Connections» page and by the guided setup («Your services», `place="setup"`).
 * Dossier docs/work/2026-11-19-unified-connections.
 */
@Component({
  selector: 'hx-connections',
  imports: [TrPipe, IconComponent, SpinnerComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @switch (state()) {
      @case ('loading') { <div class="st"><hx-spinner [size]="18" /></div> }
      @case ('error') { <div class="st"><hx-icon name="alert" [size]="20" /><span>{{ "Not available at the moment" | tr }}</span>
        <button class="retry" (click)="mount()">{{ "Try again" | tr }}</button></div> }
      @case ('empty') { <div class="st"><span>{{ "No service to link yet." | tr }}</span></div> }
    }
    <div #slot [hidden]="state() !== 'ready'"></div>`,
  styles: [`
    :host { display: block; }
    .st { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; color: var(--text-3);
          font-size: 13px; text-align: center; padding: 16px; min-height: 80px; }
    .retry { color: var(--accent); font-weight: 500; font-size: 12.5px; }
  `],
})
export class ConnectionsComponent implements OnDestroy {
  private plugins = inject(PluginsService);
  /** «setup»: only the services offered in the guided setup. */
  place = input<string>('');
  /** `<module>.<id>` of the card to open. */
  open = input<string>('');

  readonly state = signal<'loading' | 'ready' | 'error' | 'empty'>('loading');
  private slot = viewChild.required<ElementRef<HTMLElement>>('slot');
  private el: ConnectionsElement | null = null;
  private readonly modules = computed(() => {
    const seen = new Map<string, string>();
    for (const c of this.plugins.connections()) if (!seen.has(c.module)) seen.set(c.module, c.source);
    return [...seen.entries()];
  });

  constructor() {
    effect(() => {
      const mods = this.modules();
      const place = this.place(), open = this.open();
      untracked(() => void this.mount(mods, place, open));
    });
  }

  async mount(mods = this.modules(), place = this.place(), open = this.open()): Promise<void> {
    if (!this.plugins.catalog()) { this.state.set('loading'); return; }
    if (!mods.length) { this.state.set('empty'); return; }
    if (!customElements.get('hxk-connections') && !(await this.plugins.loadSdk())) { this.state.set('error'); return; }
    if (!this.el) {
      this.el = document.createElement('hxk-connections') as ConnectionsElement;
      this.slot().nativeElement.appendChild(this.el);
    }
    this.el.place = place;
    if (open) this.el.open = open;
    this.el.sources = mods.map(([module, path]) => ({ module, path, host: this.plugins.host(module) }));
    this.state.set('ready');
    if (open) setTimeout(() => this.el?.shadowRoot?.getElementById(open)?.scrollIntoView({ block: 'center', behavior: 'smooth' }), 400);
  }

  /** Re-read every module (the page calls it when it comes back in view). */
  reload(): void { void this.el?.load?.(); }

  ngOnDestroy(): void { this.el?.remove(); this.el = null; }
}
