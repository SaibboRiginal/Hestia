import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { AgendaItem, AgendaOccurrence } from './calendar.models';

/** WebUI backend → Hub → Chronos. Every write is marked by=user (user decision wins over modules). */
@Injectable({ providedIn: 'root' })
export class AgendaApi {
  private http = inject(HttpClient);
  private base = '/api/webui/agenda';

  async occurrences(start: Date, end: Date): Promise<AgendaOccurrence[]> {
    const params = new HttpParams().set('start', start.toISOString()).set('end', end.toISOString()).set('includeDone', 'true');
    const r = await firstValueFrom(this.http.get<{ occurrences: AgendaOccurrence[] }>(`${this.base}/occurrences`, { params }));
    return r?.occurrences ?? [];
  }

  async items(): Promise<AgendaItem[]> {
    const r = await firstValueFrom(this.http.get<{ items: AgendaItem[] }>(`${this.base}/items`));
    return r?.items ?? [];
  }

  create(body: Partial<AgendaItem> & { title: string; start_at: string }) {
    return firstValueFrom(this.http.post<{ item: AgendaItem }>(`${this.base}/items`, body));
  }
  update(key: string, changes: Record<string, unknown>) {
    return firstValueFrom(this.http.patch<{ item: AgendaItem }>(`${this.base}/items/${encodeURIComponent(key)}`, changes));
  }
  cancel(key: string) {
    return firstValueFrom(this.http.delete<{ item: AgendaItem }>(`${this.base}/items/${encodeURIComponent(key)}`));
  }
  skip(key: string, occurrence?: string) {
    return firstValueFrom(this.http.post<{ item: AgendaItem }>(`${this.base}/items/${encodeURIComponent(key)}/skip`, { occurrence }));
  }
  unskip(key: string, occurrence: string) {
    return firstValueFrom(this.http.post<{ item: AgendaItem }>(`${this.base}/items/${encodeURIComponent(key)}/unskip`, { occurrence }));
  }
  move(key: string, occurrence: string, start_at: string | null, end_at: string | null, reset = false) {
    return firstValueFrom(this.http.post<{ item: AgendaItem }>(`${this.base}/items/${encodeURIComponent(key)}/move`,
      { occurrence, start_at, end_at, reset }));
  }
  run(key: string) {
    return firstValueFrom(this.http.post<{ ok: boolean; detail: string }>(`${this.base}/items/${encodeURIComponent(key)}/run`, {}));
  }
}
