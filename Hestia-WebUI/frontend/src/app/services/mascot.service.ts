import { Injectable, inject, signal } from '@angular/core';
import { tr } from '../core/i18n';
import { ToastService } from '../ui/overlays';

/** How the assistant/mascot answers an event: the character side plays its own pose for each kind. */
export type ReactionKind = 'cheer' | 'proud' | 'comfort' | 'nudge';

export interface ReactionAction { label: string; prompt?: string }

export interface Reaction { id: number; kind: ReactionKind; text?: string; action?: ReactionAction; at: number }

interface Rule { (data: Record<string, unknown>, module: string): Omit<Reaction, 'id' | 'at'> | null }

/** Fixed rules (no model): a page event → a short reaction. Texts in the owner's language. */
const RULES: Record<string, Rule> = {
  mood_logged: d => {
    const score = Number(d['score'] ?? d['mood'] ?? 0);
    if (score && score <= 2) return { kind: 'comfort', text: tr("I'm here, if you want to talk about it."),
      action: { label: tr('Talk about it'), prompt: tr("Today I'm not feeling great") } };
    if (score >= 4) return { kind: 'cheer', text: tr('Glad to hear it!') };
    return { kind: 'cheer', text: tr('Noted, thank you.') };
  },
  workout_done: d => Number(d['records'] ?? 0) > 0
    ? { kind: 'proud', text: tr('New record! Well done.') }
    : { kind: 'cheer', text: tr('Workout done, well done!') },
  deadline_done: () => ({ kind: 'cheer', text: tr('One less thing to think about.') }),
  budget_over: d => ({ kind: 'nudge', text: d['category'] ? tr('«{0}» is over budget this month.', d['category']) : tr('This month is over budget.'),
    action: { label: tr('Where can I save?'), prompt: tr('Where can I save this month?') } }),
  item_added: () => ({ kind: 'cheer' }),
};

/** One reaction at a time, and not more often than this: the site never nags. */
const QUIET_MS = 15_000;

/**
 * The link between the site and the mascot (docs/work/2026-11-27-webui-rethink piece 4).
 * - Pages tell what the owner did with `host.event(kind, data)` (SDK) → `pageEvent()` → rules → `react()`.
 * - The mascot side reads `reaction()` and plays a pose for its `kind` (cheer · proud · comfort · nudge) with the
 *   optional text and action in a bubble; it never needs to know which page sent it, and the site never knows the
 *   sprites. `react()` is also the door for anything else that wants a reaction.
 * - `chatOpen` is the mini chat next to the mascot (a click on it); `present` says a mascot is on screen, so the
 *   bottom-right bubble steps aside (one door to the assistant).
 */
@Injectable({ providedIn: 'root' })
export class MascotService {
  readonly reaction = signal<Reaction | null>(null);
  readonly chatOpen = signal(false);
  readonly present = signal(false);
  /** Text put in the mini chat's box by a reaction's action («Talk about it»). */
  readonly draft = signal('');
  private toasts = inject(ToastService);
  private seq = 0;
  private last = 0;
  private timer: ReturnType<typeof setTimeout> | undefined;

  react(kind: ReactionKind, text?: string, action?: ReactionAction): void {
    const now = Date.now();
    if (now - this.last < QUIET_MS) return;
    this.last = now;
    if (!this.present()) {   // no mascot on screen: only an offer (comfort, nudge) becomes a notice; the page already said «done»
      if (text && action) this.toasts.show(text, kind === 'nudge' ? 'warning' : 'success', action ? { label: action.label, run: () => this.run(action) } : undefined);
      return;
    }
    this.reaction.set({ id: ++this.seq, kind, text, action, at: now });
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.reaction.set(null), action ? 9000 : 5000);
  }

  /** A reaction's button: the mini chat opens with its sentence ready to send. */
  run(action: ReactionAction): void {
    this.dismiss();
    if (action.prompt) this.draft.set(action.prompt);
    this.chatOpen.set(true);
  }

  dismiss(): void { clearTimeout(this.timer); this.reaction.set(null); }

  /** A plugin page's `host.event(kind, data)`: unknown kinds are ignored. */
  pageEvent(kind: string, data: Record<string, unknown> = {}, module = ''): void {
    const rule = RULES[String(kind || '')];
    const r = rule ? rule(data && typeof data === 'object' ? data : {}, module) : null;
    if (r) this.react(r.kind, r.text, r.action);
  }
}
