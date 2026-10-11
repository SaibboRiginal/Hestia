import { ChangeDetectionStrategy, Component, computed, effect, input, signal, untracked } from '@angular/core';
import { ThinkingStep } from '../../models/chat.models';
import { IconComponent } from '../../ui';

/**
 * Reasoning / tool trace of an assistant answer ("Ragionamento · 3 passi").
 * `display` (Impostazioni → Ragionamento): compact = closed, one line per step · detailed = open,
 * full reasoning text and tool results · live = open while working, closes when the answer arrives.
 * A click on the header always wins over the automatic open/close.
 */
@Component({
  selector: 'chat-thinking',
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <button class="toggle" (click)="toggle()">
      <hx-icon [name]="live() ? 'sparkle' : 'brain'" [size]="14" [class.pulse]="live()" />
      <span>{{ live() ? 'Sto ragionando…' : 'Ragionamento' }}</span>
      <span class="sum">{{ summary() }}</span>
      <hx-icon [name]="open() ? 'chevron-up' : 'chevron-down'" [size]="14" />
    </button>
    @if (open()) {
      <ol class="steps" [class.full]="full()">
        @for (s of steps(); track s.stepNumber) {
          <li [attr.data-type]="s.type">
            <hx-icon [name]="s.type === 'tool_call' ? 'zap' : s.type === 'tool_result' ? (s.metadata?.ok ? 'check' : 'alert') : 'brain'" [size]="13" />
            <div class="body">
              <span class="txt">{{ label(s) }}</span>
              @if (full() && s.type === 'tool_result' && s.content) { <pre class="res">{{ s.content }}</pre> }
            </div>
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
    .steps.full { gap: 8px; }
    li { display: flex; gap: 7px; font-size: 13px; color: var(--text-2); align-items: flex-start; }
    li hx-icon { margin-top: 3px; color: var(--text-3); }
    li[data-type=tool_result] hx-icon { color: var(--success); }
    .body { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
    .txt { white-space: pre-wrap; word-break: break-word; }
    .res { margin: 0; font-size: 12px; color: var(--text-3); background: var(--surface-2); border-radius: var(--radius-sm); padding: 6px 8px;
           white-space: pre-wrap; word-break: break-word; max-height: 180px; overflow: auto; }
  `],
})
export class ThinkingStepsComponent {
  steps = input.required<ThinkingStep[]>();
  live = input(false);
  /** compact | detailed | live (hidden = the parent does not render this component). */
  display = input<string>('compact');
  open = signal(false);
  private touched = false;

  readonly full = computed(() => this.display() === 'detailed');

  constructor() {
    effect(() => {
      const d = this.display(), working = this.live();
      if (untracked(() => this.touched)) return;
      this.open.set(d === 'detailed' || (d === 'live' && working));
    });
  }

  toggle() { this.touched = true; this.open.set(!this.open()); }

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
    const text = s.content || '';
    return this.full() ? text : text.split('\n')[0].slice(0, 300);
  }
}
