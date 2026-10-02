import { Component, inject } from '@angular/core';
import { SettingsService } from '../../../services/settings.service';
import { FormsModule } from '@angular/forms';

@Component({
  selector: 'app-settings-panel',
  standalone: true,
  imports: [FormsModule],
  template: `
    <div class="settings-panel">
      <h3>Session Settings</h3>

      <div class="setting-group">
        <label>Tone</label>
        <select [(ngModel)]="tone" (change)="update()">
          <option value="neutral">Neutral</option>
          <option value="warm">Warm</option>
          <option value="direct">Direct</option>
          <option value="formal">Formal</option>
        </select>
      </div>

      <div class="setting-group">
        <label>Thinking Display</label>
        <select [(ngModel)]="thinkingDisplay" (change)="update()">
          <option value="hidden">Hidden</option>
          <option value="compact">Compact</option>
          <option value="detailed">Detailed</option>
        </select>
      </div>

      <div class="setting-group">
        <label>Custom Prompt</label>
        <textarea
          [(ngModel)]="customPrompt"
          (blur)="update()"
          placeholder="Custom instructions for Oracle..."
          rows="3"
        ></textarea>
      </div>

      <button class="btn-reset" (click)="reset()">Reset to Defaults</button>
    </div>
  `,
  styles: [`
    .settings-panel { padding: 4px; }
    h3 { font-size: 13px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 16px; }
    .setting-group { margin-bottom: 16px; }
    .setting-group label { display: block; font-size: 13px; color: var(--text-secondary); margin-bottom: 6px; font-weight: 500; }
    .setting-group select, .setting-group textarea {
      width: 100%; padding: 10px 12px; background: var(--bg-tertiary);
      border: 1px solid var(--border); border-radius: var(--radius-md);
      color: var(--text-primary); font-size: 14px; font-family: 'Inter', sans-serif;
      outline: none; resize: vertical;
    }
    .setting-group select:focus, .setting-group textarea:focus { border-color: var(--accent); }
    .btn-reset {
      width: 100%; padding: 10px; background: none; border: 1px solid var(--border);
      border-radius: var(--radius-md); color: var(--text-secondary); font-size: 13px;
      cursor: pointer; font-family: 'Inter', sans-serif;
      transition: all var(--transition-fast);
    }
    .btn-reset:hover { border-color: var(--danger); color: var(--danger); }
  `]
})
export class SettingsPanelComponent {
  private settingsService = inject(SettingsService);
  tone = 'neutral';
  customPrompt = '';
  thinkingDisplay = 'hidden';

  constructor() {
    const s = this.settingsService.settings();
    this.tone = s.tone;
    this.customPrompt = s.customPrompt;
    this.thinkingDisplay = s.thinkingDisplay;
  }

  async update(): Promise<void> {
    await this.settingsService.update({
      tone: this.tone,
      customPrompt: this.customPrompt,
      thinkingDisplay: this.thinkingDisplay
    });
  }

  async reset(): Promise<void> {
    await this.settingsService.reset();
    const s = this.settingsService.settings();
    this.tone = s.tone;
    this.customPrompt = s.customPrompt;
    this.thinkingDisplay = s.thinkingDisplay;
  }
}
