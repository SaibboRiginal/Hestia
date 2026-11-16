import { ChangeDetectionStrategy, Component, computed, effect, inject, model, signal, untracked } from '@angular/core';
import { CentralSettingsApi, apiError } from '../settings/central-settings.api';
import { SessionService } from '../../services/session.service';
import { IconComponent, PopoverComponent, SettingLinkComponent, ToastService } from '../../ui';
import { tr, TrPipe } from '../../core/i18n';

export const MODE_KEY = 'oracle.chat.mode';

/** Conversation modes (Oracle owns them: setting oracle.chat.mode). */
export const CHAT_MODES = [
  { value: 'auto', label: tr('Auto'), icon: 'sparkle', help: tr('Hestia decides: quick answer or reasoned with the tools.') },
  { value: 'quick', label: tr('Quick'), icon: 'zap', help: tr('A single answer, no tools. The fastest.') },
  { value: 'thinking', label: tr('Thoughtful'), icon: 'brain', help: tr('Always reasons and uses the tools before answering.') },
  { value: 'cot', label: 'CoT', icon: 'list', help: tr('Deep step by step reasoning, with the steps at the bottom. Slower.') },
] as const;

/**
 * <hx-chat-mode [(mode)]="mode" /> — composer button: how much Hestia reasons for THIS conversation.
 * The value comes from Themis (session → client → profile, default in Impostazioni → Personali);
 * a pick is saved for this conversation (scope session) and sent with every message.
 */
@Component({
  selector: 'hx-chat-mode',
  imports: [TrPipe, IconComponent, PopoverComponent, SettingLinkComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <button class="pick" (click)="toggle($event)"  [title]="'Conversation mode' | tr"  [attr.aria-label]="'Conversation mode' | tr">
      <hx-icon [name]="current().icon" [size]="14" /><span>{{ current().label }}</span><hx-icon name="chevron-down" [size]="13" />
    </button>
    <hx-popover [open]="open()" [anchor]="anchor()" [width]="300" (closed)="open.set(false)">
      <div class="list" role="listbox"  [attr.aria-label]="'alt::Mode' | tr">
        @for (m of modes; track m.value) {
          <button class="opt" role="option" [class.on]="m.value === mode()" [attr.aria-selected]="m.value === mode()" (click)="pick(m.value)">
            <hx-icon [name]="m.icon" [size]="15" />
            <span class="t"><b>{{ m.label }}</b><small>{{ m.help }}</small></span>
            @if (m.value === mode()) { <hx-icon name="check" [size]="14" /> }
          </button>
        }
        <div class="foot"><span>{{ "Applies to this conversation" | tr }}</span>
          <hx-setting-link [key]="key"  [label]="'f::default' | tr"  [title]="'Change the default mode' | tr" (go)="open.set(false)" /></div>
      </div>
    </hx-popover>`,
  styles: [`
    :host { display: inline-flex; }
    .pick { display: inline-flex; align-items: center; gap: 5px; height: 30px; padding: 0 8px; border-radius: var(--radius-full);
            font-size: 13px; color: var(--text-2); border: 1px solid var(--border); }
    .pick:hover { background: var(--surface-2); color: var(--text); }
    .list { display: flex; flex-direction: column; padding: 6px; gap: 2px; }
    .opt { display: flex; align-items: flex-start; gap: 9px; padding: 8px; border-radius: var(--radius-md); text-align: left; color: var(--text-2); }
    .opt:hover { background: var(--surface-2); }
    .opt.on { color: var(--text); }
    .opt hx-icon { margin-top: 2px; }
    .t { display: flex; flex-direction: column; gap: 2px; flex: 1; }
    .t b { font-weight: 600; font-size: 13.5px; }
    .t small { font-size: 12px; color: var(--text-3); line-height: 1.35; }
    .foot { display: flex; align-items: center; justify-content: space-between; gap: 8px; font-size: 11.5px; color: var(--text-3);
            padding: 6px 2px 2px 8px; border-top: 1px solid var(--border); margin-top: 4px; }
  `],
})
export class ChatModeComponent {
  readonly key = MODE_KEY;
  private api = inject(CentralSettingsApi);
  private session = inject(SessionService);
  private toast = inject(ToastService);

  readonly mode = model('auto');
  readonly modes = CHAT_MODES;
  readonly open = signal(false);
  readonly anchor = signal<{ x: number; y: number; width: number; height: number } | null>(null);
  readonly current = computed(() => CHAT_MODES.find(m => m.value === this.mode()) ?? CHAT_MODES[0]);

  constructor() {
    // New conversation → its mode (profile default unless already overridden).
    effect(() => { this.session.sessionId(); untracked(() => void this.load()); });
  }

  private async load() {
    try {
      const page = await this.api.items('oracle');
      const v = page.items.find(i => i.key === MODE_KEY)?.value;
      if (typeof v === 'string' && CHAT_MODES.some(m => m.value === v)) this.mode.set(v);
    } catch { /* Themis unreachable: keep the current choice, Oracle falls back to its default */ }
  }

  toggle(e: MouseEvent) {
    e.stopPropagation();
    if (this.open()) { this.open.set(false); return; }
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    this.anchor.set({ x: r.left, y: r.top, width: r.width, height: r.height });
    this.open.set(true);
  }

  async pick(v: string) {
    this.open.set(false);
    if (v === this.mode()) return;
    this.mode.set(v);   // sent with the next message even if saving fails
    try { await this.api.set(MODE_KEY, v, 'session'); }
    catch (e) { this.toast.error(apiError(e, tr('Mode not saved for this conversation'))); }
  }
}
