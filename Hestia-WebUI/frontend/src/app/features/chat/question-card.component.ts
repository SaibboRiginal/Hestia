import { ChangeDetectionStrategy, Component, computed, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { PendingQuestion } from '../../models/chat.models';
import { ButtonComponent, IconComponent } from '../../ui';

/**
 * A question from the assistant (Chat page and "Crea con Hestia" drawer): confirm, single choice, multiple choice
 * (pick then «Invia») or free text; choice kinds with `allowOther` also take a free answer («Altro…»).
 * Multiple answers are sent one per line (oracle-offline v3 A).
 */
@Component({
  selector: 'hx-question-card',
  imports: [FormsModule, ButtonComponent, IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @let q = question();
    <div class="question hx-fade-in" [class.compact]="compact()">
      <div class="qh"><hx-icon [name]="q.kind === 'confirm' ? 'check-circle' : 'info'" tone="accent" [size]="15" /> {{ q.header }}</div>
      @if (q.prompt) { <div class="qp">{{ q.prompt }}</div> }
      @if (q.options.length) {
        <div class="qo">
          @for (o of q.options; track o.value) {
            @if (multi()) {
              <button hx-btn size="sm" [variant]="picked().includes(o.value) ? 'primary' : 'secondary'" (click)="toggle(o.value)"
                      [attr.aria-pressed]="picked().includes(o.value)">
                <hx-icon [name]="picked().includes(o.value) ? 'check' : 'plus'" [size]="13" /> {{ o.label }}</button>
            } @else {
              <button hx-btn size="sm" (click)="send(o.value)">{{ o.label }}</button>
            }
          }
        </div>
      }
      @if (freeField()) {
        <div class="qf">
          <input class="hx-input" [(ngModel)]="text" (keydown.enter)="submit()"
                 [placeholder]="q.options.length ? 'Altro…' : 'Rispondi…'" />
          @if (!multi()) { <button hx-btn variant="primary" size="sm" (click)="submit()" [disabled]="!text.trim()">Invia</button> }
        </div>
      }
      @if (multi()) {
        <div class="qf"><button hx-btn variant="primary" size="sm" (click)="submit()" [disabled]="!picked().length && !text.trim()">Invia</button></div>
      }
      @if (!q.required) { <button class="skipq" (click)="send('')">Salta</button> }
    </div>
  `,
  styles: [`
    .question { background: var(--surface); border: 1px solid var(--accent); border-radius: var(--radius-lg); padding: 12px 14px; margin-bottom: 10px; box-shadow: var(--shadow-1); }
    .question.compact { border-radius: var(--radius-md); padding: 10px 12px; margin-bottom: 8px; box-shadow: none; }
    .qh { display: flex; align-items: center; gap: 6px; font-weight: 600; font-size: 14px; }
    .qp { color: var(--text-2); font-size: 13.5px; margin: 4px 0 8px; }
    .qo, .qf { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 6px; }
    .qf .hx-input { flex: 1; min-width: 140px; }
    .skipq { font-size: 12px; color: var(--text-3); margin-top: 6px; }
  `],
})
export class QuestionCardComponent {
  question = input.required<PendingQuestion>();
  compact = input(false);
  answered = output<string>();

  text = '';
  picked = signal<string[]>([]);
  multi = computed(() => this.question().kind === 'multi_choice');
  freeField = computed(() => {
    const q = this.question();
    return q.kind === 'free_text' || !q.options.length || !!q.allowOther;
  });

  toggle(v: string) {
    this.picked.update(p => p.includes(v) ? p.filter(x => x !== v) : [...p, v]);
  }

  submit() {
    const other = this.text.trim();
    if (this.multi()) {
      const all = [...this.picked(), ...(other ? [other] : [])];
      if (all.length) this.send(all.join('\n'));
    } else if (other) {
      this.send(other);
    }
  }

  send(v: string) {
    this.answered.emit(v);
    this.text = '';
    this.picked.set([]);
  }
}
