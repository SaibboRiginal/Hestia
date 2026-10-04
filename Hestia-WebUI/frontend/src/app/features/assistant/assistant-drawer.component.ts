import { uid } from '../../core/uid';
import {
  AfterViewChecked, ChangeDetectionStrategy, Component, ElementRef, HostListener, computed, effect, inject,
  untracked, viewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ChatService } from '../../services/chat.service';
import { SignalRService } from '../../services/signalr.service';
import { SettingsService } from '../../services/settings.service';
import { NoticePrefsService } from '../../services/notice-prefs.service';
import { AssistantService } from '../../services/assistant.service';
import { ButtonComponent, IconComponent } from '../../ui';
import { ThinkingStepsComponent } from '../chat/thinking-steps.component';

const DEFAULT_SUGGESTIONS: Record<string, string[]> = {
  calendar: ['Ogni lunedì alle 9 controlla le nuove case', 'Sposta il job di stanotte a domani alle 3', 'Salta la prossima finestra Claude'],
  forge: ['Spiegami cosa ha cambiato questo task', 'Crea uno sviluppo: aggiungi un comando che…'],
  commands: ['Crea un comando che…', 'Cosa fa questo comando?'],
};

/**
 * "Crea con Hestia": right-side assistant drawer (full screen on phones), opened from any page
 * through AssistantService.open(ctx). Own ChatService instance on channel "assistant" and its own
 * Oracle session; the context packet travels with every message as client instructions.
 * Lazy (@defer in the shell); shortcut Ctrl/⌘+J lives in the shell.
 */
@Component({
  selector: 'hx-assistant',
  imports: [FormsModule, ButtonComponent, IconComponent, ThinkingStepsComponent],
  providers: [{ provide: ChatService, useFactory: () => { const c = new ChatService(); c.channel = 'assistant'; return c; } }],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (assistant.isOpen()) {
      <div class="scrim hx-fade-in" (click)="assistant.close()"></div>
      <aside class="drawer" role="dialog" aria-label="Crea con Hestia">
        <header>
          <hx-icon name="sparkle" [size]="17" class="spark" />
          <h2>Crea con Hestia</h2>
          <div class="hx-grow"></div>
          <button hx-btn variant="ghost" size="sm" icon="plus" iconOnly aria-label="Nuova conversazione" title="Nuova conversazione"
                  (click)="reset()" [disabled]="chat.isStreaming()"></button>
          <button hx-btn variant="ghost" size="sm" icon="x" iconOnly aria-label="Chiudi" title="Chiudi (Esc)" (click)="assistant.close()"></button>
        </header>
        @if (ctx(); as c) {
          @if (c.label) {
            <div class="ctx" [title]="packet()">
              <hx-icon [name]="pageIcon()" [size]="13" />
              <span>{{ c.label }}</span>
              <button class="ctx-x" (click)="assistant.context.set(null)" aria-label="Togli contesto" title="Togli contesto"><hx-icon name="x" [size]="12" /></button>
            </div>
          }
        }

        <div class="scroll" #scroller>
          @if (!chat.messages().length) {
            <div class="empty">
              <p>Dimmi cosa creare o cambiare: lo faccio io con gli strumenti di Hestia. Se manca uno strumento, ti propongo uno sviluppo.</p>
              <div class="chips">
                @for (s of suggestions(); track s) { <button (click)="use(s)">{{ s }}</button> }
              </div>
            </div>
          }
          @for (m of chat.messages(); track m.id) {
            @if (m.role === 'user') {
              <div class="msg user"><div class="bubble">{{ m.content }}</div></div>
            } @else {
              <div class="msg asst">
                @if (m.thinkingSteps?.length && thinkingMode() !== 'hidden') {
                  <chat-thinking [steps]="m.thinkingSteps!" [live]="!!m.isStreaming && !m.content" [expandedByDefault]="false" />
                }
                @if (m.content) { <div class="hx-prose" [innerHTML]="m.content"></div> }
                @else if (m.isStreaming) { <div class="typing"><span></span><span></span><span></span></div> }
                @if (m.notices?.length) {
                  <div class="hx-notices">
                    @for (n of m.notices; track n.id) {
                      <div class="hx-notice hx-fade-in" [attr.data-level]="n.level" [title]="n.kind">
                        <hx-icon [name]="n.icon" [size]="14" />
                        <span class="nt">{{ n.title }}</span>
                        @if (n.detail) { <span class="nd">{{ n.detail }}</span> }
                      </div>
                    }
                  </div>
                }
              </div>
            }
          }
          <div #bottom></div>
        </div>

        <div class="foot">
          @if (chat.pendingQuestion(); as q) {
            <div class="question hx-fade-in">
              <div class="qh"><hx-icon name="info" [size]="14" /> {{ q.header }}</div>
              @if (q.prompt) { <div class="qp">{{ q.prompt }}</div> }
              @if (q.options.length) {
                <div class="qo">@for (o of q.options; track o.value) { <button hx-btn size="sm" (click)="answer(q.questionId, o.value)">{{ o.label }}</button> }</div>
              }
              @if (q.kind === 'free_text' || !q.options.length) {
                <div class="qo">
                  <input class="hx-input" [(ngModel)]="questionText" (keydown.enter)="answer(q.questionId, questionText)" placeholder="Rispondi…" />
                  <button hx-btn variant="primary" size="sm" (click)="answer(q.questionId, questionText)" [disabled]="!questionText.trim()">Invia</button>
                </div>
              }
            </div>
          }
          <div class="composer" [class.disabled]="signalR.connectionState() !== 'connected'">
            <textarea #ta [(ngModel)]="text" (keydown)="onKey($event)" (input)="grow()" rows="2"
                      [placeholder]="placeholder()"></textarea>
            <div class="tools">
              <span class="hint">Invio per mandare</span>
              <div class="hx-grow"></div>
              @if (chat.isStreaming()) {
                <button hx-btn variant="secondary" size="sm" icon="stop" iconOnly aria-label="Stop" (click)="chat.cancelStream()"></button>
              } @else {
                <button hx-btn variant="primary" size="sm" icon="send" iconOnly aria-label="Invia" (click)="send()" [disabled]="!text.trim()"></button>
              }
            </div>
          </div>
        </div>
      </aside>
    }
  `,
  styles: [`
    .scrim { position: fixed; inset: 0; background: var(--overlay); z-index: 880; opacity: .35; }
    .drawer { position: fixed; top: 0; right: 0; bottom: 0; width: min(440px, 100vw); z-index: 890; background: var(--surface);
              border-left: 1px solid var(--border); box-shadow: var(--shadow-3); display: flex; flex-direction: column;
              animation: hx-drawer-in var(--dur) var(--ease); }
    @keyframes hx-drawer-in { from { transform: translateX(24px); opacity: 0; } to { transform: none; opacity: 1; } }
    header { display: flex; align-items: center; gap: 8px; padding: 12px 10px 8px 16px; }
    header h2 { font-family: var(--font-serif); font-weight: 500; font-size: 18px; }
    .spark { color: var(--accent); }
    .ctx { display: inline-flex; align-items: center; gap: 6px; margin: 0 16px 6px; padding: 3px 4px 3px 9px; align-self: flex-start;
           max-width: calc(100% - 32px); border: 1px solid var(--border-strong); border-radius: var(--radius-full);
           font-size: 12.5px; color: var(--text-2); background: var(--surface-2); }
    .ctx span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .ctx-x { width: 18px; height: 18px; border-radius: 50%; display: grid; place-items: center; color: var(--text-3); flex-shrink: 0; }
    .ctx-x:hover { background: var(--surface-3); color: var(--text); }
    .scroll { flex: 1; overflow-y: auto; padding: 8px 16px 12px; display: flex; flex-direction: column; gap: 16px; }
    .empty p { color: var(--text-3); font-size: 13.5px; line-height: 1.5; margin: 6px 0 12px; }
    .chips { display: flex; flex-direction: column; gap: 6px; }
    .chips button { text-align: left; border: 1px solid var(--border); border-radius: var(--radius-md); padding: 8px 11px;
                    font-size: 13px; color: var(--text-2); background: var(--surface); }
    .chips button:hover { background: var(--surface-2); color: var(--text); border-color: var(--border-strong); }
    .msg.user { display: flex; justify-content: flex-end; }
    .bubble { background: var(--user-bubble); color: var(--user-bubble-text); padding: 8px 12px; border-radius: var(--radius-lg);
              max-width: 88%; white-space: pre-wrap; word-wrap: break-word; font-size: 14px; }
    .msg.asst .hx-prose { font-size: 14px; }
    .typing { display: inline-flex; gap: 4px; padding: 6px 0; }
    .typing span { width: 6px; height: 6px; border-radius: 50%; background: var(--text-3); animation: hx-pulse 1.2s infinite; }
    .typing span:nth-child(2) { animation-delay: .2s; } .typing span:nth-child(3) { animation-delay: .4s; }
    .foot { padding: 0 12px 12px; }
    .composer { border: 1px solid var(--border-strong); border-radius: var(--radius-lg); padding: 9px 9px 6px 12px; background: var(--surface); }
    .composer:focus-within { border-color: var(--accent); }
    .composer.disabled { opacity: .7; }
    textarea { width: 100%; border: 0; outline: 0; resize: none; background: transparent; font-size: 14.5px; line-height: 1.45; max-height: 180px; color: var(--text); }
    textarea::placeholder { color: var(--text-3); }
    .tools { display: flex; align-items: center; gap: 4px; }
    .hint { font-size: 11px; color: var(--text-3); }
    .question { border: 1px solid var(--accent); border-radius: var(--radius-md); padding: 10px 12px; margin-bottom: 8px; }
    .qh { display: flex; align-items: center; gap: 6px; font-weight: 600; font-size: 13.5px; }
    .qp { color: var(--text-2); font-size: 13px; margin: 4px 0 6px; }
    .qo { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 6px; }
    .qo .hx-input { flex: 1; min-width: 140px; }
    @media (max-width: 720px) {
      .drawer { width: 100vw; border-left: 0; }
      .scrim { display: none; }
    }
  `],
})
export class AssistantDrawerComponent implements AfterViewChecked {
  chat = inject(ChatService);
  signalR = inject(SignalRService);
  assistant = inject(AssistantService);
  private settings = inject(SettingsService);
  notices = inject(NoticePrefsService);
  private bottom = viewChild<ElementRef<HTMLElement>>('bottom');
  private ta = viewChild<ElementRef<HTMLTextAreaElement>>('ta');

  text = '';
  questionText = '';
  /** Own Oracle session: drawer conversations don't pollute the Chat page context. */
  private sessionId = uid();
  private lastCount = 0;
  private lastLen = 0;

  readonly ctx = this.assistant.context;
  readonly packet = computed(() => AssistantService.serialize(this.ctx()));
  readonly thinkingMode = computed(() => this.settings.settings().thinkingDisplay || 'compact');
  readonly suggestions = computed(() => {
    const c = this.ctx();
    return c?.suggestions?.length ? c.suggestions : DEFAULT_SUGGESTIONS[c?.page ?? ''] ?? [
      'Pianifica per Hestia un controllo ogni sera alle 22', 'Cosa ha in programma Hestia stanotte?'];
  });
  readonly placeholder = computed(() => this.signalR.connectionState() !== 'connected' ? 'Connessione in corso…'
    : this.ctx()?.page === 'calendar' ? 'Es. "ogni venerdì alle 18 controlla le email di Scout"' : 'Cosa vuoi creare o cambiare?');
  readonly pageIcon = computed(() => ({ calendar: 'calendar', forge: 'code', commands: 'terminal', documents: 'file' } as Record<string, string>)[this.ctx()?.page ?? ''] ?? 'info');

  constructor() {
    // Each open(): apply the prefill and focus the composer.
    effect(() => {
      this.assistant.openSeq();
      const c = untracked(() => this.ctx());
      untracked(() => {
        if (c?.prompt) this.text = c.prompt;
        setTimeout(() => { this.ta()?.nativeElement.focus(); this.grow(); });
      });
    });
  }

  ngAfterViewChecked() {
    const msgs = this.chat.messages();
    const len = msgs.length ? msgs[msgs.length - 1].content.length : 0;
    if (msgs.length !== this.lastCount || len !== this.lastLen) {
      this.lastCount = msgs.length;
      this.lastLen = len;
      this.bottom()?.nativeElement.scrollIntoView({ block: 'end' });
    }
  }

  @HostListener('document:keydown.escape')
  onEsc() {
    if (this.assistant.isOpen() && !document.querySelector('hx-modal .backdrop')) this.assistant.close();
  }

  use(s: string) { this.text = s; this.send(); }

  send() {
    const t = this.text.trim();
    if (!t || this.chat.isStreaming()) return;
    void this.chat.sendMessage(t, this.sessionId, 'auto', 'generic', this.packet() || 'page=generico');
    this.text = '';
    queueMicrotask(() => this.grow());
  }

  reset() {
    this.chat.clearMessages();
    this.sessionId = uid();
  }

  answer(id: string, v: string) { this.chat.answerQuestion(id, v); this.questionText = ''; }

  onKey(e: KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); this.send(); }
  }

  grow() {
    const el = this.ta()?.nativeElement;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 180) + 'px';
  }

}
