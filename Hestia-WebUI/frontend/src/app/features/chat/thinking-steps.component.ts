import { ChangeDetectionStrategy, Component, OnInit, computed, input, signal } from '@angular/core';
import { ThinkingStep } from '../../models/chat.models';
import { IconComponent } from '../../ui';

/** Collapsible reasoning / tool trace of an assistant answer ("Ragionamento · 3 passi"). */
@Component({
  selector: 'chat-thinking',
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <button class="toggle" (click)="open.set(!open())">
      <hx-icon [name]="live() ? 'sparkle' : 'brain'" [size]="14" [class.pulse]="live()" />
      <span>{{ live() ? 'Sto ragionando…' : 'Ragionamento' }}</span>
      <span class="sum">{{ summary() }}</span>
      <hx-icon [name]="open() ? 'chevron-up' : 'chevron-down'" [size]="14" />
    </button>
    @if (open()) {
      <ol class="steps">
        @for (s of steps(); track s.stepNumber) {
          <li [attr.data-type]="s.type">
            <hx-icon [name]="s.type === 'tool_call' ? 'zap' : s.type === 'tool_result' ? (s.metadata?.ok ? 'check' : 'alert') : 'brain'" [size]="13" />
            <span class="txt">{{ label(s) }}</span>
          </li>
        }
      </ol>
    }`,
  styles: [`
    :host { display: block; margin-bottom: 8px; }
    .toggle { display: inline-flex; align-items: center; gap: 6px; font-size: 12.5px; color: var(--text-3); padding: 3px 8px 3px 4px; border-radius: var(--radius-sm); }
    .toggle:hover { color: var(--text-2); background: var(--surface-2); }
    .sum { color: var(--text-3); opacity: .8; }
    .pulse { animation: hx-pulse 1.2s infinite; color: var(--accent); }
    .steps { list-style: none; margin: 6px 0 4px 6px; padding-left: 12px; border-left: 2px solid var(--border); display: flex; flex-direction: column; gap: 5px; }
    li { display: flex; gap: 7px; font-size: 13px; color: var(--text-2); align-items: flex-start; }
    li hx-icon { margin-top: 3px; color: var(--text-3); }
    li[data-type=tool_result] hx-icon { color: var(--success); }
    .txt { white-space: pre-wrap; word-break: break-word; }
  `],
})
export class ThinkingStepsComponent implements OnInit {
  steps = input.required<ThinkingStep[]>();
  live = input(false);
  expandedByDefault = input(false);
  open = signal(false);
  ngOnInit() { this.open.set(this.expandedByDefault()); }

  summary = computed(() => {
    const s = this.steps();
    const tools = s.filter(x => x.type === 'tool_call').length;
    return `· ${s.length} passi${tools ? ` · ${tools} strumenti` : ''}`;
  });

  label(s: ThinkingStep): string {
    if (s.type === 'tool_call') return `Uso ${s.tool}`;
    if (s.type === 'tool_result') {
      const n = s.metadata?.result_count, ms = s.metadata?.duration_ms;
      return `${s.tool}: ${s.metadata?.ok ? 'ok' : 'errore'}${n ? ` · ${n} risultati` : ''}${ms ? ` · ${ms} ms` : ''}`;
    }
    return (s.content || '').split('\n')[0].slice(0, 300);
  }
}
