import {
  AfterViewChecked, ChangeDetectionStrategy, Component, ElementRef, computed, inject, signal, viewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ChatService } from '../../services/chat.service';
import { SessionService } from '../../services/session.service';
import { SettingsService } from '../../services/settings.service';
import { FeedbackService } from '../../services/feedback.service';
import { SignalRService } from '../../services/signalr.service';
import { ChatMessage } from '../../models/chat.models';
import { ButtonComponent, DialogService, IconComponent, MenuComponent, MenuItem, ToastService } from '../../ui';
import { ThinkingStepsComponent } from './thinking-steps.component';
import { NoticePrefsService } from '../../services/notice-prefs.service';

/** Chat with Hestia (Oracle via SignalR): streaming, reasoning, questions, attachments, feedback. */
@Component({
  selector: 'app-chat-page',
  imports: [FormsModule, ButtonComponent, IconComponent, MenuComponent, ThinkingStepsComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <header class="top">
      <span class="ttl">{{ chat.messages().length ? 'Conversazione' : '' }}</span>
      <div class="hx-grow"></div>
      <select class="hx-select mode" [(ngModel)]="mode" title="Modalità">
        <option value="auto">Auto</option><option value="quick">Veloce</option><option value="thinking">Ragionamento</option>
      </select>
      <hx-menu [items]="menu" (select)="onMenu($event)">
        <button hx-btn variant="ghost" size="sm" icon="more" iconOnly trigger aria-label="Altro"></button>
      </hx-menu>
    </header>

    <div class="scroll" #scroller>
      <div class="thread">
        @if (!chat.messages().length) {
          <div class="welcome hx-fade-in">
            <div class="logo">◈</div>
            <h1>{{ greeting() }}</h1>
            <p>Chiedi qualcosa, pianifica nell'agenda, fai sviluppare Hestia.</p>
            <div class="chips">
              @for (s of suggestions; track s) { <button (click)="use(s)">{{ s }}</button> }
            </div>
          </div>
        }
        @for (m of chat.messages(); track m.id) {
          @if (m.role === 'user') {
            <div class="msg user hx-fade-in"><div class="bubble">{{ m.content }}</div></div>
          } @else {
            <div class="msg asst hx-fade-in">
              @if (m.thinkingSteps?.length && thinkingMode() !== 'hidden') {
                <chat-thinking [steps]="m.thinkingSteps!" [live]="!!m.isStreaming && !m.content"
                               [expandedByDefault]="thinkingMode() === 'detailed'" />
              }
              @if (m.content) { <div class="hx-prose" [innerHTML]="m.content"></div> }
              @else if (m.isStreaming) { <div class="typing"><span></span><span></span><span></span></div> }
              @if (m.isStreaming && m.content) { <span class="caret"></span> }
              @if (m.notices?.length && notices.inline()) {
                <div class="hx-notices" [class.rich]="notices.prefs().style === 'rich'">
                  @for (n of m.notices; track n.id) {
                    <div class="hx-notice hx-fade-in" [attr.data-level]="n.level" [title]="n.kind">
                      <hx-icon [name]="n.icon" [size]="14" />
                      <span class="nt">{{ n.title }}</span>
                      @if (n.detail) { <span class="nd">{{ n.detail }}</span> }
                    </div>
                  }
                </div>
              }
              @if (!m.isStreaming && m.content) {
                <div class="foot">
                  <button class="fb" [class.on]="rated()[m.id] === 'good'" (click)="feedback('good', m)" title="Utile"><hx-icon name="thumb-up" [size]="15" /></button>
                  <button class="fb" [class.on]="rated()[m.id] === 'bad'" (click)="feedback('bad', m)" title="Non utile"><hx-icon name="thumb-down" [size]="15" /></button>
                  <button class="fb" (click)="copy(m)" title="Copia"><hx-icon name="copy" [size]="15" /></button>
                  @if ($last) { <button class="fb" (click)="chat.retry()" [disabled]="chat.isStreaming()" title="Rigenera"><hx-icon name="refresh" [size]="15" /></button> }
                </div>
              }
            </div>
          }
        }
        <div #bottom></div>
      </div>
    </div>

    <div class="composer-wrap">
      @if (chat.pendingQuestion(); as q) {
        <div class="question hx-fade-in">
          <div class="qh"><hx-icon name="info" [size]="15" /> {{ q.header }}</div>
          @if (q.prompt) { <div class="qp">{{ q.prompt }}</div> }
          @if (q.options.length) {
            <div class="qo">@for (o of q.options; track o.value) { <button hx-btn size="sm" (click)="answer(q.questionId, o.value)">{{ o.label }}</button> }</div>
          }
          @if (q.kind === 'free_text' || !q.options.length) {
            <div class="qf">
              <input class="hx-input" [(ngModel)]="questionText" (keydown.enter)="answer(q.questionId, questionText)" placeholder="Rispondi…" />
              <button hx-btn variant="primary" size="sm" (click)="answer(q.questionId, questionText)" [disabled]="!questionText.trim()">Invia</button>
            </div>
          }
          @if (!q.required) { <button class="skipq" (click)="answer(q.questionId, '')">Salta</button> }
        </div>
      }
      <div class="composer" [class.disabled]="signalR.connectionState() !== 'connected'">
        <textarea #ta [(ngModel)]="text" (keydown)="onKey($event)" (input)="grow()" rows="1"
                  [placeholder]="signalR.connectionState() === 'connected' ? 'Scrivi a Hestia…' : 'Connessione in corso…'"></textarea>
        <div class="tools">
          <input #file type="file" hidden (change)="onFile($event)" />
          <button hx-btn variant="ghost" size="sm" icon="paperclip" iconOnly aria-label="Allega" (click)="file.click()" [disabled]="chat.isStreaming()"></button>
          <div class="hx-grow"></div>
          @if (chat.isStreaming()) {
            <button hx-btn variant="secondary" size="sm" icon="stop" iconOnly aria-label="Stop" (click)="chat.cancelStream()"></button>
          } @else {
            <button hx-btn variant="primary" size="sm" icon="send" iconOnly aria-label="Invia" (click)="send()" [disabled]="!text.trim()"></button>
          }
        </div>
      </div>
      <p class="disc">Invio per mandare · Shift+Invio per andare a capo</p>
    </div>
  `,
  styles: [`
    :host { display: flex; flex-direction: column; flex: 1; min-height: 0; }
    .top { display: flex; align-items: center; gap: 8px; padding: 10px 16px 8px 56px; min-height: 52px; }
    .ttl { font-size: 14px; color: var(--text-2); }
    .mode { width: auto; height: 30px; padding-top: 4px; padding-bottom: 4px; font-size: 13px; }
    .scroll { flex: 1; overflow-y: auto; }
    .thread { max-width: var(--chat-width); margin: 0 auto; padding: 8px 20px 24px; display: flex; flex-direction: column; gap: 22px; }
    .welcome { text-align: center; padding: 12vh 0 0; display: flex; flex-direction: column; align-items: center; gap: 10px; }
    .welcome .logo { font-size: 34px; color: var(--accent); }
    .welcome h1 { font-family: var(--font-serif); font-weight: 400; font-size: 32px; }
    .welcome p { color: var(--text-3); }
    .chips { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; margin-top: 14px; max-width: 600px; }
    .chips button { border: 1px solid var(--border-strong); border-radius: var(--radius-full); padding: 7px 14px; font-size: 13.5px; color: var(--text-2); background: var(--surface); }
    .chips button:hover { background: var(--surface-2); color: var(--text); }
    .msg.user { display: flex; justify-content: flex-end; }
    .bubble { background: var(--user-bubble); color: var(--user-bubble-text); padding: 10px 15px; border-radius: var(--radius-xl);
              max-width: 80%; white-space: pre-wrap; word-wrap: break-word; font-size: 15px; }
    .msg.asst { position: relative; }
    .caret { display: inline-block; width: 8px; height: 17px; background: var(--accent); vertical-align: text-bottom; margin-left: 2px; animation: hx-pulse 1s infinite; border-radius: 2px; }
    .typing { display: inline-flex; gap: 4px; padding: 6px 0; }
    .typing span { width: 7px; height: 7px; border-radius: 50%; background: var(--text-3); animation: hx-pulse 1.2s infinite; }
    .typing span:nth-child(2) { animation-delay: .2s; } .typing span:nth-child(3) { animation-delay: .4s; }
    .foot { display: flex; gap: 2px; margin-top: 8px; opacity: 0; transition: opacity var(--dur); }
    .msg.asst:hover .foot, .msg.asst:last-child .foot { opacity: 1; }
    .fb { width: 28px; height: 28px; border-radius: var(--radius-sm); display: grid; place-items: center; color: var(--text-3); }
    .fb:hover:not(:disabled) { background: var(--surface-2); color: var(--text); }
    .fb.on { color: var(--accent); }
    .composer-wrap { padding: 0 20px 10px; max-width: calc(var(--chat-width) + 40px); width: 100%; margin: 0 auto; }
    .composer { background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius-xl); box-shadow: var(--shadow-2);
                padding: 12px 12px 8px 16px; transition: border-color var(--dur-fast); }
    .composer:focus-within { border-color: var(--accent); }
    .composer.disabled { opacity: .7; }
    textarea { width: 100%; border: 0; outline: 0; resize: none; background: transparent; font-size: 15.5px; line-height: 1.5; max-height: 240px; color: var(--text); }
    textarea::placeholder { color: var(--text-3); }
    .tools { display: flex; align-items: center; gap: 4px; margin-top: 4px; }
    .disc { text-align: center; font-size: 11.5px; color: var(--text-3); margin-top: 6px; }
    .question { background: var(--surface); border: 1px solid var(--accent); border-radius: var(--radius-lg); padding: 12px 14px; margin-bottom: 10px; box-shadow: var(--shadow-1); }
    .qh { display: flex; align-items: center; gap: 6px; font-weight: 600; font-size: 14px; }
    .qp { color: var(--text-2); font-size: 13.5px; margin: 4px 0 8px; }
    .qo, .qf { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 6px; }
    .qf .hx-input { flex: 1; min-width: 160px; }
    .skipq { font-size: 12px; color: var(--text-3); margin-top: 6px; }
    @media (max-width: 720px) { .thread { padding: 4px 12px 18px; } .composer-wrap { padding: 0 10px 8px; } .welcome h1 { font-size: 25px; } }
  `],
})
export class ChatPageComponent implements AfterViewChecked {
  chat = inject(ChatService);
  signalR = inject(SignalRService);
  private session = inject(SessionService);
  private settings = inject(SettingsService);
  notices = inject(NoticePrefsService);
  private fb = inject(FeedbackService);
  private toast = inject(ToastService);
  private dialogs = inject(DialogService);
  private bottom = viewChild<ElementRef<HTMLElement>>('bottom');
  private ta = viewChild<ElementRef<HTMLTextAreaElement>>('ta');

  text = '';
  questionText = '';
  mode = 'auto';
  rated = signal<Record<string, 'good' | 'bad'>>({});
  private lastCount = 0;
  private lastLen = 0;

  readonly suggestions = ['Cosa ho in agenda questa settimana?', 'Riassumi le ultime email importanti', 'Cosa ha pianificato Hestia per stanotte?', 'Ci sono nuove case interessanti?'];
  readonly menu: MenuItem[] = [
    { id: 'new', label: 'Nuova conversazione', icon: 'plus' },
    { id: 'clear', label: 'Pulisci schermo', icon: 'trash' },
  ];

  thinkingMode = computed(() => this.settings.settings().thinkingDisplay || 'compact');
  greeting = computed(() => {
    const h = new Date().getHours();
    return h < 6 ? 'Buona notte' : h < 13 ? 'Buongiorno' : h < 18 ? 'Buon pomeriggio' : 'Buonasera';
  });

  ngAfterViewChecked() {
    const msgs = this.chat.messages();
    const len = msgs.length ? msgs[msgs.length - 1].content.length : 0;
    if (msgs.length !== this.lastCount || len !== this.lastLen) {
      this.lastCount = msgs.length;
      this.lastLen = len;
      this.bottom()?.nativeElement.scrollIntoView({ block: 'end' });
    }
  }

  use(s: string) { this.text = s; this.send(); }

  send() {
    const t = this.text.trim();
    if (!t || this.chat.isStreaming()) return;
    void this.chat.sendMessage(t, this.session.sessionId() || '', this.mode, 'generic');
    this.text = '';
    queueMicrotask(() => this.grow());
  }

  onKey(e: KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); this.send(); }
  }

  grow() {
    const el = this.ta()?.nativeElement;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 240) + 'px';
  }

  onFile(e: Event) {
    const input = e.target as HTMLInputElement;
    const f = input.files?.[0];
    input.value = '';
    if (!f) return;
    const t = this.text.trim();
    this.text = '';
    void this.chat.sendDocument(f, t, this.session.sessionId() || '');
  }

  answer(id: string, v: string) { this.chat.answerQuestion(id, v); this.questionText = ''; }

  async feedback(label: 'good' | 'bad', m: ChatMessage) {
    const msgs = this.chat.messages();
    const idx = msgs.findIndex(x => x.id === m.id);
    const prompt = msgs.slice(0, Math.max(0, idx)).reverse().find(x => x.role === 'user')?.content || '';
    if (await this.fb.submit(label, '', { interactionId: m.id, prompt, response: m.content.replace(/<[^>]+>/g, '') })) {
      this.rated.update(r => ({ ...r, [m.id]: label }));
      this.toast.success('Grazie del feedback');
    }
  }

  async copy(m: ChatMessage) {
    const tmp = document.createElement('div');
    tmp.innerHTML = m.content;
    try { await navigator.clipboard.writeText(tmp.innerText); this.toast.success('Copiato'); } catch { /* */ }
  }

  async onMenu(id: string) {
    if (id === 'clear') this.chat.clearMessages();
    if (id === 'new' && await this.dialogs.confirm('Nuova conversazione?', 'Hestia dimentica il contesto di questa chat (le memorie restano).')) {
      await this.session.clear();
      this.chat.clearMessages();
    }
  }
}
