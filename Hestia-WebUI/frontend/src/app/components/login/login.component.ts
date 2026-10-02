import { Component, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { AuthService } from '../../services/auth.service';

@Component({
  selector: 'app-login',
  standalone: true,
  imports: [FormsModule],
  template: `
    <div class="login-container">
      <div class="login-card">
        <div class="login-icon">🏛️</div>
        <h1>Hestia</h1>
        <p class="login-subtitle">Enter your access token to continue</p>
        <div class="login-input-group">
          <input
            type="password"
            [(ngModel)]="token"
            placeholder="Paste your access token..."
            (keydown.enter)="submit()"
            [disabled]="loading"
            class="token-input"
            autofocus
          />
          <button (click)="submit()" [disabled]="!token || loading" class="login-btn">
            @if (!loading) { <span>Connect</span> }
            @if (loading) { <span class="spinner"></span> }
          </button>
        </div>
        @if (error) { <p class="login-error">{{ error }}</p> }
        <p class="login-info">Get your token via <code>/webui_token</code> in Telegram</p>
      </div>
    </div>
  `,
  styles: [`
    .login-container {
      display: flex; align-items: center; justify-content: center;
      height: 100vh; background: var(--bg-primary);
    }
    .login-card {
      text-align: center; width: 100%; max-width: 420px;
      padding: 48px 32px; animation: fadeIn 0.4s ease;
    }
    .login-icon { font-size: 64px; margin-bottom: 16px; }
    h1 { font-size: 32px; font-weight: 700; margin-bottom: 8px; color: var(--text-primary); }
    .login-subtitle { color: var(--text-secondary); margin-bottom: 32px; font-size: 15px; }
    .login-input-group { display: flex; gap: 8px; }
    .token-input {
      flex: 1; padding: 14px 18px; background: var(--bg-input);
      border: 1px solid var(--border); border-radius: var(--radius-lg);
      color: var(--text-primary); font-size: 15px; outline: none;
      transition: border-color var(--transition-fast); font-family: 'JetBrains Mono', monospace;
    }
    .token-input:focus { border-color: var(--accent); }
    .login-btn {
      padding: 14px 28px; background: var(--accent); color: white;
      border: none; border-radius: var(--radius-lg); font-size: 15px;
      font-weight: 600; cursor: pointer; transition: background var(--transition-fast);
      white-space: nowrap; min-width: 110px;
    }
    .login-btn:hover:not(:disabled) { background: var(--accent-hover); }
    .login-btn:disabled { opacity: 0.5; cursor: not-allowed; }
    .login-error { color: var(--danger); margin-top: 16px; font-size: 14px; }
    .login-info { color: var(--text-muted); margin-top: 24px; font-size: 13px; }
    .login-info code { background: var(--bg-tertiary); padding: 2px 8px; border-radius: var(--radius-sm); }
    .spinner {
      display: inline-block; width: 18px; height: 18px;
      border: 2px solid rgba(255,255,255,0.3); border-top-color: white;
      border-radius: 50%; animation: spin 0.6s linear infinite;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
  `]
})
export class LoginComponent {
  private auth = inject(AuthService);
  private router = inject(Router);

  token = '';
  loading = false;
  error = '';

  async submit(): Promise<void> {
    if (!this.token.trim()) return;
    this.loading = true;
    this.error = '';
    const ok = await this.auth.login(this.token.trim());
    this.loading = false;
    if (ok) {
      this.router.navigate(['/']);
    } else {
      this.error = 'Invalid or expired token. Get a new one via /webui_token in Telegram.';
    }
  }
}
