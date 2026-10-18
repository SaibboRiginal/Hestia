import { ChangeDetectionStrategy, Component, ElementRef, OnDestroy, computed, effect, inject, input, signal, untracked, viewChild } from '@angular/core';
import { IconComponent, SpinnerComponent } from '../../ui';
import { PluginsService } from './plugins.service';

/**
 * Mounts one plugin custom element (page or widget): loads the module bundle, creates `<element>`, sets
 * `el.host` (SDK host API) and `el.ctx`. Module offline / bundle missing → a quiet state, never an error page.
 */
@Component({
  selector: 'hx-plugin-outlet',
  imports: [IconComponent, SpinnerComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @switch (state()) {
      @case ('loading') { <div class="st"><hx-spinner [size]="18" /></div> }
      @case ('offline') { <div class="st"><hx-icon name="offline" [size]="20" /><span>{{ title() }} non raggiungibile</span>
        <button class="retry" (click)="mount(true)">Riprova</button></div> }
      @case ('error') { <div class="st"><hx-icon name="alert" [size]="20" /><span>Interfaccia di {{ title() }} non disponibile</span>
        <button class="retry" (click)="mount(true)">Riprova</button></div> }
    }
    <div #slot class="slot" [hidden]="state() !== 'ready'"></div>`,
  styles: [`
    :host { display: flex; flex-direction: column; min-height: 0; flex: 1; }
    .slot { display: flex; flex-direction: column; flex: 1; min-height: 0; }
    .slot > * { flex: 1; min-height: 0; }
    .st { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; color: var(--text-3);
          font-size: 13px; text-align: center; padding: 16px; min-height: 80px; }
    .retry { color: var(--accent); font-weight: 500; font-size: 12.5px; }
  `],
})
export class PluginOutletComponent implements OnDestroy {
  private plugins = inject(PluginsService);
  module = input.required<string>();
  element = input.required<string>();
  ctx = input<object>({});

  readonly state = signal<'loading' | 'ready' | 'offline' | 'error'>('loading');
  readonly title = computed(() => this.plugins.modules().get(this.module())?.title ?? this.module());
  private slot = viewChild.required<ElementRef<HTMLElement>>('slot');
  private el: (HTMLElement & { host?: object; ctx?: object }) | null = null;
  private mounted = '';

  constructor() {
    effect(() => {
      const key = `${this.module()}|${this.element()}`;
      this.plugins.bundles();                      // re-run when the catalog (versions, online) changes
      untracked(() => { if (key !== this.mounted || this.state() !== 'ready') void this.mount(); });
    });
    effect(() => {
      const ctx = this.ctx();
      untracked(() => { if (this.el) this.el.ctx = ctx; });
    });
  }

  async mount(force = false): Promise<void> {
    const module = this.module(), element = this.element();
    const info = this.plugins.modules().get(module);
    if (!this.plugins.catalog()) { this.state.set('loading'); return; }
    if (!customElements.get(element)) {
      if (info && !info.online) { this.state.set('offline'); return; }
      this.state.set('loading');
      if (force) await this.plugins.refreshCatalog(true);
      const ok = await this.plugins.loadBundle(module);
      if (!ok || !customElements.get(element)) {
        this.state.set(info && !this.plugins.modules().get(module)?.online ? 'offline' : 'error');
        return;
      }
    }
    if (this.mounted === `${module}|${element}` && this.el) { this.state.set('ready'); return; }
    this.slot().nativeElement.replaceChildren();
    const el = document.createElement(element) as HTMLElement & { host?: object; ctx?: object };
    el.host = this.plugins.host(module);
    el.ctx = this.ctx();
    this.slot().nativeElement.appendChild(el);
    this.el = el;
    this.mounted = `${module}|${element}`;
    this.state.set('ready');
  }

  ngOnDestroy(): void { this.el?.remove(); this.el = null; }
}
