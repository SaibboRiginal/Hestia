import { AfterViewChecked, ChangeDetectionStrategy, Component, ElementRef, HostListener, computed, effect, inject, untracked, viewChild } from '@angular/core';
import { Router } from '@angular/router';
import { IconComponent, ToastService } from '../ui';
import { assistantName, tr, TrPipe } from '../core/i18n';
import { ChatService } from '../services/chat.service';
import { ChatsService } from '../services/chats.service';
import { LiveVoiceService } from '../services/live-voice.service';
import { MascotService } from '../services/mascot.service';
import { SessionService } from '../services/session.service';

/**
 * The mini chat next to the mascot (docs/work/2026-11-27-webui-rethink piece 4): a click on the mascot opens the
 * conversation in course, or the last one, right where the owner is; «Open» moves to the Chat page, «Talk» starts
 * the voice conversation. Same conversation as the Chat page: what is written here continues there.
 */
@Component({
  selector: 'hx-mascot-chat',
  imports: [TrPipe, IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (mascot.chatOpen()) {
      <section class="mc hx-fade-in" role="dialog" [attr.aria-label]="name()">
        <header>
          <b>{{ name() }}</b>
          <span class="grow"></span>
          <button class="ib" (click)="talk()" [title]="(live.on ? 'Stop Talk' : 'Talk') | tr" [attr.aria-label]="(live.on ? 'Stop Talk' : 'Talk') | tr"><hx-icon name="waveform" [size]="16" /></button>
          <button class="ib" (click)="openFull()" [title]="'Open in chat' | tr" [attr.aria-label]="'Open in chat' | tr"><hx-icon name="external" [size]="16" /></button>
          <button class="ib" (click)="mascot.chatOpen.set(false)" [title]="'Close' | tr" [attr.aria-label]="'Close' | tr"><hx-icon name="x" [size]="16" /></button>
        </header>
        <div class="msgs" #scroller>
          @for (m of shown(); track m.id) {
            @if (m.role === 'user') { <div class="u">{{ m.content }}</div> }
            @else if (m.role === 'assistant') {
              @if (m.content) { <div class="a" [innerHTML]="m.content"></div> }
              @else { <div class="a muted"><span class="dots"><i></i><i></i><i></i></span></div> }
            }
          } @empty { <div class="empty">{{ "Ask me anything, or tell me what to do." | tr }}</div> }
        </div>
        <div class="in">
          <textarea #ta rows="1" [placeholder]="'Write to {assistant}…' | tr" [value]="mascot.draft()" (input)="mascot.draft.set($any($event.target).value)"
                    (keydown)="onKey($event)" [attr.aria-label]="'Message' | tr"></textarea>
          <button class="send" (click)="send()" [disabled]="!mascot.draft().trim() || chat.isStreaming()" [attr.aria-label]="'Send' | tr"><hx-icon name="send" [size]="16" /></button>
        </div>
      </section>
    }`,
  styles: [`
    .mc { position: fixed; right: 92px; bottom: 18px; z-index: 790; width: min(380px, calc(100vw - 32px)); height: min(520px, calc(100vh - 120px));
          display: flex; flex-direction: column; background: linear-gradient(var(--surface), var(--surface)), var(--bg);
          border: 1px solid var(--border); border-radius: var(--radius-xl); box-shadow: var(--shadow-3); overflow: hidden; }
    :host-context([data-mascot-side=left]) .mc { right: auto; left: 92px; }
    header { display: flex; align-items: center; gap: 4px; padding: 10px 10px 10px 16px; border-bottom: 1px solid var(--border); }
    header b { font-size: 14.5px; } .grow { flex: 1; }
    .ib { width: 32px; height: 32px; display: grid; place-items: center; border-radius: var(--radius-md); color: var(--text-3); }
    .ib:hover { background: var(--surface-2); color: var(--text); }
    .msgs { flex: 1; overflow: auto; padding: 12px 14px; display: flex; flex-direction: column; gap: 8px; }
    .u { align-self: flex-end; max-width: 85%; padding: 7px 11px; border-radius: 14px 14px 4px 14px; background: var(--accent-soft); color: var(--text);
         font-size: 14px; white-space: pre-wrap; overflow-wrap: anywhere; }
    .a { max-width: 95%; font-size: 14px; line-height: 1.5; color: var(--text); overflow-wrap: anywhere; }
    .a :is(p, ul, ol) { margin: 0 0 6px; } .a.muted { color: var(--text-3); }
    .empty { margin: auto; text-align: center; color: var(--text-3); font-size: 13.5px; max-width: 30ch; }
    .in { display: flex; align-items: flex-end; gap: 8px; padding: 10px; border-top: 1px solid var(--border); }
    textarea { flex: 1; resize: none; max-height: 120px; border: 1px solid var(--border); border-radius: var(--radius-md); padding: 8px 10px;
               font: inherit; font-size: 14px; background: var(--surface); color: var(--text); }
    textarea:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px var(--focus-ring); }
    .send { width: 36px; height: 36px; display: grid; place-items: center; border-radius: 50%; background: var(--accent); color: var(--accent-contrast); }
    .send:disabled { opacity: .45; }
    .dots { display: inline-flex; gap: 3px; } .dots i { width: 5px; height: 5px; border-radius: 50%; background: currentColor; opacity: .4; animation: hx-dot 1s infinite; }
    .dots i:nth-child(2) { animation-delay: .15s; } .dots i:nth-child(3) { animation-delay: .3s; }
    @keyframes hx-dot { 50% { opacity: 1; } }
    @media (max-width: 860px) { .mc, :host-context([data-mascot-side=left]) .mc { left: 16px; right: 16px; width: auto; bottom: calc(76px + env(safe-area-inset-bottom, 0px)); height: min(70vh, 520px); } }
    @media (prefers-reduced-motion: reduce) { .dots i { animation: none; } }
  `],
})
export class MascotChatComponent implements AfterViewChecked {
  readonly mascot = inject(MascotService);
  readonly chat = inject(ChatService);
  readonly live = inject(LiveVoiceService);
  private chats = inject(ChatsService);
  private session = inject(SessionService);
  private router = inject(Router);
  private toasts = inject(ToastService);
  private scroller = viewChild<ElementRef<HTMLElement>>('scroller');
  private ta = viewChild<ElementRef<HTMLTextAreaElement>>('ta');
  private lastLen = -1;

  readonly name = computed(() => assistantName() || tr('Assistant'));
  /** The latest part of the conversation: enough to pick up the thread, the rest is in «Open». */
  readonly shown = computed(() => this.chat.messages().filter(m => m.role !== 'system').slice(-14));

  constructor() {
    effect(() => {
      if (!this.mascot.chatOpen()) return;
      untracked(() => {
        void this.loadLast();
        setTimeout(() => this.ta()?.nativeElement.focus());
      });
    });
  }

  ngAfterViewChecked() {
    const msgs = this.shown();
    const len = msgs.reduce((n, m) => n + m.content.length, msgs.length);
    if (len !== this.lastLen) { this.lastLen = len; const el = this.scroller()?.nativeElement; if (el) el.scrollTop = el.scrollHeight; }
  }

  /** Nothing on screen yet (page just opened): the last conversation comes back here, without changing page. */
  private async loadLast() {
    if (this.chat.messages().length || this.chat.isStreaming()) return;
    await this.chats.refreshRecent();
    const last = this.chats.recent()[0];
    if (last && !this.chat.messages().length) await this.chats.open(last.session_id, true);
  }

  send() {
    const t = this.mascot.draft().trim();
    if (!t || this.chat.isStreaming()) return;
    void this.chat.sendMessage(t, this.session.sessionId() || '', 'auto', 'generic');
    this.mascot.draft.set('');
  }

  onKey(e: KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); this.send(); }
  }

  openFull() { this.mascot.chatOpen.set(false); void this.router.navigateByUrl('/chat'); }

  talk() {
    if (this.live.on) { this.live.stop(); return; }
    void this.live.start().then(() => { if (this.live.error()) this.toasts.error(this.live.error()); });
  }

  @HostListener('document:keydown.escape')
  onEsc() { if (this.mascot.chatOpen()) this.mascot.chatOpen.set(false); }
}
