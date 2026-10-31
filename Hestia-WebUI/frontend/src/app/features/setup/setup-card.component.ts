import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { UI } from '../../ui';
import { SetupApi, SetupState } from './setup.api';

const LABELS: Record<string, string> = { cervello: 'cervello', telegram: 'Telegram', backup: 'backup', esterni: 'account esterni' };

/** Home card «Da finire»: what the guided setup left for later (no nag, it just stays here until done). */
@Component({
  selector: 'hx-setup-card',
  imports: [...UI, RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (open().length) {
      <a class="card hx-card" routerLink="/benvenuto">
        <hx-icon name="sparkle" [size]="18" tone="accent" />
        <span class="t"><b>Da finire</b><small>{{ open().join(' · ') }}</small></span>
        <hx-icon name="chevron-right" [size]="16" tone="muted" />
      </a>
    }`,
  styles: [`
    .card { display: flex; align-items: center; gap: 12px; padding: 12px 14px; margin: 0 0 14px; color: var(--text); text-decoration: none; }
    .t { flex: 1; display: flex; flex-direction: column; gap: 2px; min-width: 0; }
    b { font-weight: 600; font-size: 14px; }
    small { color: var(--text-3); font-size: 13px; }
  `],
})
export class SetupCardComponent {
  private state = signal<SetupState | null>(null);
  open = computed(() => {
    const s = this.state();
    if (!s) return [];
    const left = s.later.filter(k => k !== 'esterni' && !(k === 'telegram' && s.telegram.linked) && !(k === 'backup' && s.backup.passphrase));
    if (!s.completed && !s.brain.recipe && !left.includes('cervello')) left.unshift('cervello');
    return left.map(k => LABELS[k] || k);
  });

  constructor() {
    inject(SetupApi).state().then(s => this.state.set(s)).catch(() => undefined);
  }
}
