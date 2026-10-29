import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { IconComponent } from '../ui';
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
 * Over every page, never in the way (pointer-events off): the light effect of the active graphic profile (snow,
 * leaves, petals, confetti, hearts, stars, pumpkins, a warm sun) and the pet in the corner — a tap makes it happy,
 * at night it sleeps (dossier 2026-10-24-tutto-brainstorm-cindy A2, W7). With «riduci movimento» the effect is off.
 */
@Component({
  selector: 'hx-appearance-layer',
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
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
    @if (petSrc(); as src) {
      <button class="pet" [class.happy]="pose() === 'happy'" (click)="cheer()" [attr.aria-label]="petName()" [attr.title]="petName()">
        <img [src]="src" alt="" draggable="false">
      </button>
    }`,
  styles: [`
    .fx, .sun { position: fixed; inset: 0; pointer-events: none; z-index: 5; overflow: hidden; }
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
    .pet { position: fixed; right: 14px; bottom: 96px; z-index: 6; width: 64px; height: 64px; padding: 0; border: 0; background: transparent;
           cursor: pointer; border-radius: 50%; transition: transform var(--dur-fast) var(--ease); }
    .pet:hover { transform: translateY(-2px); }
    .pet:focus-visible { outline: none; box-shadow: 0 0 0 3px var(--focus-ring); }
    .pet.happy { animation: hx-hop .5s var(--ease) 2; }
    .pet img { width: 100%; height: 100%; object-fit: contain; filter: drop-shadow(0 2px 4px rgba(0,0,0,.25)); }
    @keyframes hx-hop { 50% { transform: translateY(-10px); } }
    @media (max-width: 860px) { .pet { width: 48px; height: 48px; bottom: 84px; } }
  `],
})
export class AppearanceLayerComponent {
  private look = inject(AppearanceService);
  readonly bits = BITS;
  readonly effect = this.look.lightEffect;
  readonly icon = computed(() => ICON_EFFECT[this.effect()] || '');
  private readonly happyUntil = signal(0);
  readonly pose = computed(() => {
    if (this.happyUntil() > 0) return 'happy';
    const h = new Date().getHours();
    return h >= 23 || h < 7 ? 'sleep' : 'idle';
  });
  readonly petName = computed(() => this.look.pet()?.name ?? '');
  readonly petSrc = computed(() => this.look.pet() ? this.look.petImage(this.pose()) : '');

  cheer(): void {
    this.happyUntil.set(Date.now() + 2500);
    setTimeout(() => this.happyUntil.set(0), 2500);
  }
}
