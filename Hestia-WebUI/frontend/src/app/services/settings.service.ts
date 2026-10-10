import { Injectable, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { SessionSettings } from '../models/chat.models';

@Injectable({ providedIn: 'root' })
export class SettingsService {
  private http = inject(HttpClient);
  private apiBase = '/api/webui/settings';

  settings = signal<SessionSettings>({
    tone: 'warm',
    customPrompt: '',
    thinkingDisplay: 'hidden'
  });

  async load(): Promise<void> {
    try {
      const resp = await firstValueFrom(
        this.http.get<{ settings: SessionSettings }>(this.apiBase)
      );
      this.settings.set(resp.settings);
    } catch {
      // Use defaults
    }
  }

  async update(partial: Partial<SessionSettings>): Promise<void> {
    const resp = await firstValueFrom(
      this.http.put<{ settings: SessionSettings }>(this.apiBase, partial)
    );
    this.settings.set(resp.settings);
  }

  async reset(): Promise<void> {
    const resp = await firstValueFrom(
      this.http.post<{ settings: SessionSettings }>(`${this.apiBase}/reset`, {})
    );
    this.settings.set(resp.settings);
  }
}
