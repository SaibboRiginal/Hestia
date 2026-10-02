import { Component, inject, signal, effect, viewChild, ElementRef, AfterViewChecked } from '@angular/core';
import { ChatService } from '../../services/chat.service';
import { SessionService } from '../../services/session.service';
import { SignalRService } from '../../services/signalr.service';
import { ChatMessage } from '../../models/chat.models';
import { ThinkingDisplayComponent } from './thinking-display/thinking-display.component';
import { FeedbackService } from '../../services/feedback.service';
import { SettingsService } from '../../services/settings.service';
import { FormsModule } from '@angular/forms';

@Component({
  selector: 'app-chat-view',
  standalone: true,
  imports: [ThinkingDisplayComponent, FormsModule],
  template: `
    <div class="chat-root">
      @if (chat.messages().length === 0) {
        <div class="welcome">
          <div class="welcome-icon">🏛️</div>
          <h2>Hestia</h2>
          <p>How can I help you today?</p>
          <p class="conn-hint" [class.ok]="signalR.connectionState() === 'connected'">
            {{ signalR.connectionState() === 'connected' ? '● Connected' : '○ Connecting...' }}
          </p>
        </div>
      }
      <div class="msg-list" #scrollContainer>
        @for (msg of chat.messages(); track msg.id) {
          <div class="msg-row" [class.user]="msg.role === 'user'">
            @if (msg.role === 'user') {
              <div class="bubble user-bubble">{{ msg.content }}</div>
            } @else {
              <div class="bubble asst-bubble">
                @if (msg.thinkingSteps?.length && settings.settings().thinkingDisplay !== 'hidden') {
                  <app-thinking-display [steps]="msg.thinkingSteps!"
                                        [expandedByDefault]="settings.settings().thinkingDisplay === 'detailed'" />
                }
                @if (msg.content) {
                  <div class="msg-text" [innerHTML]="msg.content"></div>
                } @else if (msg.isStreaming) {
                  <span class="cursor">|</span>
                } @else {
                  <span class="empty-msg">(empty response)</span>
                }
                @if (msg.isStreaming && msg.content) {
                  <span class="cursor">|</span>
                }
                @if (!msg.isStreaming && msg.content) {
                  <div class="msg-foot">
                    <button (click)="feedback('good', msg)" title="Good" [class.on]="rated()[msg.id] === 'good'">👍</button>
                    <button (click)="feedback('bad', msg)" title="Bad" [class.on]="rated()[msg.id] === 'bad'">👎</button>
                    <button (click)="chat.retry()" title="Rigenera" [disabled]="chat.isStreaming()">🔄</button>
                  </div>
                }
              </div>
            }
          </div>
        }
        <div #bottom></div>
      </div>
      @if (chat.pendingQuestion(); as q) {
        <div class="question-card">
          <div class="q-header">❓ {{ q.header }}</div>
          @if (q.prompt) { <div class="q-prompt">{{ q.prompt }}</div> }
          @if (q.options.length) {
            <div class="q-options">
              @for (o of q.options; track o.value) {
                <button class="q-opt" (click)="answer(q.questionId, o.value)">{{ o.label }}</button>
              }
            </div>
          }
          @if (q.kind === 'free_text' || !q.options.length) {
            <div class="q-free">
              <input [(ngModel)]="questionText" (keydown.enter)="answer(q.questionId, questionText())"
                     placeholder="Rispondi..." />
              <button class="q-opt" (click)="answer(q.questionId, questionText())"
                      [disabled]="!questionText().trim()">Invia</button>
            </div>
          }
          @if (!q.required) {
            <button class="q-skip" (click)="answer(q.questionId, '')">Salta</button>
          }
        </div>
      }
      <div class="input-bar">
        <input #fileInput type="file" hidden (change)="onFile($event)" />
        <button class="btn-attach" title="Allega file" (click)="fileInput.click()"
                [disabled]="chat.isStreaming()">📎</button>
        <textarea
          #textArea
          [(ngModel)]="inputText"
          (keydown.enter)="$any($event).shiftKey || send()"
          [disabled]="chat.isStreaming()"
          placeholder="Message Hestia..."
          rows="1"
          (input)="autoGrow($event)"
        ></textarea>
        @if (chat.isStreaming()) {
          <button class="btn-send stop" (click)="chat.cancelStream()">■</button>
        } @else {
          <button class="btn-send" (click)="send()" [disabled]="!inputText().trim()">↑</button>
        }
      </div>
    </div>
  `,
  styles: [`
    :host { display:flex; flex-direction:column; flex:1; min-height:0; overflow:hidden; }
    .chat-root { display:flex; flex-direction:column; flex:1; min-height:0; background:var(--bg-primary); }
    .welcome { display:flex; flex-direction:column; align-items:center; justify-content:center; padding:64px 20px 32px; text-align:center; }
    .welcome-icon { font-size:56px; margin-bottom:12px; }
    .welcome h2 { font-size:24px; font-weight:700; color:var(--text-primary); margin-bottom:6px; }
    .welcome p { color:var(--text-secondary); font-size:15px; }
    .conn-hint { font-size:12px; margin-top:12px; color:var(--danger); }
    .conn-hint.ok { color:var(--success); }

    .msg-list { flex:1; overflow-y:auto; padding:16px; display:flex; flex-direction:column; gap:12px; }
    .msg-row { display:flex; max-width:90%; }
    .msg-row.user { align-self:flex-end; }
    .bubble { padding:10px 16px; border-radius:18px; line-height:1.5; font-size:15px; word-wrap:break-word; }
    .user-bubble { background:var(--accent); color:#fff; border-bottom-right-radius:4px; max-width:75%; }
    .asst-bubble { background:var(--bg-secondary); color:var(--text-primary); border-bottom-left-radius:4px; max-width:85%; }
    .cursor { display:inline-block; color:var(--accent); animation:pulse 0.8s infinite; font-weight:700; }
    .empty-msg { color:var(--text-muted); font-style:italic; }
    .msg-foot { display:flex; gap:4px; margin-top:8px; }
    .msg-foot button { background:none; border:none; font-size:15px; cursor:pointer; padding:2px 6px; border-radius:4px; opacity:0.5; }
    .msg-foot button:hover, .msg-foot button.on { opacity:1; background:var(--bg-hover); }

    .question-card { margin:0 16px 8px; padding:12px 14px; border:1px solid var(--accent); border-radius:12px; background:var(--bg-secondary); }
    .q-header { font-weight:600; color:var(--text-primary); margin-bottom:4px; }
    .q-prompt { color:var(--text-secondary); font-size:14px; margin-bottom:8px; }
    .q-options, .q-free { display:flex; flex-wrap:wrap; gap:6px; }
    .q-free input { flex:1; min-width:120px; background:var(--bg-input); border:1px solid var(--border); border-radius:8px; padding:6px 10px; color:var(--text-primary); }
    .q-opt { background:var(--accent); color:#fff; border:none; border-radius:8px; padding:6px 12px; cursor:pointer; }
    .q-opt:disabled { opacity:0.4; cursor:default; }
    .q-skip { margin-top:6px; background:none; border:none; color:var(--text-muted); cursor:pointer; font-size:12px; }
    .btn-attach { width:40px; height:40px; border-radius:50%; border:1px solid var(--border); background:var(--bg-secondary); font-size:17px; cursor:pointer; flex-shrink:0; }
    .btn-attach:disabled { opacity:0.3; cursor:default; }
    .input-bar { display:flex; gap:8px; padding:12px 16px 16px; border-top:1px solid var(--border); background:var(--bg-primary); }
    .input-bar textarea { flex:1; background:var(--bg-input); border:1px solid var(--border); border-radius:24px; padding:10px 18px; color:var(--text-primary); font-size:15px; font-family:Inter,sans-serif; resize:none; outline:none; max-height:160px; line-height:1.4; }
    .input-bar textarea:focus { border-color:var(--accent); }
    .btn-send { width:40px; height:40px; border-radius:50%; border:none; background:var(--accent); color:#fff; font-size:18px; font-weight:700; cursor:pointer; flex-shrink:0; display:flex; align-items:center; justify-content:center; }
    .btn-send:disabled { opacity:0.3; cursor:default; }
    .btn-send.stop { background:var(--danger); }

    @keyframes pulse { 0%,100% { opacity:1 } 50% { opacity:0.3 } }
  `]
})
export class ChatViewComponent implements AfterViewChecked {
  chat = inject(ChatService);
  signalR = inject(SignalRService);
  private session = inject(SessionService);
  private fb = inject(FeedbackService);
  settings = inject(SettingsService);
  inputText = signal('');
  questionText = signal('');
  private bottomEl = viewChild<ElementRef>('bottom');

  ngAfterViewChecked() { this.bottomEl()?.nativeElement?.scrollIntoView({ behavior: 'smooth' }); }

  send() {
    const t = this.inputText().trim();
    if (!t || this.chat.isStreaming()) return;
    this.chat.sendMessage(t, this.session.sessionId() || '', 'auto', 'generic');
    this.inputText.set('');
  }

  answer(questionId: string, value: string) {
    this.chat.answerQuestion(questionId, value);
    this.questionText.set('');
  }

  onFile(e: Event) {
    const input = e.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (!file) return;
    const text = this.inputText().trim();
    this.inputText.set('');
    void this.chat.sendDocument(file, text, this.session.sessionId() || '');
  }

  autoGrow(e: Event) {
    const el = e.target as HTMLTextAreaElement;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 160) + 'px';
  }

  rated = signal<Record<string, 'good' | 'bad'>>({});

  async feedback(label: 'good' | 'bad', msg: ChatMessage) {
    // Pair the rated answer with the user message before it (Metis builds datasets from both).
    const msgs = this.chat.messages();
    const idx = msgs.findIndex(m => m.id === msg.id);
    const prompt = [...msgs.slice(0, Math.max(0, idx))].reverse().find(m => m.role === 'user')?.content || '';
    const plain = (msg.content || '').replace(/<[^>]+>/g, '');
    if (await this.fb.submit(label, '', { interactionId: msg.id, prompt, response: plain })) {
      this.rated.update(r => ({ ...r, [msg.id]: label }));
    }
  }
}
