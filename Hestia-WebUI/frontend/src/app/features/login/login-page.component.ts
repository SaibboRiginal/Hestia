import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { AuthService } from '../../services/auth.service';
import { ButtonComponent, FieldComponent } from '../../ui';

@Component({
  selector: 'app-login-page',
  imports: [FormsModule, ButtonComponent, FieldComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="wrap">
      <form class="card hx-card" (ngSubmit)="submit()">
        <div class="logo">◈</div>
        <h1>Hestia</h1>
        <p class="sub">Inserisci il token di accesso</p>
        <hx-field [error]="error()" hint="Lo ottieni con /webui_token su Telegram">
          <input class="hx-input mono" name="token" [(ngModel)]="token" type="password" autocomplete="off"
                 placeholder="token…" autofocus />
        </hx-field>
        <button hx-btn variant="primary" size="lg" block type="submit" [loading]="loading()" [disabled]="!token">Entra</button>
      </form>
    </div>`,
  styles: [`
    .wrap { height: 100vh; display: grid; place-items: center; padding: 16px; background: var(--bg); }
    .card { width: 100%; max-width: 380px; padding: 32px 28px; display: flex; flex-direction: column; gap: 14px; text-align: center; }
    .logo { font-size: 34px; color: var(--accent); }
    h1 { font-family: var(--font-serif); font-weight: 500; font-size: 28px; }
    .sub { color: var(--text-3); font-size: 14px; margin-top: -8px; }
    hx-field { text-align: left; }
  `],
})
export class LoginPageComponent {
  private auth = inject(AuthService);
  private router = inject(Router);
  token = '';
  loading = signal(false);
  error = signal('');

  async submit() {
    this.loading.set(true);
    this.error.set('');
    const ok = await this.auth.login(this.token.trim());
    this.loading.set(false);
    if (ok) this.router.navigate(['/']);
    else this.error.set('Token non valido o scaduto');
  }
}
