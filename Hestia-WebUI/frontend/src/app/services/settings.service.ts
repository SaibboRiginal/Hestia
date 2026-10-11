import { Injectable, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { SessionSettings } from '../models/chat.models';

/** How the reasoning of an answer is shown (WebUI presentation, saved by the WebUI backend). */
export type ThinkingDisplay = 'hidden' | 'compact' | 'detailed' | 'live';
export const THINKING_DISPLAY_OPTIONS: { value: ThinkingDisplay; label: string; title: string }[] = [
  { value: 'hidden', label: 'Nascosto', title: 'Solo la risposta' },
  { value: 'compact', label: 'Compatto', title: 'Riquadro chiuso, un passo per riga' },
  { value: 'detailed', label: 'Dettagliato', title: 'Riquadro aperto con ragionamento e risultati completi' },
  { value: 'live', label: 'Dal vivo', title: 'Aperto mentre lavora, si chiude quando risponde' },
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
