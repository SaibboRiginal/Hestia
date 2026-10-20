import { Injectable, computed, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { ToastService } from '../ui';

/**
 * Assistant presence (SPEC docs/work/2026-10-10-assistant-presence): the state Chronos computes
 * from signals (last interaction, running jobs, night window…) — "Sveglio · Occupato: Forge".
 * Read-only here except «Non disturbare». Refreshed every minute and when the tab comes back.
 */
export interface PresenceActivity { key: string; label?: string; load?: string; resource?: string; kind?: string; since?: string; }
export interface PresenceState {
  base: string;
  base_label: string;
  emoji: string;
  label: string;
  help?: string;
  dnd_minutes?: number;
  overlays: { key: string; label: string; emoji: string }[];
  effects: Record<string, string>;
  enabled: boolean;
  since?: string;
  last_interaction_at?: string | null;
  last_interaction_client?: string | null;
  idle_minutes?: number | null;
  dnd_until?: string | null;
  activities: PresenceActivity[];
}

export interface PresenceChange { at?: string; base: string; label: string; from?: string | null; from_label?: string | null; reason?: string; }

/** What the current state changes in the system, in plain words (one line per effect). */
const EFFECT_LABELS: Record<string, Record<string, string>> = {
  'work.heavy': {
    allow: 'Forge e addestramenti possono partire',
    local: 'Lavori pesanti solo con i modelli locali',
    defer: 'Forge e addestramenti aspettano che tu sia via',
  },
  'llm.claude': {
    allow: 'Claude usabile anche dai lavori automatici (es. Forge di notte)',
    save: 'Claude solo per le tue richieste: niente consumi automatici',
    deny: 'Claude non viene usato',
  },
  'chat.reply': {
    live: '',
    queued: 'Oracle è offline: i messaggi in chat restano in coda e avranno risposta appena torna',
  },
  'notify.level': {
    all: 'Ti arrivano tutte le notifiche',
    important: 'Solo notifiche importanti, le altre in un riepilogo dopo',
    urgent: 'Solo notifiche urgenti, le altre in un riepilogo dopo',
  },
};

/** Why a state change happened, from the engine's reason ("interaction:webui:ui", "activity_start:forge.task"…). */
export function reasonLabel(r?: string): string {
  if (!r) return '';
  const [kind, a] = r.split(':');
  switch (kind) {
    case 'interaction': return `hai interagito (${a})`;
    case 'activity_start': return 'iniziato un lavoro';
    case 'activity_stop': return 'finito un lavoro';
    case 'dnd_on': return 'Non disturbare attivato';
    case 'dnd_off': return 'Non disturbare spento';
    case 'tick': case 'read': return 'tempo trascorso';
    case 'settings': return 'impostazioni cambiate';
    case 'boot': return 'riavvio';
    case 'signal': case 'clear':
      if (a?.startsWith('resource.claude')) return 'quota Claude';
      if (a?.startsWith('health.')) return 'moduli in errore';
      if (a?.startsWith('oracle.offline')) return 'Oracle offline o tornato';
      if (a?.startsWith('manual.dnd')) return 'Non disturbare scaduto';
      return '';
    default: return '';
  }
}

export function ago(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined) return 'mai';
  if (minutes < 1) return 'adesso';
  if (minutes < 60) return `${Math.floor(minutes)} min fa`;
  if (minutes < 48 * 60) return `${Math.floor(minutes / 60)} h fa`;
  return `${Math.floor(minutes / 1440)} giorni fa`;
}

@Injectable({ providedIn: 'root' })
export class PresenceService {
  private http = inject(HttpClient);
  private toast = inject(ToastService);
  private base = '/api/webui/presence';
  private timer: ReturnType<typeof setInterval> | null = null;

  readonly state = signal<PresenceState | null>(null);
  readonly history = signal<PresenceChange[] | null>(null);
  readonly busy = signal(false);
  readonly tone = computed(() => {
    const s = this.state();
    if (!s) return 'off';
    if (s.base === 'awake') return 'awake';
    if (s.base === 'dnd') return 'dnd';
    if (s.base === 'deep_sleep' || s.base === 'nap') return 'sleep';
    return 'idle';
  });
  readonly effects = computed(() => {
    const e = this.state()?.effects ?? {};
    return Object.keys(EFFECT_LABELS).filter(k => e[k]).map(k => EFFECT_LABELS[k][e[k]] ?? `${k}: ${e[k]}`)
      .filter(Boolean);
  });
  /** Oracle offline (presence overlay, SPEC oracle-offline): chat messages wait in a queue. */
  readonly chatQueued = computed(() => this.state()?.effects?.['chat.reply'] === 'queued');

  start(): void {
    if (this.timer) return;
    void this.refresh();
    this.timer = setInterval(() => { if (!document.hidden) void this.refresh(); }, 60_000);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) void this.refresh(); });
  }

  async refresh(): Promise<void> {
    try { this.state.set(await firstValueFrom(this.http.get<PresenceState>(this.base))); }
    catch { /* Chronos down: keep the last state */ }
  }

  async loadHistory(): Promise<void> {
    try {
      const res = await firstValueFrom(this.http.get<{ items: PresenceChange[] }>(`${this.base}/history`, { params: { limit: 15 } }));
      this.history.set(res.items ?? []);
    } catch { this.history.set([]); }
  }

  async dnd(on: boolean, minutes?: number): Promise<void> {
    this.busy.set(true);
    try {
      const res = on
        ? await firstValueFrom(this.http.post<PresenceState>(`${this.base}/dnd`, minutes ? { minutes } : {}))
        : await firstValueFrom(this.http.delete<PresenceState>(`${this.base}/dnd`));
      this.state.set(res);
      this.toast.success(on ? 'Non disturbare attivo' : 'Non disturbare spento');
    } catch {
      this.toast.error('Stato non raggiungibile (Chronos)');
    } finally {
      this.busy.set(false);
    }
  }
}
