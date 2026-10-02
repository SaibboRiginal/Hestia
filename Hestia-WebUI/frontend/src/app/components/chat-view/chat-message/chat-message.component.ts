import { Component, input, inject } from '@angular/core';
import { ChatMessage } from '../../../models/chat.models';
import { FeedbackService } from '../../../services/feedback.service';
import { ThinkingDisplayComponent } from '../thinking-display/thinking-display.component';
import { SafeHtmlPipe } from '../../../pipes/safe-html.pipe';
import { NgClass } from '@angular/common';

@Component({
  selector: 'app-chat-message',
  standalone: true,
  imports: [ThinkingDisplayComponent, SafeHtmlPipe, NgClass],
  template: `
    <div class="msg-wrapper" [ngClass]="message().role">
      @if (message().role === 'user') {
        <div class="msg user-msg fade-in">
          <div class="msg-content" [innerHTML]="message().content | safeHtml"></div>
        </div>
      } @else {
        <div class="msg assistant-msg fade-in">
          @if ((message().thinkingSteps?.length ?? 0) > 0) {
            <app-thinking-display [steps]="message().thinkingSteps!" />
          }
          <div class="msg-content">
            @if (message().isStreaming && !message().content) {
              <span class="streaming-cursor"></span>
            } @else {
              <div [innerHTML]="message().content || '' | safeHtml"></div>
              @if (message().isStreaming) {
                <span class="streaming-cursor"></span>
              }
            }
          </div>
          @if (!message().isStreaming && message().content) {
            <div class="msg-actions">
              <button class="action-btn" (click)="feedback('good')" title="Good">👍</button>
              <button class="action-btn" (click)="feedback('bad')" title="Bad">👎</button>
            </div>
          }
        </div>
      }
    </div>
  `,
  styles: [`
    .msg-wrapper { display: flex; margin-bottom: 4px; }
    .msg-wrapper.user { justify-content: flex-end; }
    .msg-wrapper.assistant { justify-content: flex-start; }
    .msg { max-width: 80%; }
    .user-msg {
      background: var(--user-bubble); color: var(--user-bubble-text);
      padding: 12px 18px; border-radius: var(--radius-lg) var(--radius-lg) 4px var(--radius-lg);
      line-height: 1.5;
    }
    .assistant-msg {
      padding: 4px 0; color: var(--text-primary); line-height: 1.6;
      width: 100%; max-width: var(--chat-max-width);
    }
    .msg-content { word-wrap: break-word; overflow-wrap: break-word; }
    .msg-content ::ng-deep pre { margin: 8px 0; }
    .msg-content ::ng-deep p { margin: 4px 0; }
    .streaming-cursor {
      display: inline-block; width: 8px; height: 18px;
      background: var(--accent); margin-left: 2px; vertical-align: text-bottom;
      animation: pulse 0.8s ease infinite;
    }
    .msg-actions { display: flex; gap: 4px; margin-top: 8px; opacity: 0; transition: opacity var(--transition-fast); }
    .msg-wrapper.assistant:hover .msg-actions { opacity: 1; }
    .action-btn { background: none; border: none; font-size: 16px; cursor: pointer; padding: 4px 6px; border-radius: var(--radius-sm); }
    .action-btn:hover { background: var(--bg-hover); }
  `]
})
export class ChatMessageComponent {
  message = input.required<ChatMessage>();
  private feedbackService = inject(FeedbackService);

  feedback(label: 'good' | 'bad'): void {
    this.feedbackService.submit(label);
  }
}
