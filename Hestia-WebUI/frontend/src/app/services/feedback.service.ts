import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';

@Injectable({ providedIn: 'root' })
export class FeedbackService {
  private http = inject(HttpClient);
  private apiBase = '/api/webui/feedback';

  async submit(label: 'good' | 'bad', text = ''): Promise<boolean> {
    const resp = await firstValueFrom(
      this.http.post<{ ok: boolean }>(this.apiBase, {
        qualityLabel: label,
        qualityScore: label === 'good' ? 4 : 2,
        feedbackText: text
      })
    );
    return resp.ok;
  }
}
