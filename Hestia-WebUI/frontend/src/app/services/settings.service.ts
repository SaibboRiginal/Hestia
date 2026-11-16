import { Injectable, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { SessionSettings } from '../models/chat.models';
import { tr } from '../core/i18n';

/** How the reasoning of an answer is shown (WebUI presentation, saved by the WebUI backend). */
export type ThinkingDisplay = 'hidden' | 'compact' | 'detailed' | 'live';
export const THINKING_DISPLAY_OPTIONS: { value: ThinkingDisplay; label: string; title: string }[] = [
  { value: 'hidden', label: tr('Hidden'), title: tr('Only the answer') },
  { value: 'compact', label: tr('Compact'), title: tr('Closed box, one step per line') },
  { value: 'detailed', label: tr('Detailed'), title: tr('Open box with full reasoning and results') },
  { value: 'live', label: tr('Live'), title: tr('Open while it works, closes when it answers') },
];

@Injectable({ providedIn: 'root' })
export class SettingsService {
  private http = inject(HttpClient);
  private apiBase = '/api/webui/settings';

  settings = signal<SessionSettings>({
    tone: 'warm',
    customPrompt: '',
    thinkingDisplay: 'compact'
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
