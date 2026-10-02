import { Injectable, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';

@Injectable({ providedIn: 'root' })
export class SessionService {
  private http = inject(HttpClient);
  private apiBase = '/api/webui/sessions';

  sessionId = signal<string>('');

  async load(): Promise<void> {
    try {
      const resp = await firstValueFrom(
        this.http.get<{ sessionId: string }>(`${this.apiBase}/current`)
      );
      this.sessionId.set(resp.sessionId);
    } catch {
      // Session will be created on first chat
    }
  }

  async clear(): Promise<string> {
    const resp = await firstValueFrom(
      this.http.post<{ newSessionId: string }>(`${this.apiBase}/clear`, {})
    );
    this.sessionId.set(resp.newSessionId);
    return resp.newSessionId;
  }
}
