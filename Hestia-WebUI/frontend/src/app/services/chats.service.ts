import { Injectable, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { PluginsService } from '../features/plugins/plugins.service';
import { ChatService } from './chat.service';
import { SessionService } from './session.service';
import { DialogService, ToastService } from '../ui';
import { tr } from '../core/i18n';

export interface ChatTag { name: string; color: string; }
export interface ChatSummary {
  session_id: string; title: string; first_at: string | null; last_at: string | null; messages: number;
  tags: ChatTag[]; pinned: boolean;
  /** «Don't use for training»: no turn of it goes in the training dataset. */
  training_off?: boolean;
}
export interface ChatQuery { q?: string; tag?: string; since?: string; until?: string; limit?: number; offset?: number; }

export const TAG_COLORS = ['gray', 'red', 'orange', 'yellow', 'green', 'teal', 'blue', 'purple', 'pink'];
/** Tag colour → CSS colour (fixed hues that read on light and dark). */
export const TAG_CSS: Record<string, string> = {
  gray: '#8a8a8a', red: '#dc2626', orange: '#ea580c', yellow: '#ca8a04', green: '#16a34a', teal: '#0d9488',
  blue: '#2563eb', purple: '#7c3aed', pink: '#db2777',
};

/**
 * Conversations of the owner (Cindy 26 + new sidebar, dossier 2026-10-24-whole-cindy-brainstorm W7): list with
 * search, tag and date filters, coloured tags, pinned; open one again in the chat (its messages come back and the
 * answers continue in it). Through the Oracle plugin door `/api/ui/chats*` (Archive keeps them).
 */
@Injectable({ providedIn: 'root' })
export class ChatsService {
  private plugins = inject(PluginsService);
  private chat = inject(ChatService);
  private session = inject(SessionService);
  private router = inject(Router);
  private dialogs = inject(DialogService);
  private toasts = inject(ToastService);

  /** Sidebar: pinned conversations, or the 3 most recent. */
  readonly recent = signal<ChatSummary[]>([]);
  readonly tags = signal<ChatTag[]>([]);
  readonly historyOpen = signal(false);

  async list(query: ChatQuery = {}): Promise<{ ok: boolean; items: ChatSummary[]; total: number }> {
    const r = await this.plugins.call<{ items?: ChatSummary[]; total?: number }>('oracle', 'GET', '/api/ui/chats', { query: { ...query } });
    return { ok: r.ok, items: r.data?.items ?? [], total: r.data?.total ?? 0 };
  }

  async refreshRecent(): Promise<void> {
    if (!this.plugins.modules().has('oracle')) return;
    const r = await this.list({ limit: 20 });
    if (!r.ok) return;
    // The Chat panel lists them (docs/work/2026-11-27-webui-rethink): pinned first, then the latest.
    this.recent.set([...r.items.filter(i => i.pinned), ...r.items.filter(i => !i.pinned)].slice(0, 12));
  }

  async loadTags(): Promise<void> {
    const r = await this.plugins.call<{ items?: ChatTag[] }>('oracle', 'GET', '/api/ui/chats/tags');
    if (r.ok) this.tags.set(r.data?.items ?? []);
  }

  async setMeta(sessionId: string, body: { title?: string; tags?: ChatTag[]; add_tags?: ChatTag[]; remove_tags?: string[]; pinned?: boolean; training_off?: boolean }) {
    const r = await this.plugins.call<ChatSummary & { before: Partial<ChatSummary> }>('oracle', 'PUT', `/api/ui/chats/${encodeURIComponent(sessionId)}`, { body });
    if (r.ok) { void this.refreshRecent(); void this.loadTags(); this.changed.update(n => n + 1); }
    return r;
  }

  /** Bumped when a conversation is deleted or renamed, so every list of them reloads. */
  readonly changed = signal(0);

  /** Deletes a conversation for good. The one on screen is closed: the chat starts a new one. */
  async remove(sessionId: string): Promise<boolean> {
    const r = await this.plugins.call('oracle', 'DELETE', `/api/ui/chats/${encodeURIComponent(sessionId)}`);
    if (!r.ok) return false;
    if (sessionId === this.session.sessionId()) {
      try { await this.session.clear(); } catch { /* the next message opens a new one */ }
      this.chat.clearMessages();
    }
    this.recent.update(x => x.filter(c => c.session_id !== sessionId));
    this.changed.update(n => n + 1);
    void this.refreshRecent();
    return true;
  }

  /** «Delete» from any list of conversations: asks first, then tells how it went. */
  async confirmRemove(c: ChatSummary): Promise<boolean> {
    const ok = await this.dialogs.confirm(tr('Delete the conversation?'),
      tr("«{0}» is deleted forever with all its messages. What the assistant learned about you stays.", c.title), tr('Delete'), true);
    if (!ok) return false;
    if (!(await this.remove(c.session_id))) { this.toasts.error(tr('Not deleted: try again shortly')); return false; }
    this.toasts.success(tr('Conversation deleted'));
    return true;
  }

  /** Opens a conversation: its messages in the chat, the next message continues it. `stay` keeps the page (the
   *  mascot's mini chat shows it where the owner is). */
  async open(sessionId: string, stay = false): Promise<boolean> {
    const r = await this.plugins.call<{ items?: Array<{ role: string; content: string; at?: string; model?: string }> }>(
      'oracle', 'GET', `/api/ui/chats/${encodeURIComponent(sessionId)}/messages`, { query: { limit: 200 } });
    if (!r.ok) return false;
    this.session.sessionId.set(sessionId);
    this.chat.showHistory(r.data?.items ?? [], sessionId);
    if (!stay && !this.router.url.startsWith('/chat')) void this.router.navigateByUrl('/chat');
    return true;
  }
}
