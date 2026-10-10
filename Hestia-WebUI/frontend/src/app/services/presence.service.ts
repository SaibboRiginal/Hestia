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

const EFFECT_LABELS: Record<string, Record<string, string>> = {
  'work.heavy': { allow: 'lavori pesanti: sì', local: 'lavori pesanti: solo locali', defer: 'lavori pesanti: rimandati' },
  'llm.claude': { allow: 'Claude: libero', save: 'Claude: solo per le tue chat', deny: 'Claude: no' },
  'notify.level': { all: 'notifiche: tutte', important: 'notifiche: solo importanti', urgent: 'notifiche: solo urgenti' },
};

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
    return Object.keys(EFFECT_LABELS).filter(k => e[k]).map(k => EFFECT_LABELS[k][e[k]] ?? `${k}: ${e[k]}`);
  });

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
