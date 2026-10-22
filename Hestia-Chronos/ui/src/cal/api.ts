/**
 * Chronos agenda calls of the calendar page (all under the plugin's api_prefix `/api/agenda/`). Every write is
 * marked `by: user` (a user decision wins over modules; Chronos defaults to `user` too). Errors throw `Error(detail)`.
 */
import type { ApiResult, HestiaHost, HttpMethod } from '@hestia/webui-sdk';
import type { AgendaItem, AgendaOccurrence, AgendaTemplate, AgendaType, CalWeather } from './models';

export const API = '/api/agenda';
export interface AgendaDraft { title: string; type: AgendaType; start_at: string; end_at: string | null;
                               recurrence: string | null; description: string | null; }
export type TemplateBody = { values: Record<string, unknown>; start_at: string; end_at?: string | null;
                             recurrence?: string | null; type?: string; description?: string };

export interface LogRow { ts: string; level: string; message: string; }
export interface LogsResult { service: string; from: string; to: string; count: number; oldest: string | null; logs: LogRow[]; }

export class AgendaError extends Error { constructor(msg: string, readonly offline = false) { super(msg); } }

const enc = encodeURIComponent;

export class AgendaApi {
  constructor(private host: HestiaHost) {}

  private async call<T = any>(method: HttpMethod, path: string, opts?: { query?: Record<string, any>; body?: unknown }): Promise<T> {
    const r: ApiResult<T> = await this.host.api<T>(method, `${API}${path}`, opts);
    if (!r.ok) {
      const offline = r.status === 0 || r.error === 'unreachable' || r.error === 'offline';
      throw new AgendaError(offline ? 'Chronos non raggiungibile' : r.error || 'Operazione non riuscita', offline);
    }
    return r.data;
  }

  async occurrences(start: Date, end: Date): Promise<AgendaOccurrence[]> {
    const r = await this.call<{ occurrences: AgendaOccurrence[] }>('GET', '/occurrences',
      { query: { start: start.toISOString(), end: end.toISOString(), include_done: true } });
    return r?.occurrences ?? [];
  }
  async items(): Promise<AgendaItem[]> {
    const r = await this.call<{ items: AgendaItem[] }>('GET', '/items', { query: { include_cancelled: true } });
    return r?.items ?? [];
  }
  create(body: Record<string, unknown>) {
    return this.call('POST', '/items', { body: { owner: 'user', created_by: 'user', ...body } });
  }
  update(key: string, changes: Record<string, unknown>) {
    return this.call('PATCH', `/items/${enc(key)}`, { body: { ...changes, by: 'user' } });
  }
  cancel(key: string) { return this.call('DELETE', `/items/${enc(key)}`, { query: { by: 'user' } }); }
  skip(key: string, occurrence?: string) { return this.call('POST', `/items/${enc(key)}/skip`, { body: { occurrence, by: 'user' } }); }
  unskip(key: string, occurrence: string) { return this.call('POST', `/items/${enc(key)}/unskip`, { body: { occurrence, by: 'user' } }); }
  move(key: string, occurrence: string, start_at: string | null, end_at: string | null, reset = false) {
    return this.call('POST', `/items/${enc(key)}/move`, { body: { occurrence, start_at, end_at, reset, by: 'user' } });
  }
  run(key: string) { return this.call<{ ok: boolean; detail: string }>('POST', `/items/${enc(key)}/run`); }
  async templates(): Promise<AgendaTemplate[]> {
    const r = await this.call<{ templates: AgendaTemplate[] }>('GET', '/templates');
    return r?.templates ?? [];
  }
  fromTemplate(owner: string, id: string, body: TemplateBody) {
    return this.call('POST', `/templates/${enc(owner)}/${enc(id)}/create`, { body });
  }
  /** Natural-language quick add → draft for the editor (Chronos asks Oracle; nothing is created). */
  async parse(text: string): Promise<AgendaDraft> {
    const r = await this.call<{ draft: AgendaDraft }>('POST', '/parse', { body: { text, tz: Intl.DateTimeFormat().resolvedOptions().timeZone } });
    return r.draft;
  }
  /** Weather for the visible days (next 14 only): Casa per day, located occurrences, own located events. */
  weather(start: Date, end: Date, located: { key: string; place: string; at: string }[]) {
    return this.call<CalWeather>('POST', '/weather', { body: { start: start.toISOString(), end: end.toISOString(), located } });
  }
  /** A module's logs around an occurrence (its in-memory buffer: recent hours only), read by Chronos through Hub. */
  logs(service: string, at: string, minutes = 5) {
    return this.call<LogsResult>('GET', '/logs', { query: { service, at, minutes } });
  }
  /** The read-only iCalendar file (the Hub hands non-JSON answers over as {raw}). */
  async ics(): Promise<string> {
    const r = await this.call<any>('GET', '/ics', { query: { days: 60 } });
    const text = typeof r === 'string' ? r : r?.raw ?? '';
    if (!String(text).startsWith('BEGIN:VCALENDAR')) throw new AgendaError('Chronos non ha restituito un calendario');
    return text;
  }
}
