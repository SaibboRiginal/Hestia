import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';

@Injectable({ providedIn: 'root' })
export class FeedbackService {
  private http = inject(HttpClient);
  private apiBase = '/api/webui/feedback';

  async submit(label: 'good' | 'bad', text = '', ctx: { interactionId?: string; prompt?: string; response?: string } = {}): Promise<boolean> {
    try {
      const resp = await firstValueFrom(
        this.http.post<{ ok: boolean }>(this.apiBase, {
          qualityLabel: label,
          qualityScore: label === 'good' ? 4 : 2,
          feedbackText: text,
          interactionId: ctx.interactionId,
          prompt: ctx.prompt,
          response: ctx.response,
        })
      );
      return resp.ok;
    } catch {
      return false;
    }
  }
}
