import { ChangeDetectionStrategy, Component, HostListener, computed, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router } from '@angular/router';
import { filter, map } from 'rxjs';
import { IconComponent, ToastService } from '../ui';
import { AssistantService } from '../services/assistant.service';
import { LiveVoiceService } from '../services/live-voice.service';

/**
 * The bubble at the bottom right of every page (docs/work/2026-11-13-sidebar-e-chat §3.4): the two ways to reach the
 * assistant without leaving the page, each with one line that says what it does.
 * - «Scrivi qui»: the side panel that knows which page you are on (Ctrl+J).
 * - «Parla»: the continuous voice conversation, which goes on while you move around (Ctrl+Shift+Space).
 * Hidden on the Chat page (it has both in its own bar) and while the side panel is open.
 */
@Component({
  selector: 'hx-quick-bubble',
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (shown()) {
      <div class="wrap" [class.up]="live.on">
        @if (open()) {
          <div class="acts hx-fade-in" role="menu">
            <button type="button" role="menuitem" (click)="write()">
              <hx-icon name="edit" [size]="18" />
              <span><b>Scrivi qui</b><i>Chiedi o fai fare qualcosa su questa pagina, senza lasciarla</i></span><kbd>Ctrl J</kbd>
            </button>
            <button type="button" role="menuitem" (click)="talk()">
              <hx-icon name="waveform" [size]="18" />
              <span><b>{{ live.on ? 'Ferma Parla' : 'Parla' }}</b><i>Conversazione a voce: parli e ti risponde a voce, anche mentre cambi pagina</i></span>
            </button>
          </div>
        }
        <button type="button" class="fab" [class.live]="live.on" (click)="toggle($event)" aria-haspopup="menu" [attr.aria-expanded]="open()"
                aria-label="Scrivi o parla con l'assistente" title="Scrivi o parla con l'assistente">
          <hx-icon [name]="open() ? 'x' : live.on ? 'waveform' : 'sparkle'" [size]="22" />
        </button>
      </div>
    }`,
  styles: [`
    .wrap { position: fixed; right: 18px; bottom: 18px; z-index: 780; display: flex; flex-direction: column; align-items: flex-end; gap: 10px; }
    .fab { width: 52px; height: 52px; border-radius: 50%; display: grid; place-items: center; background: var(--accent); color: var(--accent-contrast);
           box-shadow: var(--shadow-3); transition: transform var(--dur-fast) var(--ease); }
    .fab:hover { transform: scale(1.05); }
    .fab.live { animation: hx-pulse 1.6s ease-in-out infinite; }
    .acts { display: flex; flex-direction: column; gap: 2px; width: min(320px, calc(100vw - 28px)); padding: 6px; background: var(--surface);
            border: 1px solid var(--border); border-radius: var(--radius-lg); box-shadow: var(--shadow-3); }
    .acts button { display: flex; align-items: flex-start; gap: 11px; padding: 9px 10px; border-radius: var(--radius-md); text-align: left; color: var(--text); }
    .acts button:hover { background: var(--surface-2); }
    .acts hx-icon { color: var(--accent); margin-top: 2px; flex: none; }
    .acts span { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
    .acts b { font-weight: 600; font-size: 14px; }
    .acts i { font-style: normal; font-size: 12.5px; color: var(--text-3); line-height: 1.35; }
    .acts kbd { font: 10.5px var(--font-mono, monospace); color: var(--text-3); margin-top: 3px; white-space: nowrap; }
    @media (max-width: 860px) { .wrap { right: 14px; bottom: 14px; } .fab { width: 48px; height: 48px; } .acts kbd { display: none; }
      .wrap.up { bottom: 84px; } }   /* above the «Parla» bar */
    @media (prefers-reduced-motion: reduce) { .fab { animation: none !important; transition: none; } }
  `],
})
export class QuickBubbleComponent {
  live = inject(LiveVoiceService);
  private assistant = inject(AssistantService);
  private toasts = inject(ToastService);
  private router = inject(Router);
  private url = toSignal(this.router.events.pipe(filter(e => e instanceof NavigationEnd), map(() => this.router.url)), { initialValue: this.router.url });
  readonly open = signal(false);
  readonly shown = computed(() => !this.url().startsWith('/chat') && !this.assistant.isOpen());

  toggle(e: MouseEvent): void { e.stopPropagation(); this.open.update(v => !v); }

  write(): void {
    this.open.set(false);
    this.assistant.toggle();
  }

  talk(): void {
    this.open.set(false);
    if (this.live.on) { this.live.stop(); return; }
    void this.live.start().then(() => { if (this.live.error()) this.toasts.error(this.live.error()); });
  }

  @HostListener('document:click')
  @HostListener('document:keydown.escape')
  close(): void { if (this.open()) this.open.set(false); }
}
