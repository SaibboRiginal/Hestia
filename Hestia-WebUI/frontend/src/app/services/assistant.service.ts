import { Injectable, inject, signal } from '@angular/core';
import { Observable, Subject } from 'rxjs';
import { SignalRService } from './signalr.service';

/**
 * Context packet of "Crea con Hestia": where the user opened the assistant from.
 * `label` is shown in the drawer; the rest goes to Oracle as client instructions of the turn.
 */
export interface AssistantContext {
  page: 'calendar' | 'forge' | 'commands' | 'chat' | 'documents' | 'settings' | string;
  intent?: 'create' | 'modify' | 'explain' | 'ask' | string;
  label?: string;                       // e.g. "Agenda · lun 6 ott, 15:00"
  hints?: Record<string, string | number | boolean | null | undefined>;
  suggestions?: string[];               // starter prompts for this context
  prompt?: string;                      // prefill (not sent automatically)
}

/** Notice kinds that change data shown by pages (calendar, Sviluppo, commands). */
const CHANGE_KINDS = ['agenda.planned', 'action.done', 'forge.task', 'subscription.added', 'subscription.changed', 'subscription.removed'];

/**
 * Opens the "Crea con Hestia" drawer from any page (`open(ctx)`) and tells pages when the
 * assistant changed something (`changed$`: agenda/Forge/action notices), so they reload live.
 */
@Injectable({ providedIn: 'root' })
export class AssistantService {
  private signalR = inject(SignalRService);
  readonly isOpen = signal(false);
  readonly context = signal<AssistantContext | null>(null);
  /** Bumped on every open(): the drawer applies a new prompt/context even if already open. */
  readonly openSeq = signal(0);

  private changedSubject = new Subject<string>();
  /** Emits the notice kind (debounced per animation frame) after the assistant changed data. */
  readonly changed$: Observable<string> = this.changedSubject.asObservable();
  private pending: string | null = null;

  constructor() {
    this.signalR.events$.subscribe(e => {
      if (e.type === 'notice' && e.kind && CHANGE_KINDS.includes(e.kind)) this.emitChanged(e.kind);
    });
  }

  open(ctx: AssistantContext | null = null) {
    this.context.set(ctx);
    this.openSeq.update(n => n + 1);
    this.isOpen.set(true);
  }

  close() { this.isOpen.set(false); }
  toggle(ctx: AssistantContext | null = null) { this.isOpen() ? this.close() : this.open(ctx ?? this.context() ?? this.guessContext()); }

  /** Opened without an explicit packet (sidebar, Ctrl+J): the current page is still useful context. */
  guessContext(): AssistantContext {
    const page = location.pathname.split('/').filter(Boolean)[0] || 'chat';
    const labels: Record<string, string> = { calendar: 'Agenda di Hestia', forge: 'Sviluppo', commands: 'Comandi & MCP', documents: 'Documenti', settings: 'Impostazioni' };
    return { page, intent: 'ask', label: labels[page] };
  }

  /** Compact "key=value; …" packet for Oracle (caveman style: every token is paid). */
  static serialize(ctx: AssistantContext | null): string {
    if (!ctx) return '';
    const parts = [`page=${ctx.page}`];
    if (ctx.intent) parts.push(`intent=${ctx.intent}`);
    for (const [k, v] of Object.entries(ctx.hints ?? {})) {
      if (v !== undefined && v !== null && v !== '') parts.push(`${k}=${String(v).replace(/[;\n]/g, ' ').slice(0, 300)}`);
    }
    parts.push(`ora=${new Date().toISOString().slice(0, 16)}`, `tz=${Intl.DateTimeFormat().resolvedOptions().timeZone}`);
    return parts.join('; ');
  }

  private emitChanged(kind: string) {
    if (this.pending) return;
    this.pending = kind;
    // Several notices of one answer → one reload.
    setTimeout(() => { const k = this.pending!; this.pending = null; this.changedSubject.next(k); }, 400);
  }
}
