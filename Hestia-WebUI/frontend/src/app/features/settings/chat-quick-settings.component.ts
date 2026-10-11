import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { ButtonComponent, PopoverComponent, SegmentedComponent, SpinnerComponent, ToastService } from '../../ui';
import { SettingsService, THINKING_DISPLAY_OPTIONS } from '../../services/settings.service';
import { CentralSettingsApi, SettingItem, apiError } from './central-settings.api';
import { SettingControlComponent } from './setting-control.component';

const KEYS = ['oracle.chat.tone', 'oracle.chat.instructions'];

/**
 * <hx-chat-quick-settings /> — chat header button: personal settings for THIS conversation
 * (Themis scope session). Defaults stay in Impostazioni → Personali; "Come predefinito" drops
 * the override so the conversation follows the defaults again. "Ragionamento" is how this browser
 * shows the reasoning (WebUI presentation, same value as Personali).
 */
@Component({
  selector: 'hx-chat-quick-settings',
  imports: [RouterLink, ButtonComponent, PopoverComponent, SegmentedComponent, SpinnerComponent, SettingControlComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <button hx-btn variant="ghost" size="sm" icon="settings" iconOnly aria-label="Impostazioni di questa chat"
            title="Impostazioni di questa chat" (click)="toggle($event)"></button>
    <hx-popover [open]="open()" [anchor]="anchor()" [width]="370" (closed)="open.set(false)">
      <div class="pop">
        <div class="ph">Questa conversazione</div>
        @if (loading()) { <div class="c"><hx-spinner [size]="16" /></div> }
        @for (it of items(); track it.key) {
          <div class="row">
            <div class="lbl">
              <span>{{ it.label }}</span>
              @if (it.source === 'session') {
                <button class="def" (click)="followDefault(it)">Come predefinito</button>
              } @else { <span class="src">predefinito</span> }
            </div>
            <hx-setting-control [item]="it" (commit)="set(it, $event)" />
          </div>
        }
        <div class="row">
          <div class="lbl"><span>Ragionamento</span><span class="src">su questo browser</span></div>
          <hx-segmented [options]="thinking" [value]="prefs.settings().thinkingDisplay" (changed)="setThinking($event)" />
        </div>
        <a class="more" routerLink="/settings" (click)="open.set(false)">Predefiniti e altre impostazioni…</a>
      </div>
    </hx-popover>`,
  styles: [`
    :host { display: inline-flex; }
    .pop { padding: 12px 14px; display: flex; flex-direction: column; gap: 12px; }
    .ph { font-weight: 600; font-size: 14px; }
    .c { display: flex; justify-content: center; }
    .row { display: flex; flex-direction: column; gap: 6px; }
    .lbl { display: flex; align-items: center; justify-content: space-between; gap: 8px; font-size: 13px; color: var(--text-2); }
    .src { font-size: 11.5px; color: var(--text-3); }
    .def { font-size: 12px; color: var(--accent); }
    .more { font-size: 12.5px; color: var(--accent); text-decoration: none; }
  `],
})
export class ChatQuickSettingsComponent {
  private api = inject(CentralSettingsApi);
  private toast = inject(ToastService);
  readonly prefs = inject(SettingsService);
  readonly thinking = THINKING_DISPLAY_OPTIONS;
  readonly open = signal(false);
  readonly anchor = signal<{ x: number; y: number; width: number; height: number } | null>(null);
  readonly items = signal<SettingItem[]>([]);
  readonly loading = signal(false);

  async toggle(e: MouseEvent) {
    e.stopPropagation();
    if (this.open()) { this.open.set(false); return; }
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    this.anchor.set({ x: r.left, y: r.top, width: r.width, height: r.height });
    this.open.set(true);
    await this.load();
  }

  private async load() {
    this.loading.set(true);
    try {
      const page = await this.api.items('oracle');
      this.items.set(KEYS.map(k => page.items.find(i => i.key === k)).filter((i): i is SettingItem => !!i));
    } catch (e) {
      this.toast.error(apiError(e, 'Impostazioni non raggiungibili'));
    } finally {
      this.loading.set(false);
    }
  }

  async set(it: SettingItem, value: unknown) {
    try {
      await this.api.set(it.key, value, 'session');
      await this.load();
      this.toast.success(`${it.label}: vale per questa conversazione`);
    } catch (e) { this.toast.error(apiError(e, 'Salvataggio non riuscito')); }
  }

  async setThinking(v: string) {
    try { await this.prefs.update({ thinkingDisplay: v }); }
    catch (e) { this.toast.error(apiError(e, 'Salvataggio non riuscito')); }
  }

  async followDefault(it: SettingItem) {
    try { await this.api.reset(it.key, 'session'); await this.load(); }
    catch (e) { this.toast.error(apiError(e)); }
  }
}
