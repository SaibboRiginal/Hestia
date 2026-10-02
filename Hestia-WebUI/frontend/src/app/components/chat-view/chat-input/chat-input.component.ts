import { Component, input, output, viewChild, ElementRef, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { FileDropzoneComponent } from '../file-dropzone/file-dropzone.component';

@Component({
  selector: 'app-chat-input',
  standalone: true,
  imports: [FormsModule, FileDropzoneComponent],
  template: `
    <div class="input-container">
      <div class="input-wrapper">
        <textarea
          #textArea
          [(ngModel)]="inputText"
          (keydown.enter)="$any($event).shiftKey || onSend()"
          (keydown.escape)="cancel.emit()"
          (input)="autoResize()"
          [disabled]="disabled()"
          placeholder="Message Hestia..."
          rows="1"
          class="chat-input"
        ></textarea>
        <div class="input-actions">
          <button class="attach-btn" (click)="showDropzone.set(!showDropzone())" title="Attach file">
            📎
          </button>
          @if (disabled()) {
            <button class="send-btn cancel" (click)="cancel.emit()" title="Cancel">
              ■
            </button>
          } @else {
            <button class="send-btn" (click)="onSend()" [disabled]="!inputText().trim()" title="Send">
              ↑
            </button>
          }
        </div>
      </div>
      @if (showDropzone()) {
        <app-file-dropzone (close)="showDropzone.set(false)" />
      }
      <p class="input-hint">Hestia can make mistakes. Verify important information.</p>
    </div>
  `,
  styles: [`
    .input-container {
      padding: 16px 16px 12px; flex-shrink: 0;
      max-width: var(--chat-max-width); width: 100%;
      margin: 0 auto;
    }
    .input-wrapper {
      display: flex; align-items: flex-end; gap: 8px;
      background: var(--bg-input); border: 1px solid var(--border);
      border-radius: var(--radius-xl); padding: 8px 12px;
      transition: border-color var(--transition-fast);
    }
    .input-wrapper:focus-within { border-color: var(--accent); }
    .chat-input {
      flex: 1; background: none; border: none; color: var(--text-primary);
      font-size: 15px; font-family: 'Inter', sans-serif; line-height: 1.5;
      resize: none; outline: none; max-height: var(--input-max-height);
      padding: 4px 0;
    }
    .chat-input::placeholder { color: var(--text-muted); }
    .input-actions { display: flex; gap: 4px; align-items: center; flex-shrink: 0; }
    .attach-btn, .send-btn {
      background: none; border: none; cursor: pointer;
      padding: 6px; border-radius: var(--radius-full);
      display: flex; align-items: center; justify-content: center;
      width: 34px; height: 34px; font-size: 16px;
      transition: background var(--transition-fast);
    }
    .attach-btn:hover { background: var(--bg-hover); }
    .send-btn {
      background: var(--accent); color: white; font-weight: 700; font-size: 18px;
    }
    .send-btn:hover:not(:disabled) { background: var(--accent-hover); }
    .send-btn:disabled { opacity: 0.4; cursor: not-allowed; }
    .send-btn.cancel { background: var(--danger); }
    .input-hint {
      text-align: center; font-size: 11px; color: var(--text-muted);
      margin-top: 8px;
    }
  `]
})
export class ChatInputComponent {
  disabled = input(false);
  send = output<string>();
  cancel = output<void>();

  inputText = signal('');
  showDropzone = signal(false);
  private textAreaEl = viewChild<ElementRef>('textArea');

  onSend(): void {
    const text = this.inputText().trim();
    if (!text || this.disabled()) return;
    this.send.emit(text);
    this.inputText.set('');
    // Reset height
    const el = this.textAreaEl()?.nativeElement as HTMLTextAreaElement;
    if (el) el.style.height = 'auto';
  }

  autoResize(): void {
    const el = this.textAreaEl()?.nativeElement as HTMLTextAreaElement;
    if (el) {
      el.style.height = 'auto';
      el.style.height = Math.min(el.scrollHeight, 200) + 'px';
    }
  }
}
