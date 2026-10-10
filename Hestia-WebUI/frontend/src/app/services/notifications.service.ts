import { Injectable, computed, inject, signal } from '@angular/core';
import { HttpClient, HttpErrorResponse, HttpParams } from '@angular/common/http';
import { Router } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { HermesPush, SignalRService } from './signalr.service';
import { ToastService } from '../ui';

/**
 * Hermes notifications in the WebUI (SPEC docs/work/2026-10-10-hermes-global-notifications).
 * Inbox = Archive through Hermes (`/api/webui/notifications*`); live pushes on SignalR.
 * Read state is global: what is seen here is seen on Telegram too, and vice versa.
 */
export type NotificationLevel = 'info' | 'success' | 'warning' | 'error';
export type NotificationFilter = 'unread' | 'pending' | 'all';
export type ToastMode = 'all' | 'important' | 'none';

export interface NotificationAction { id: string; label: string; style: string; }
export interface NotificationAnswer {
  action_id?: string; label?: string; by?: string; at?: string; status?: string; outcome_text?: string;
}
export interface HestiaNotification {
  id: string;
  created_at: string;
  updated_at?: string;
  state: string;
  read: boolean;
  pending: boolean;
  title: string;
  message: string;
  level: NotificationLevel;
  source: string;
  event_type: string;
  actions: NotificationAction[];
  audience: 'global' | 'origin';
  origin: { client: string; session_id?: string } | null;
  other_client: boolean;
  seen: { by: string; at: string } | null;
  answer: NotificationAnswer | null;
}
export interface NotificationCounts { unread: number; pending: number; }

const CLIENT = 'webui';
const PREFS_KEY = 'hestia_notification_prefs';
export const CLIENT_LABELS: Record<string, string> = { telegram: 'Telegram', webui: 'WebUI' };
export const clientLabel = (name?: string | null) => (name && CLIENT_LABELS[name]) || name || '';

@Injectable({ providedIn: 'root' })
export class NotificationsService {
  private http = inject(HttpClient);
  private signalR = inject(SignalRService);
  private toast = inject(ToastService);
  private router = inject(Router);
  private base = '/api/webui/notifications';

  readonly items = signal<HestiaNotification[]>([]);
  readonly counts = signal<NotificationCounts>({ unread: 0, pending: 0 });
  readonly loading = signal(false);
  readonly hasMore = signal(false);
  readonly filter = signal<NotificationFilter>('unread');
  readonly source = signal('');
  readonly showOtherClients = signal(false);
  readonly toastMode = signal<ToastMode>(this.readPrefs());
  /** Page open: new items are shown in place (and seen) instead of only toasted. */
  readonly pageOpen = signal(false);
  readonly busy = signal<string | null>(null);

  readonly badge = computed(() => this.counts().unread);
  readonly visible = computed(() => this.items().filter(n => this.showOtherClients() || !n.other_client));
  readonly sources = computed(() => [...new Set(this.items().map(n => n.source).filter(Boolean))].sort());

  private started = false;

  /** Called once by the shell after SignalR connects. */
  start(): void {
    if (this.started) return;
    this.started = true;
    this.signalR.notifications$.subscribe(push => this.onPush(push));
    this.signalR.reconnected$.subscribe(() => void this.refresh());
    void this.loadCounts();
  }

  // ── API ─────────────────────────────────────────────────────────────────

  async loadCounts(): Promise<void> {
    try { this.counts.set(await firstValueFrom(this.http.get<NotificationCounts>(`${this.base}/counts`))); }
    catch { /* Hermes down: badge stays as is */ }
  }

  async refresh(): Promise<void> { await this.load(false); }

  async load(more = false): Promise<void> {
    this.loading.set(true);
    try {
      let params = new HttpParams().set('filter', this.filter()).set('limit', 40);
      if (this.source()) params = params.set('source', this.source());
      const last = this.items().at(-1);
      if (more && last) params = params.set('before', last.created_at);
      const res = await firstValueFrom(this.http.get<{ items: HestiaNotification[]; counts: NotificationCounts }>(this.base, { params }));
      const items = res?.items ?? [];
      this.items.set(more ? [...this.items(), ...items] : items);
      this.hasMore.set(items.length >= 40);
      if (res?.counts) this.counts.set(res.counts);
    } catch {
      this.toast.error('Notifiche non disponibili: Hermes non risponde');
    } finally {
      this.loading.set(false);
    }
  }

  async markSeen(n: HestiaNotification): Promise<void> {
    if (n.read) return;
    this.patch(n.id, { read: true, state: 'seen', seen: { by: CLIENT, at: new Date().toISOString() } });
    this.counts.update(c => ({ ...c, unread: Math.max(0, c.unread - 1) }));
    try { await firstValueFrom(this.http.post(`${this.base}/${n.id}/seen`, {})); } catch { /* retried on next view */ }
  }

  async markAllSeen(): Promise<void> {
    try {
      await firstValueFrom(this.http.post(`${this.base}/seen-all`, {}));
      this.items.update(list => list.map(n => n.read ? n : { ...n, read: true, state: 'seen' }));
      await this.loadCounts();
      if (this.filter() === 'unread') await this.refresh();
    } catch {
      this.toast.error('Non riuscito, riprova');
    }
  }

  async answer(n: HestiaNotification, action: NotificationAction): Promise<void> {
    this.busy.set(n.id);
    try {
      const res = await firstValueFrom(this.http.post<{ status: string; answer: NotificationAnswer }>(
        `${this.base}/${n.id}/answer`, { actionId: action.id }));
      this.applyAnswer(n.id, res?.answer ?? { label: action.label, by: CLIENT, status: 'done' });
      this.toast.success(res?.answer?.outcome_text || `${action.label} ✓`);
    } catch (err) {
      const e = err as HttpErrorResponse;
      if (e.status === 409) {
        const answer: NotificationAnswer = e.error?.answer ?? {};
        this.applyAnswer(n.id, answer);
        this.toast.show(answer.by && answer.by !== CLIENT ? `Già gestita da ${clientLabel(answer.by)}` : 'Già gestita', 'info');
      } else {
        this.toast.error(`Non riuscito: ${e.error?.detail || 'riprova più tardi'}`);
      }
    } finally {
      this.busy.set(null);
      void this.loadCounts();
    }
  }

  setToastMode(mode: ToastMode): void {
    this.toastMode.set(mode);
    try { localStorage.setItem(PREFS_KEY, JSON.stringify({ toast: mode })); } catch { /* private mode */ }
  }

  // ── Live pushes ──────────────────────────────────────────────────────────

  private onPush(push: HermesPush): void {
    if (push.kind === 'notification') this.onNew(push);
    else if (push.kind === 'update') this.onUpdate(push);
  }

  private onNew(push: HermesPush): void {
    const origin = (push['origin'] as HestiaNotification['origin']) ?? null;
    const actions = (push['actions'] as NotificationAction[]) ?? [];
    const n: HestiaNotification = {
      id: push.notification_id,
      created_at: String(push['created_at'] ?? new Date().toISOString()),
      state: 'delivered', read: false, pending: actions.length > 0,
      title: String(push['title'] ?? ''), message: String(push['message'] ?? ''),
      level: (push['level'] as NotificationLevel) ?? 'info', source: String(push['source'] ?? ''),
      event_type: String(push['event_type'] ?? ''), actions,
      audience: origin ? 'origin' : 'global', origin,
      other_client: !!origin && origin.client !== CLIENT, seen: null, answer: null,
    };
    if (this.items().some(x => x.id === n.id)) return;
    if (this.filter() !== 'pending' || n.pending) {
      if (!this.source() || this.source() === n.source) this.items.update(list => [n, ...list]);
    }
    this.counts.update(c => ({ unread: c.unread + 1, pending: c.pending + (n.pending ? 1 : 0) }));
    if (push['silent']) return; // pushed to another client: inbox only

    const visible = typeof document !== 'undefined' && document.visibilityState === 'visible' && document.hasFocus();
    if (this.pageOpen() && visible) { void this.markSeen(n); return; }
    const mode = this.toastMode();
    const important = n.pending || n.level === 'warning' || n.level === 'error';
    if (mode === 'none' || (mode === 'important' && !important)) return;
    const text = n.title || plain(n.message).slice(0, 140) || 'Nuova notifica';
    this.toast.show(text, toneOf(n.level), {
      label: n.pending ? 'Rispondi' : 'Apri',
      run: () => void this.router.navigate(['/notifications']),
    }, n.pending ? 10000 : 6000);
    if (visible) void this.markSeen(n);
  }

  private onUpdate(push: HermesPush): void {
    const state = String(push['state'] ?? '');
    const known = this.items().find(x => x.id === push.notification_id);
    if (state === 'seen') {
      if (known && !known.read) {
        this.patch(known.id, { read: true, state: 'seen', seen: (push['seen'] as HestiaNotification['seen']) ?? null });
      }
    } else if (state === 'answered' || state === 'expired') {
      this.applyAnswer(push.notification_id, (push['answer'] as NotificationAnswer) ?? {}, state);
    }
    void this.loadCounts();
  }

  private applyAnswer(id: string, answer: NotificationAnswer, state = 'answered'): void {
    this.patch(id, { answer, state, pending: false, read: true });
    if (this.filter() === 'pending') this.items.update(list => list.filter(n => n.id !== id));
  }

  private patch(id: string, changes: Partial<HestiaNotification>): void {
    this.items.update(list => list.map(n => n.id === id ? { ...n, ...changes } : n));
  }

  private readPrefs(): ToastMode {
    try { return (JSON.parse(localStorage.getItem(PREFS_KEY) || '{}').toast as ToastMode) || 'all'; }
    catch { return 'all'; }
  }
}

function toneOf(level: NotificationLevel): 'info' | 'success' | 'danger' | 'warning' {
  return level === 'error' ? 'danger' : level === 'warning' ? 'warning' : level === 'success' ? 'success' : 'info';
}

/** Hermes messages are Telegram-style HTML: plain text for toasts. */
export function plain(html: string): string {
  if (typeof DOMParser === 'undefined') return html;
  // DOMParser runs no scripts/handlers (unlike innerHTML on a detached element).
  const doc = new DOMParser().parseFromString(html.replace(/<br\s*\/?>/gi, ' '), 'text/html');
  return (doc.body.textContent || '').replace(/\s+/g, ' ').trim();
}
