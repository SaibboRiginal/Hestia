import { Component, input, effect, inject, viewChild, ElementRef, AfterViewChecked } from '@angular/core';
import { ChatMessage } from '../../../models/chat.models';
import { ChatMessageComponent } from '../chat-message/chat-message.component';

@Component({
  selector: 'app-message-list',
  standalone: true,
  imports: [ChatMessageComponent],
  template: `
    <div class="message-list" #scrollContainer>
      @if (messages().length === 0) {
        <div class="welcome">
          <div class="welcome-icon">🏛️</div>
          <h2>Hestia</h2>
          <p>How can I help you today?</p>
        </div>
      }
      @for (msg of messages(); track msg.id) {
        <app-chat-message [message]="msg" />
      }
      <div #bottom></div>
    </div>
  `,
  styles: [`
    .message-list {
      flex: 1; overflow-y: auto; padding: 24px 16px;
      display: flex; flex-direction: column; gap: 8px;
    }
    .welcome {
      display: flex; flex-direction: column; align-items: center;
      justify-content: center; padding: 80px 20px; text-align: center;
      animation: fadeIn 0.6s ease;
    }
    .welcome-icon { font-size: 72px; margin-bottom: 16px; }
    .welcome h2 { font-size: 28px; font-weight: 700; color: var(--text-primary); margin-bottom: 8px; }
    .welcome p { color: var(--text-secondary); font-size: 16px; }
  `]
})
export class MessageListComponent implements AfterViewChecked {
  messages = input.required<ChatMessage[]>();
  isStreaming = input(false);
  private scrollEl = viewChild<ElementRef>('scrollContainer');
  private bottomEl = viewChild<ElementRef>('bottom');

  ngAfterViewChecked(): void {
    this.bottomEl()?.nativeElement?.scrollIntoView({ behavior: 'smooth' });
  }
}
