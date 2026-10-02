import { Injectable, signal, computed, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private http = inject(HttpClient);
  private apiBase = '/api/webui';

  token = signal<string | null>(localStorage.getItem('hestia_token'));
  isAuthenticated = computed(() => this.token() !== null && this.token()!.length >= 32);

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
    localStorage.removeItem('hestia_token');
  }

  getToken(): string | null {
    return this.token();
  }
}
