import { ChangeDetectionStrategy, Component, computed, effect, inject, model, signal, untracked } from '@angular/core';
import { CentralSettingsApi, apiError } from '../settings/central-settings.api';
import { SessionService } from '../../services/session.service';
import { IconComponent, PopoverComponent, ToastService } from '../../ui';

export const MODE_KEY = 'oracle.chat.mode';

/** Conversation modes (Oracle owns them: setting oracle.chat.mode). */
export const CHAT_MODES = [
  { value: 'auto', label: 'Auto', icon: 'sparkle', help: 'Hestia decide: risposta rapida o ragionata con gli strumenti.' },
  { value: 'quick', label: 'Rapida', icon: 'zap', help: 'Una sola risposta, niente strumenti. La più veloce.' },
  { value: 'thinking', label: 'Pensata', icon: 'brain', help: 'Ragiona sempre e usa gli strumenti prima di rispondere.' },
  { value: 'cot', label: 'CoT', icon: 'list', help: 'Ragionamento profondo passo passo, con i passi in fondo. Più lenta.' },
] as const;

/**
 * <hx-chat-mode [(mode)]="mode" /> — composer button: how much Hestia reasons for THIS conversation.
 * The value comes from Themis (session → client → profile, default in Impostazioni → Personali);
 * a pick is saved for this conversation (scope session) and sent with every message.
 */
@Component({
  selector: 'hx-chat-mode',
  imports: [IconComponent, PopoverComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <button class="pick" (click)="toggle($event)" title="Modalità di conversazione" aria-label="Modalità di conversazione">
      <hx-icon [name]="current().icon" [size]="14" /><span>{{ current().label }}</span><hx-icon name="chevron-down" [size]="13" />
    </button>
    <hx-popover [open]="open()" [anchor]="anchor()" [width]="300" (closed)="open.set(false)">
      <div class="list" role="listbox" aria-label="Modalità">
        @for (m of modes; track m.value) {
          <button class="opt" role="option" [class.on]="m.value === mode()" [attr.aria-selected]="m.value === mode()" (click)="pick(m.value)">
            <hx-icon [name]="m.icon" [size]="15" />
            <span class="t"><b>{{ m.label }}</b><small>{{ m.help }}</small></span>
            @if (m.value === mode()) { <hx-icon name="check" [size]="14" /> }
          </button>
        }
        <div class="foot">Vale per questa conversazione · predefinita in Impostazioni → Personali</div>
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
    .foot { font-size: 11.5px; color: var(--text-3); padding: 6px 8px 2px; border-top: 1px solid var(--border); margin-top: 4px; }
  `],
})
export class ChatModeComponent {
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
    catch (e) { this.toast.error(apiError(e, 'Modalità non salvata per questa conversazione')); }
  }
}
