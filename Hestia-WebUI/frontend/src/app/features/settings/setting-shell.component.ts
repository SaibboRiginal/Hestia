import { ChangeDetectionStrategy, Component, input } from '@angular/core';

/**
 * <hx-setting-shell label help [wide]> control </hx-setting-shell> — the same row as <hx-setting>
 * (label + help on the left, control on the right) for settings that live in this client
 * (theme, notices…), so Personali and Sistema look and read the same. `wide` puts the control
 * under the label (theme cards, long text).
 */
@Component({
  selector: 'hx-setting-shell',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="meta">
      <div class="lbl"><span>{{ label() }}</span><ng-content select="[badge]" /></div>
      @if (help()) { <div class="help">{{ help() }}</div> }
    </div>
    <div class="ctl"><ng-content /></div>`,
  styles: [`
    :host { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 300px) 34px; gap: 6px 16px; align-items: center;
            padding: 12px 4px; border-bottom: 1px solid var(--border); }
    :host(:last-child) { border-bottom: 0; }
    :host(.wide) { grid-template-columns: minmax(0, 1fr); }
    :host(.wide) .ctl { grid-column: 1; }
    .ctl { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; min-width: 0; }
    .lbl { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; font-size: 14px; color: var(--text); font-weight: 500; }
    .help { font-size: 12.5px; color: var(--text-3); margin-top: 3px; line-height: 1.4; }
    @media (max-width: 700px) {
      :host { grid-template-columns: minmax(0, 1fr); }
    }
  `],
  host: { '[class.wide]': 'wide()' },
})
export class SettingShellComponent {
  label = input.required<string>();
  help = input('');
  wide = input(false);
}
