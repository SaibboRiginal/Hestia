import { ChangeDetectionStrategy, Component, input } from '@angular/core';

/** <hx-logo>: the hearth seen from above, a ring with the fire in the middle (docs/work/2026-11-27-webui-rethink §3.6).
 *  Drawn in the theme's colours (--accent, --accent-2), so it follows every theme; never tied to the mascot. */
@Component({
  selector: 'hx-logo',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <svg [attr.width]="size()" [attr.height]="size()" viewBox="0 0 32 32" aria-hidden="true">
      <circle cx="16" cy="16" r="12.5" fill="none" stroke="var(--accent)" stroke-width="3" />
      <circle cx="16" cy="16" r="5.5" fill="var(--accent-2, var(--accent))" />
    </svg>`,
  styles: [`:host { display: inline-grid; flex-shrink: 0; }`],
})
export class LogoComponent {
  readonly size = input(28);
}
