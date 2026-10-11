import { ChangeDetectionStrategy, Component, HostListener, input, model, signal } from '@angular/core';

const PREFIX = 'hestia_w_';

/** Width saved by `<hx-resize [key]>` (per browser), or `def`. Use it to initialise the width signal. */
export function savedWidth(key: string, def: number): number {
  try { return Number(localStorage.getItem(PREFIX + key)) || def; } catch { return def; }
}

/**
 * Drag handle that resizes a side panel: put it inside the panel (`position: relative`) and bind the width,
 * `<hx-resize [(width)]="w" edge="right" [min]="200" [max]="480" [def]="248" key="nav" />`.
 * `edge` = side of the panel the handle sits on. For a panel that scrolls, use `inline` and put the handle right
 * after/before the panel in the flex row instead (an absolute child would scroll away with the content).
 * Drag, ←/→ when focused (Shift = bigger step), double-click = `def`.
 * Width clamped to [min, max] and to 90% of the viewport; saved per browser under `key`. Hidden on phones (≤860px).
 */
@Component({
  selector: 'hx-resize',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: {
    role: 'separator', 'aria-orientation': 'vertical', 'aria-label': 'Ridimensiona', tabindex: '0',
    title: 'Trascina per ridimensionare · doppio clic per la larghezza predefinita',
    '[class]': 'edge()', '[class.inline]': 'inline()', '[class.dragging]': 'dragging()',
    '[attr.aria-valuenow]': 'width()', '[attr.aria-valuemin]': 'min()', '[attr.aria-valuemax]': 'max()',
  },
  template: '',
  styles: [`
    :host { position: absolute; top: 0; bottom: 0; width: 9px; cursor: col-resize; z-index: 5; touch-action: none; }
    :host(.right) { right: -5px; } :host(.left) { left: -5px; }
    :host::after { content: ''; position: absolute; top: 0; bottom: 0; left: 3px; width: 3px; background: transparent;
                   transition: background var(--dur) var(--ease); }
    :host(.inline) { position: relative; width: 0; flex-shrink: 0; align-self: stretch; right: auto; left: auto; }
    :host(.inline)::before { content: ''; position: absolute; top: 0; bottom: 0; left: -5px; width: 9px; }
    :host(.inline)::after { left: -2px; }
    :host(:hover)::after, :host(:focus-visible)::after, :host(.dragging)::after { background: var(--accent); }
    :host(:focus-visible) { outline: none; }
    @media (max-width: 860px) { :host { display: none; } }
  `],
})
export class ResizeHandleComponent {
  readonly width = model.required<number>();
  readonly edge = input<'left' | 'right'>('right');
  readonly min = input(180);
  readonly max = input(1200);
  readonly def = input.required<number>();
  readonly key = input<string>();
  readonly inline = input(false);
  readonly dragging = signal(false);

  private clamp(w: number) {
    const max = Math.max(this.min(), Math.min(this.max(), Math.floor(window.innerWidth * 0.9)));
    return Math.round(Math.min(Math.max(w, this.min()), max));
  }

  private commit(w: number) {
    const v = this.clamp(w);
    this.width.set(v);
    const k = this.key();
    if (k) try { localStorage.setItem(PREFIX + k, String(v)); } catch { /* private mode */ }
  }

  @HostListener('pointerdown', ['$event'])
  down(e: PointerEvent) {
    if (e.button !== 0) return;
    e.preventDefault();
    const el = e.currentTarget as HTMLElement;
    el.setPointerCapture(e.pointerId);
    const x0 = e.clientX, w0 = this.width(), dir = this.edge() === 'right' ? 1 : -1;
    this.dragging.set(true);
    document.body.classList.add('hx-resizing');
    const move = (ev: PointerEvent) => this.width.set(this.clamp(w0 + dir * (ev.clientX - x0)));
    const end = () => {
      el.removeEventListener('pointermove', move);
      el.removeEventListener('pointerup', end);
      el.removeEventListener('pointercancel', end);
      this.dragging.set(false);
      document.body.classList.remove('hx-resizing');
      this.commit(this.width());
    };
    el.addEventListener('pointermove', move);
    el.addEventListener('pointerup', end);
    el.addEventListener('pointercancel', end);
  }

  @HostListener('dblclick') reset() { this.commit(this.def()); }

  @HostListener('keydown', ['$event'])
  key_(e: KeyboardEvent) {
    const step = (e.shiftKey ? 80 : 20) * (this.edge() === 'right' ? 1 : -1);
    if (e.key === 'ArrowRight') { e.preventDefault(); this.commit(this.width() + step); }
    else if (e.key === 'ArrowLeft') { e.preventDefault(); this.commit(this.width() - step); }
  }

  /** Keep a remembered width inside the viewport when the window shrinks. */
  @HostListener('window:resize') fit() { if (this.width() !== this.clamp(this.width())) this.width.set(this.clamp(this.width())); }
}
