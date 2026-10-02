import { Component, inject } from '@angular/core';
import { SessionService } from '../../../services/session.service';
import { ChatService } from '../../../services/chat.service';

@Component({
  selector: 'app-session-list',
  standalone: true,
  template: `
    <div class="session-panel">
      <h3>Current Session</h3>
      <div class="session-info">
        <code>{{ session.sessionId() || '(not created)' }}</code>
      </div>
      <div class="session-actions">
        <button class="btn btn-danger" (click)="clear()">🧹 Clear Session</button>
      </div>
      <p class="hint">Clearing starts a new conversation. Chat history is deleted.</p>
    </div>
  `,
  styles: [`
    .session-panel { padding: 4px; }
    h3 { font-size: 13px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 12px; }
    .session-info { margin-bottom: 12px; }
    .session-info code {
      display: block; font-size: 12px; padding: 8px 12px;
      background: var(--bg-tertiary); border-radius: var(--radius-sm);
      word-break: break-all;
    }
    .session-actions { margin-bottom: 12px; }
    .btn {
      display: block; width: 100%; padding: 10px 14px;
      border: none; border-radius: var(--radius-md); font-size: 14px;
      font-weight: 500; cursor: pointer; font-family: 'Inter', sans-serif;
      transition: all var(--transition-fast);
    }
    .btn-danger { background: rgba(231, 76, 60, 0.15); color: var(--danger); }
    .btn-danger:hover { background: rgba(231, 76, 60, 0.25); }
    .hint { font-size: 12px; color: var(--text-muted); line-height: 1.5; }
  `]
})
export class SessionListComponent {
  session = inject(SessionService);
  private chat = inject(ChatService);

  async clear(): Promise<void> {
    await this.session.clear();
    this.chat.clearMessages();
  }
}
