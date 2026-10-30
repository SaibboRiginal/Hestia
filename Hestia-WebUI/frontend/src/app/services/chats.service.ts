import { Injectable, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { PluginsService } from '../features/plugins/plugins.service';
import { ChatService } from './chat.service';
import { SessionService } from './session.service';

export interface ChatTag { name: string; color: string; }
export interface ChatSummary {
  session_id: string; title: string; first_at: string | null; last_at: string | null; messages: number;
  tags: ChatTag[]; pinned: boolean;
  /** «Non usare per l'allenamento»: no turn of it goes in the training dataset. */
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
 * Conversations of the owner (Cindy 26 + new sidebar, dossier 2026-10-24-tutto-brainstorm-cindy W7): list with
 * search, tag and date filters, coloured tags, pinned; open one again in the chat (its messages come back and the
 * answers continue in it). Through the Oracle plugin door `/api/ui/chats*` (Archive keeps them).
 */
@Injectable({ providedIn: 'root' })
export class ChatsService {
  private plugins = inject(PluginsService);
  private chat = inject(ChatService);
  private session = inject(SessionService);
  private router = inject(Router);

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
    const r = await this.list({ limit: 12 });
    if (!r.ok) return;
    const pinned = r.items.filter(i => i.pinned);
    this.recent.set(pinned.length ? pinned.slice(0, 8) : r.items.slice(0, 3));
  }

  async loadTags(): Promise<void> {
    const r = await this.plugins.call<{ items?: ChatTag[] }>('oracle', 'GET', '/api/ui/chats/tags');
    if (r.ok) this.tags.set(r.data?.items ?? []);
  }

  async setMeta(sessionId: string, body: { title?: string; tags?: ChatTag[]; add_tags?: ChatTag[]; remove_tags?: string[]; pinned?: boolean; training_off?: boolean }) {
    const r = await this.plugins.call<ChatSummary & { before: Partial<ChatSummary> }>('oracle', 'PUT', `/api/ui/chats/${encodeURIComponent(sessionId)}`, { body });
    if (r.ok) { void this.refreshRecent(); void this.loadTags(); }
    return r;
  }

  /** Opens a conversation: its messages in the chat, the next message continues it. */
  async open(sessionId: string): Promise<boolean> {
    const r = await this.plugins.call<{ items?: Array<{ role: string; content: string; at?: string }> }>(
      'oracle', 'GET', `/api/ui/chats/${encodeURIComponent(sessionId)}/messages`, { query: { limit: 200 } });
    if (!r.ok) return false;
    this.session.sessionId.set(sessionId);
    this.chat.showHistory(r.data?.items ?? [], sessionId);
    if (!this.router.url.startsWith('/chat')) void this.router.navigateByUrl('/chat');
    return true;
  }
}
