import { Injectable, computed, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { ToastService } from '../ui';
import { tr } from '../core/i18n';

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
  /** WebUI stroke icon + intent colour (the emoji is for Telegram). */
  icon?: string;
  tone?: string;
  label: string;
  help?: string;
  dnd_minutes?: number;
  overlays: { key: string; label: string; emoji: string; icon?: string; tone?: string }[];
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
    allow: tr('Forge and trainings can start'),
    local: tr('Heavy jobs only with the local models'),
    defer: tr('Forge and trainings wait until you are away'),
  },
  'llm.claude': {
    allow: tr('Claude usable by automatic jobs too (e.g. Forge at night)'),
    save: tr('Claude only for your requests: no automatic usage'),
    deny: tr('Claude is not used'),
  },
  'chat.reply': {
    live: '',
    queued: tr('I can\'t answer right now: chat messages stay in the queue and get an answer as soon as possible'),
  },
  'notify.level': {
    all: tr('You get all notifications'),
    important: tr('Only important notifications, the others in a summary later'),
    urgent: tr('Only urgent notifications, the others in a summary later'),
  },
};

/** Why a state change happened, from the engine's reason ("interaction:webui:ui", "activity_start:forge.task"…). */
export function reasonLabel(r?: string): string {
  if (!r) return '';
  const [kind, a] = r.split(':');
  switch (kind) {
    case 'interaction': return tr("you interacted ({0})", a);
    case 'activity_start': return tr('started a job');
    case 'activity_stop': return tr('finished a job');
    case 'dnd_on': return tr('Do not disturb turned on');
    case 'dnd_off': return tr('Do not disturb off');
    case 'tick': case 'read': return tr('time passed');
    case 'settings': return tr('settings changed');
    case 'boot': return tr('restart');
    case 'signal': case 'clear':
      if (a?.startsWith('resource.claude')) return tr('Claude quota');
      if (a?.startsWith('health.')) return tr('modules with errors');
      if (a?.startsWith('oracle.offline')) return tr('not available or available again');
      if (a?.startsWith('manual.dnd')) return tr('Do not disturb expired');
      return '';
    default: return '';
  }
}

export function ago(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined) return 'never';
  if (minutes < 1) return 'now';
  if (minutes < 60) return `${Math.floor(minutes)} min fa`;
  if (minutes < 48 * 60) return `${Math.floor(minutes / 60)} h fa`;
  return tr("{0} days ago", Math.floor(minutes / 1440));
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
  /** Icon of the state that matters most: the first overlay, else the base. */
  readonly icon = computed(() => {
    const s = this.state();
    const top = s?.overlays?.find(o => o.icon) ?? s;
    return { name: top?.icon || 'pulse', tone: top?.tone || '' };
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
      this.toast.success(on ? tr('Do not disturb active') : tr('Do not disturb off'));
    } catch {
      this.toast.error(tr('Status not available'));
    } finally {
      this.busy.set(false);
    }
  }
}
