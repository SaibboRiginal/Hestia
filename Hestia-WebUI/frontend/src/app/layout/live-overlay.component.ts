import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router, RouterLink } from '@angular/router';
import { filter, map } from 'rxjs';
import { ButtonComponent, IconComponent } from '../ui';
import { LiveVoiceService } from '../services/live-voice.service';
import { AppearanceService } from '../services/appearance.service';

const LABELS: Record<string, string> = {
  starting: 'Accendo il microfono…', listening: 'Ti ascolto', hearing: 'Ti sento…', thinking: 'Ci penso…', speaking: 'Sto parlando',
};

/**
 * Live mode «Parla» over any page (brainstorm C12, W7): started from the sidebar, the Home or Ctrl+Shift+Space, it
 * keeps going while you move around; the pet is its face when there is one (happy while talking, calm while
 * listening). The Chat page shows its own panel, so this one hides there.
 */
@Component({
  selector: 'hx-live-overlay',
  imports: [RouterLink, ButtonComponent, IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (live.on && !onChat()) {
      <div class="live hx-fade-in" role="status" [attr.data-state]="live.state()">
        @if (face(); as src) { <img class="face" [src]="src" alt=""> } @else { <span class="ring"><hx-icon name="waveform" [size]="18" /></span> }
        <div class="txt">
          <div class="st">{{ label() }}</div>
          @if (live.partial()) { <div class="pt">{{ live.partial() }}</div> }
        </div>
        @if (live.state() === 'speaking' || live.state() === 'thinking') {
          <button hx-btn variant="secondary" size="sm" icon="stop" (click)="live.interrupt()">Interrompi</button>
        }
        <a hx-btn variant="ghost" size="sm" icon="chat" iconOnly routerLink="/chat" aria-label="Apri la chat" title="Apri la chat"></a>
        <button hx-btn variant="ghost" size="sm" icon="x" iconOnly aria-label="Chiudi Parla" (click)="live.stop()"></button>
      </div>
    }`,
  styles: [`
    .live { position: fixed; left: 50%; bottom: 18px; transform: translateX(-50%); z-index: 950; display: flex; align-items: center; gap: 10px;
            width: min(560px, calc(100vw - 24px)); padding: 8px 10px 8px 8px; background: var(--surface); border: 1px solid var(--accent);
            border-radius: var(--radius-full); box-shadow: var(--shadow-3); }
    .face { width: 40px; height: 40px; object-fit: contain; flex: none; }
    .ring { width: 40px; height: 40px; border-radius: 50%; display: grid; place-items: center; flex: none; background: var(--accent-soft); color: var(--accent); }
    .live[data-state=hearing] .ring, .live[data-state=hearing] .face { animation: hx-pulse 1s infinite; }
    .live[data-state=speaking] .face { animation: hx-talk .6s ease-in-out infinite alternate; }
    @keyframes hx-talk { to { transform: translateY(-3px) scale(1.04); } }
    .txt { flex: 1; min-width: 0; }
    .st { font-weight: 600; font-size: 14px; }
    .pt { font-size: 13px; color: var(--text-2); font-style: italic; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    @media (prefers-reduced-motion: reduce) { .ring, .face { animation: none !important; } }
  `],
})
export class LiveOverlayComponent {
  live = inject(LiveVoiceService);
  private look = inject(AppearanceService);
  private router = inject(Router);
  private url = toSignal(this.router.events.pipe(filter(e => e instanceof NavigationEnd), map(() => this.router.url)), { initialValue: this.router.url });
  readonly onChat = computed(() => this.url().startsWith('/chat'));
  readonly label = computed(() => LABELS[this.live.state()] || '');
  readonly face = computed(() => this.look.pet() ? this.look.petImage(this.live.state() === 'speaking' ? 'happy' : 'idle') : '');
}
