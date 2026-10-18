import { Injectable, signal, computed, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private http = inject(HttpClient);
  private apiBase = '/api/webui';
  private accessCheck: Promise<boolean> | null = null;

  token = signal<string | null>(localStorage.getItem('hestia_token'));
  /** Opened from the home network: the server needs no token (never through the Cloudflare tunnel). */
  local = signal(false);
  isAuthenticated = computed(() => this.local() || (this.token() !== null && this.token()!.length >= 32));

  /** Asks the server once whether this browser needs the token. Error → token required. */
  checkAccess(): Promise<boolean> {
    this.accessCheck ??= firstValueFrom(
      this.http.get<{ local: boolean; tokenRequired: boolean }>(`${this.apiBase}/auth/access`)
    ).then(r => {
      const local = !!r?.local && !r.tokenRequired;
      if (local) localStorage.setItem('hestia_local', '1'); else localStorage.removeItem('hestia_local');
      return local;
    // Offline (PWA, status 0): keep the last answer so the home-network app still opens without a token.
    }).catch(e => e?.status === 0 && localStorage.getItem('hestia_local') === '1').then(local => {
      this.local.set(local);
      return local;
    });
    return this.accessCheck;
  }

  async login(token: string): Promise<boolean> {
    try {
      const resp = await firstValueFrom(
        this.http.post<{ status: string; expiresInSeconds: number }>(
          `${this.apiBase}/auth/login`, { token }
        )
      );
      if (resp.status === 'ok') {
        this.token.set(token);
        localStorage.setItem('hestia_token', token);
        return true;
      }
    } catch {
      // Invalid token
    }
    return false;
  }

  logout(): void {
    this.token.set(null);
    this.local.set(false);
    this.accessCheck = null;   // asked again on the next navigation (e.g. local access switched off)
    localStorage.removeItem('hestia_token');
    navigator.serviceWorker?.controller?.postMessage('logout');   // drop cached catalog/settings/bundles
  }

  getToken(): string | null {
    return this.token();
  }
}
