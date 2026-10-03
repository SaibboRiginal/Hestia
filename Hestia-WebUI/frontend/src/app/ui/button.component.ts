import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { IconComponent } from './icon.component';

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'subtle';
export type ButtonSize = 'sm' | 'md' | 'lg';

/**
 * <button hx-btn variant="primary" icon="plus">Nuovo</button>
 * <button hx-btn variant="ghost" icon="x" iconOnly aria-label="Chiudi"></button>
 * Works on <button> and <a>. Variants: primary | secondary | ghost | danger | subtle.
 */
@Component({
  selector: 'button[hx-btn], a[hx-btn]',
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: {
    class: 'hx-btn',
    '[class.hx-btn--primary]': "variant() === 'primary'",
    '[class.hx-btn--secondary]': "variant() === 'secondary'",
    '[class.hx-btn--ghost]': "variant() === 'ghost'",
    '[class.hx-btn--danger]': "variant() === 'danger'",
    '[class.hx-btn--subtle]': "variant() === 'subtle'",
    '[class.hx-btn--sm]': "size() === 'sm'",
    '[class.hx-btn--lg]': "size() === 'lg'",
    '[class.hx-btn--icon]': 'iconOnly()',
    '[class.hx-btn--block]': 'block()',
    '[class.hx-btn--loading]': 'loading()',
  },
  template: `
    @if (loading()) { <span class="hx-btn__spin"></span> }
    @else if (icon()) { <hx-icon [name]="icon()!" [size]="size() === 'sm' ? 15 : 17" /> }
    <ng-content />
    @if (iconRight()) { <hx-icon [name]="iconRight()!" [size]="size() === 'sm' ? 15 : 17" /> }
  `,
  styles: [`
    :host {
      display: inline-flex; align-items: center; justify-content: center; gap: 6px;
      height: 34px; padding: 0 14px; border-radius: var(--radius-md);
      font-size: 14px; font-weight: 500; white-space: nowrap; user-select: none;
      border: 1px solid transparent; color: var(--text);
      transition: background var(--dur-fast) var(--ease), border-color var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease), transform var(--dur-fast) var(--ease);
      text-decoration: none !important;
    }
    :host(:active:not([disabled])) { transform: translateY(1px); }
    :host([disabled]) { opacity: .5; cursor: not-allowed; }
    :host(.hx-btn--primary) { background: var(--accent); color: var(--accent-contrast); }
    :host(.hx-btn--primary:hover:not([disabled])) { background: var(--accent-hover); }
    :host(.hx-btn--secondary) { background: var(--surface); border-color: var(--border-strong); }
    :host(.hx-btn--secondary:hover:not([disabled])) { background: var(--surface-2); }
    :host(.hx-btn--ghost) { background: transparent; color: var(--text-2); }
    :host(.hx-btn--ghost:hover:not([disabled])) { background: var(--surface-2); color: var(--text); }
    :host(.hx-btn--subtle) { background: var(--surface-2); }
    :host(.hx-btn--subtle:hover:not([disabled])) { background: var(--surface-3); }
    :host(.hx-btn--danger) { background: var(--danger); color: #fff; }
    :host(.hx-btn--danger:hover:not([disabled])) { filter: brightness(1.08); }
    :host(.hx-btn--sm) { height: 28px; padding: 0 10px; font-size: 13px; border-radius: var(--radius-sm); }
    :host(.hx-btn--lg) { height: 42px; padding: 0 20px; font-size: 15px; }
    :host(.hx-btn--icon) { width: 34px; padding: 0; }
    :host(.hx-btn--icon.hx-btn--sm) { width: 28px; }
    :host(.hx-btn--icon.hx-btn--lg) { width: 42px; }
    :host(.hx-btn--block) { width: 100%; }
    :host(.hx-btn--loading) { pointer-events: none; }
    .hx-btn__spin { width: 14px; height: 14px; border: 2px solid currentColor; border-right-color: transparent;
                    border-radius: 50%; animation: hx-spin .7s linear infinite; }
  `],
})
export class ButtonComponent {
  variant = input<ButtonVariant>('secondary');
  size = input<ButtonSize>('md');
  icon = input<string | null>(null);
  iconRight = input<string | null>(null);
  iconOnly = input(false, { transform: (v: boolean | string) => v === '' || v === true || v === 'true' });
  block = input(false, { transform: (v: boolean | string) => v === '' || v === true || v === 'true' });
  loading = input(false);
}
