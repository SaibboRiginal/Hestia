import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { RouterLink } from '@angular/router';
import { IconComponent } from './icon.component';

/** Where a value is set: a central setting (`key`), a module's settings (`module`) or a personal row. */
export interface SettingTarget { key?: string; module?: string; section?: string; row?: string; }

/** Query of the Impostazioni page for a target (the page opens the right view, scrolls and highlights). */
export function settingQuery(t: SettingTarget): Record<string, string> {
  if (t.key) return { key: t.key };
  if (t.section) return t.row ? { section: t.section, row: t.row } : { section: t.section };
  return t.module ? { tab: 'system', module: t.module } : {};
}

/**
 * <hx-setting-link key="oracle.chat.mode" /> — the one shortcut next to a value that comes from a setting:
 * a small «cambia» that opens Impostazioni already on that setting, highlighted. Same component everywhere
 * (dossier docs/work/2026-11-12-contesto-e-scorciatoie §3.3). `key` = central setting · `module` = that module's
 * settings · `section` (+ `row`) = a personal one. `label=""` shows the gear alone.
 */
@Component({
  selector: 'hx-setting-link',
  imports: [RouterLink, IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <a routerLink="/settings" [queryParams]="query()" [attr.title]="hint()" [attr.aria-label]="hint()" (click)="go.emit()">
      <hx-icon name="settings" [size]="13" />@if (label()) { <span>{{ label() }}</span> }
    </a>`,
  styles: [`
    :host { display: inline-flex; }
    a { display: inline-flex; align-items: center; gap: 4px; min-height: 22px; padding: 0 6px; border-radius: var(--radius-full);
        font-size: 11.5px; font-weight: 500; color: var(--text-3); text-decoration: none; white-space: nowrap; }
    a:hover, a:focus-visible { color: var(--accent); background: var(--surface-2); }
  `],
})
export class SettingLinkComponent {
  key = input('');
  module = input('');
  section = input('');
  row = input('');
  label = input('cambia');
  /** Tooltip (what opens). */
  title = input('');
  /** Emitted on click, so a popover that hosts the link can close. */
  go = output<void>();

  readonly query = computed(() => settingQuery({ key: this.key(), module: this.module(), section: this.section(), row: this.row() }));
  readonly hint = computed(() => this.title() || 'Apri questa impostazione');
}
