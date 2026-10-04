import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { AgendaItem, AgendaOccurrence, AgendaTemplate } from './calendar.models';

export interface AgendaDraft { title: string; type: 'event' | 'task' | 'job' | 'window'; start_at: string; end_at: string | null;
                              recurrence: string | null; description: string | null; }
export interface LogRow { ts: string; level: string; logger: string; message: string; }
export interface LogsResult { service: string; from: string; to: string; count: number; oldest: string | null; logs: LogRow[]; }

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
  async templates(): Promise<AgendaTemplate[]> {
    const r = await firstValueFrom(this.http.get<{ templates: AgendaTemplate[] }>(`${this.base}/templates`));
    return r?.templates ?? [];
  }
  fromTemplate(owner: string, id: string, body: { values: Record<string, unknown>; start_at: string; end_at?: string | null;
                                                  recurrence?: string | null; type?: string; description?: string }) {
    return firstValueFrom(this.http.post<{ item: AgendaItem }>(
      `${this.base}/templates/${encodeURIComponent(owner)}/${encodeURIComponent(id)}/create`, body));
  }
  /** Natural-language quick add → draft for the editor (nothing is created). */
  async parse(text: string): Promise<AgendaDraft> {
    const r = await firstValueFrom(this.http.post<{ draft: AgendaDraft }>(`${this.base}/parse`,
      { text, tz: Intl.DateTimeFormat().resolvedOptions().timeZone }));
    return r.draft;
  }
  /** Service logs around an occurrence (in-memory buffer of the service: recent hours only). */
  logs(service: string, at: string, minutes = 5, contains = '') {
    let params = new HttpParams().set('service', service).set('at', at).set('minutes', minutes);
    if (contains) params = params.set('contains', contains);
    return firstValueFrom(this.http.get<LogsResult>(`${this.base}/logs`, { params }));
  }
  feedInfo() {
    return firstValueFrom(this.http.get<{ keyConfigured: boolean; path: string; key: string | null }>(`${this.base}/feed-info`));
  }
  async feedFile(): Promise<Blob> {
    return firstValueFrom(this.http.get(`${this.base}/feed.ics`, { responseType: 'blob' }));
  }
  run(key: string) {
    return firstValueFrom(this.http.post<{ ok: boolean; detail: string }>(`${this.base}/items/${encodeURIComponent(key)}/run`, {}));
  }
}
