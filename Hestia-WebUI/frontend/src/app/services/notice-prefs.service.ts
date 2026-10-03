import { Injectable, signal } from '@angular/core';
import { ChatNotice } from '../models/chat.models';

/** How system notices (Oracle `notice` packets) are shown. Per browser (localStorage): pure rendering. */
export type NoticeMode = 'inline' | 'toast' | 'both' | 'important' | 'hidden';
export type NoticeStyle = 'compact' | 'rich';
export type NoticeGroup = 'memory' | 'actions' | 'subscriptions' | 'other';

export interface NoticePrefs { mode: NoticeMode; style: NoticeStyle; groups: Record<NoticeGroup, boolean>; }

const KEY = 'hestia_notice_prefs';
const DEFAULTS: NoticePrefs = { mode: 'inline', style: 'compact', groups: { memory: true, actions: true, subscriptions: true, other: true } };

export function noticeGroup(kind: string): NoticeGroup {
  return kind.startsWith('memory.') ? 'memory' : kind.startsWith('action.') ? 'actions'
    : kind.startsWith('subscription.') ? 'subscriptions' : 'other';
}

@Injectable({ providedIn: 'root' })
export class NoticePrefsService {
  readonly prefs = signal<NoticePrefs>(this.read());

  update(p: Partial<NoticePrefs>) {
    this.prefs.update(cur => ({ ...cur, ...p, groups: { ...cur.groups, ...(p.groups ?? {}) } }));
    try { localStorage.setItem(KEY, JSON.stringify(this.prefs())); } catch { /* private mode */ }
  }
  reset() { this.update({ ...DEFAULTS, groups: { ...DEFAULTS.groups } }); }

  /** Notice passes the group/importance filter (errors always pass unless hidden). */
  allows(n: ChatNotice, p = this.prefs()): boolean {
    if (p.mode === 'hidden') return false;
    if (!p.groups[noticeGroup(n.kind)] && n.level !== 'error') return false;
    if (p.mode === 'important') return n.level === 'warning' || n.level === 'error' || n.kind.startsWith('action.');
    return true;
  }
  inline(p = this.prefs()) { return p.mode === 'inline' || p.mode === 'both' || p.mode === 'important'; }
  toast(p = this.prefs()) { return p.mode === 'toast' || p.mode === 'both'; }

  private read(): NoticePrefs {
    try {
      const raw = JSON.parse(localStorage.getItem(KEY) || '{}');
      return { ...DEFAULTS, ...raw, groups: { ...DEFAULTS.groups, ...(raw.groups ?? {}) } };
    } catch { return { ...DEFAULTS, groups: { ...DEFAULTS.groups } }; }
  }
}
