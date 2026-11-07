import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { AnswerBlocksComponent, AnswerPart, isComps, splitAnswer } from './answer-blocks.component';

/**
 * The text of one assistant message, exactly as the chat draws it: prose and answer blocks, the three dots while it
 * is being written, the caret while it streams. Used by the chat page and by the guided setup's first message
 * («I modelli sono pronti»), so the two never look different.
 */
@Component({
  selector: 'hx-assistant-text',
  imports: [AnswerBlocksComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (html()) {
      @for (p of parts(); track $index) {
        @if (isComps(p)) { <hx-answer-blocks [comps]="p.comps" (send)="send.emit($event)" /> }
        @else { <div class="hx-prose" [class.queued]="queued()" [innerHTML]="p.html"></div> }
      }
    }
    @if (streaming() && !queued()) { <div class="typing"><span></span><span></span><span></span></div> }
    @if (streaming() && html()) { <span class="caret"></span> }
  `,
  styles: [`
    :host { display: block; }
    .caret { display: inline-block; width: 8px; height: 17px; background: var(--accent); vertical-align: text-bottom; margin-left: 2px; animation: hx-pulse 1s infinite; border-radius: 2px; }
    .typing { display: inline-flex; gap: 4px; padding: 6px 0; }
    .typing span { width: 7px; height: 7px; border-radius: 50%; background: var(--text-3); animation: hx-pulse 1.2s infinite; }
    .typing span:nth-child(2) { animation-delay: .2s; } .typing span:nth-child(3) { animation-delay: .4s; }
    .hx-prose.queued { color: var(--text-2); }
  `],
})
export class AssistantTextComponent {
  /** The answer as HTML (the chat renders markdown before). */
  html = input<string>('');
  streaming = input<boolean>(false);
  queued = input<boolean>(false);
  send = output<string>();
  readonly isComps = isComps;
  private cache = new Map<string, AnswerPart[]>();

  parts(): AnswerPart[] {
    const html = this.html();
    if (this.streaming()) return [{ html }];
    let p = this.cache.get(html);
    if (!p) {
      p = splitAnswer(html);
      if (this.cache.size > 50) this.cache.clear();
      this.cache.set(html, p);
    }
    return p;
  }
}
