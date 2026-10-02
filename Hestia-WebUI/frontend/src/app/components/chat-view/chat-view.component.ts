import { Component, inject, signal, effect, viewChild, ElementRef, AfterViewChecked } from '@angular/core';
import { ChatService } from '../../services/chat.service';
import { SessionService } from '../../services/session.service';
import { SignalRService } from '../../services/signalr.service';
import { ChatMessage } from '../../models/chat.models';
import { ThinkingDisplayComponent } from './thinking-display/thinking-display.component';
import { FeedbackService } from '../../services/feedback.service';
import { FormsModule } from '@angular/forms';
import { DatePipe } from '@angular/common';

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
                @if (msg.thinkingSteps?.length) {
                  <app-thinking-display [steps]="msg.thinkingSteps!" />
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
                    <button (click)="feedback('good', msg)" title="Good">👍</button>
                    <button (click)="feedback('bad', msg)" title="Bad">👎</button>
                  </div>
                }
              </div>
            }
          </div>
        }
        <div #bottom></div>
      </div>
      <div class="input-bar">
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
    .msg-foot button:hover { opacity:1; background:var(--bg-hover); }

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
  inputText = signal('');
  private bottomEl = viewChild<ElementRef>('bottom');

  ngAfterViewChecked() { this.bottomEl()?.nativeElement?.scrollIntoView({ behavior: 'smooth' }); }

  send() {
    const t = this.inputText().trim();
    if (!t || this.chat.isStreaming()) return;
    this.chat.sendMessage(t, this.session.sessionId() || '', 'auto', 'generic');
    this.inputText.set('');
  }

  autoGrow(e: Event) {
    const el = e.target as HTMLTextAreaElement;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 160) + 'px';
  }

  feedback(label: 'good' | 'bad', msg: ChatMessage) { this.fb.submit(label); }
}
