import { Component, input, signal } from '@angular/core';
import { ThinkingStep } from '../../../models/chat.models';
import { NgClass } from '@angular/common';

@Component({
  selector: 'app-thinking-display',
  standalone: true,
  imports: [NgClass],
  template: `
    @if (steps().length > 0) {
      <div class="thinking-container">
        <button class="thinking-toggle" (click)="expanded.set(!expanded())">
          <span class="toggle-icon">{{ expanded() ? '▼' : '▶' }}</span>
          <span class="toggle-label">
            Reasoning
            <span class="toggle-summary">({{ summary() }})</span>
          </span>
        </button>
        @if (expanded()) {
          <div class="thinking-steps">
            @for (step of steps(); track step.stepNumber) {
              <div class="thinking-step" [ngClass]="step.type">
                <div class="step-header" (click)="toggleStep(step.stepNumber)">
                  <span class="step-number">{{ step.stepNumber }}</span>
                  <span class="step-icon">{{ stepIcon(step) }}</span>
                  <span class="step-title">{{ stepTitle(step) }}</span>
                  <span class="step-chevron">{{ step.isExpanded ? '▼' : '▶' }}</span>
                </div>
                @if (step.isExpanded && step.content) {
                  <div class="step-content">{{ step.content }}</div>
                }
              </div>
            }
          </div>
        }
      </div>
    }
  `,
  styles: [`
    .thinking-container {
      margin: 8px 0; border: 1px solid var(--thinking-border);
      border-radius: var(--radius-md); background: var(--thinking-bg);
      overflow: hidden; animation: fadeIn 0.3s ease;
    }
    .thinking-toggle {
      width: 100%; display: flex; align-items: center; gap: 8px;
      padding: 10px 14px; background: none; border: none;
      color: var(--text-secondary); font-size: 13px;
      font-family: 'Inter', sans-serif; cursor: pointer;
      transition: background var(--transition-fast);
    }
    .thinking-toggle:hover { background: var(--thinking-step-bg); }
    .toggle-icon { font-size: 10px; flex-shrink: 0; }
    .toggle-label { font-weight: 500; }
    .toggle-summary { color: var(--text-muted); font-weight: 400; }
    .thinking-steps { border-top: 1px solid var(--thinking-border); }
    .thinking-step { border-bottom: 1px solid var(--thinking-border); }
    .thinking-step:last-child { border-bottom: none; }
    .step-header {
      display: flex; align-items: center; gap: 8px;
      padding: 8px 14px 8px 24px; cursor: pointer;
      transition: background var(--transition-fast);
      font-size: 13px; color: var(--text-secondary);
    }
    .step-header:hover { background: var(--thinking-step-bg); }
    .step-number {
      width: 20px; height: 20px; border-radius: 50%;
      background: var(--accent-light); color: var(--accent);
      display: flex; align-items: center; justify-content: center;
      font-size: 11px; font-weight: 600; flex-shrink: 0;
    }
    .step-icon { font-size: 13px; flex-shrink: 0; }
    .step-title { flex: 1; font-weight: 500; }
    .step-chevron { font-size: 9px; color: var(--text-muted); }
    .step-content {
      padding: 8px 14px 12px 52px; font-size: 13px;
      color: var(--text-secondary); line-height: 1.5;
      white-space: pre-wrap; word-wrap: break-word;
      font-style: italic; opacity: 0.85;
    }
    .thinking-step.tool_call .step-number { background: rgba(243, 156, 18, 0.15); color: var(--warning); }
    .thinking-step.tool_result .step-number { background: rgba(39, 174, 96, 0.15); color: var(--success); }
  `]
})
export class ThinkingDisplayComponent {
  steps = input.required<ThinkingStep[]>();
  expanded = signal(false);

  // Track per-step expansion state
  private stepState = new Map<number, boolean>();

  toggleStep(stepNum: number): void {
    const steps = this.steps();
    const step = steps.find(s => s.stepNumber === stepNum);
    if (step) {
      step.isExpanded = !step.isExpanded;
    }
  }

  stepIcon(step: ThinkingStep): string {
    switch (step.type) {
      case 'reasoning': return '💭';
      case 'tool_call': return '🔧';
      case 'tool_result': return step.metadata?.ok ? '✅' : '❌';
      default: return '•';
    }
  }

  stepTitle(step: ThinkingStep): string {
    switch (step.type) {
      case 'reasoning': return `Step ${step.stepNumber}`;
      case 'tool_call': return step.tool || 'Tool call';
      case 'tool_result': {
        const count = step.metadata?.result_count;
        const dur = step.metadata?.duration_ms;
        const parts = [step.tool || 'Result'];
        if (count) parts.push(`(${count} results)`);
        if (dur) parts.push(`${dur}ms`);
        return parts.join(' ');
      }
      default: return '';
    }
  }

  summary(): string {
    const steps = this.steps();
    const r = steps.filter(s => s.type === 'reasoning').length;
    const t = steps.filter(s => s.type === 'tool_call').length;
    const ok = steps.filter(s => s.type === 'tool_result' && s.metadata?.ok).length;
    let totalMs = 0;
    for (const s of steps) {
      if (s.metadata?.duration_ms) totalMs += s.metadata.duration_ms;
    }
    const parts: string[] = [];
    if (r > 0) parts.push(`R:${r}`);
    if (t > 0) parts.push(`T:${t}`);
    if (ok > 0) parts.push(`OK:${ok}`);
    if (totalMs > 0) parts.push(`${totalMs}ms`);
    return parts.join(' ');
  }
}
