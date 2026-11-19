import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router } from '@angular/router';
import { filter, map } from 'rxjs';
import { IconComponent } from '../ui';
import { MascotComponent } from './mascot.component';
import { AppearanceService } from '../services/appearance.service';

interface Bit { left: number; delay: number; dur: number; size: number; alt: boolean; }

const COUNT = 16;
/** Same particles on every render (no jumping on change detection): a small fixed pseudo-random sequence. */
const BITS: Bit[] = Array.from({ length: COUNT }, (_, i) => {
  const r = (n: number) => ((Math.sin((i + 1) * n) * 10000) % 1 + 1) % 1;
  return { left: Math.round(r(12.9) * 100), delay: -Math.round(r(78.2) * 14), dur: 9 + Math.round(r(37.7) * 9), size: 6 + Math.round(r(4.1) * 8), alt: i % 2 === 1 };
});
const ICON_EFFECT: Record<string, string> = { hearts: 'heart', stars: 'star' };

/**
 * Never in the way (pointer-events off): the light effect of the active graphic profile (snow, leaves, petals,
 * confetti, hearts, stars, pumpkins, a warm sun) — only on Home, and the falling bits fade out after about ten
 * seconds so reading is never disturbed (dossier 2026-10-29-frontend-review-and-tests §6.4) — and the mascot on every
 * page (`<hx-mascot>`, dossier 2026-11-18-real-test-problems G).
 * With «reduce motion» or the «Animations: reduced» knob the effect is off.
 */
@Component({
  selector: 'hx-appearance-layer',
  imports: [IconComponent, MascotComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (onHome()) {
      @if (effect() === 'sun') {
        <div class="sun" aria-hidden="true"></div>
      } @else if (effect() !== 'none') {
        <div class="fx" [attr.data-fx]="effect()" aria-hidden="true">
          @for (b of bits; track $index) {
            <span class="bit" [class.alt]="b.alt" [style.left.%]="b.left" [style.animation-delay.s]="b.delay"
                  [style.animation-duration.s]="b.dur" [style.width.px]="b.size" [style.height.px]="b.size">
              @if (icon()) { <hx-icon [name]="icon()" [size]="b.size + 6" /> }
            </span>
          }
        </div>
      }
    }
    <hx-mascot />`,
  styles: [`
    .fx, .sun { position: fixed; inset: 0; pointer-events: none; z-index: 5; overflow: hidden; }
    .fx { animation: hx-fx-life 11s var(--ease) forwards; }
    @keyframes hx-fx-life { 0% { opacity: 0; } 8% { opacity: 1; } 75% { opacity: 1; } 100% { opacity: 0; visibility: hidden; } }
    :host-context([data-motion=off]) .fx { display: none; }
    .sun { background: radial-gradient(circle at 92% -6%, color-mix(in srgb, var(--accent) 22%, transparent) 0, transparent 38%); }
    .bit { position: absolute; top: -24px; display: block; opacity: .55; animation-name: hx-fall; animation-timing-function: linear;
           animation-iteration-count: infinite; color: var(--accent); }
    .bit.alt { color: var(--accent-2, var(--accent)); }
    [data-fx=snow] .bit { border-radius: 50%; background: #fff; box-shadow: 0 0 3px rgba(0,0,0,.25); opacity: .8; }
    [data-fx=leaves] .bit { border-radius: 0 70% 0 70%; background: currentColor; animation-name: hx-sway; }
    [data-fx=petals] .bit { border-radius: 70% 0 70% 0; background: currentColor; opacity: .45; animation-name: hx-sway; }
    [data-fx=confetti] .bit { border-radius: 1px; background: currentColor; height: 4px !important; animation-name: hx-spin-fall; }
    [data-fx=pumpkins] .bit { border-radius: 45%; background: currentColor; opacity: .4; }
    [data-fx=hearts] .bit, [data-fx=stars] .bit { width: auto !important; height: auto !important; opacity: .45; }
    @keyframes hx-fall { from { transform: translateY(0); } to { transform: translateY(105vh); } }
    @keyframes hx-sway { 0% { transform: translate(0, 0) rotate(0); } 50% { transform: translate(28px, 52vh) rotate(160deg); }
                         100% { transform: translate(-12px, 105vh) rotate(320deg); } }
    @keyframes hx-spin-fall { from { transform: translateY(0) rotate(0); } to { transform: translateY(105vh) rotate(720deg); } }
    @media (prefers-reduced-motion: reduce) { .fx { display: none; } }
  `],
})
export class AppearanceLayerComponent {
  private look = inject(AppearanceService);
  private router = inject(Router);
  /** The light effect lives on Home only (proposal 4). */
  readonly onHome = toSignal(this.router.events.pipe(filter(e => e instanceof NavigationEnd),
    map(() => this.router.url.startsWith('/home'))), { initialValue: this.router.url.startsWith('/home') || this.router.url === '/' });
  readonly bits = BITS;
  readonly effect = this.look.lightEffect;
  readonly icon = computed(() => ICON_EFFECT[this.effect()] || '');
}
