import { ChangeDetectionStrategy, Component, computed, inject, input, output, signal } from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { SegmentedComponent, SegmentOption, TimeFieldComponent, ToastService, ToggleComponent } from '../../ui';
import { CentralSettingsApi, SettingItem, SettingOption } from './central-settings.api';

/**
 * <hx-setting-control [item] [disabled] (commit)="store.set(item, $event)" />
 * The input for one central setting, chosen by its declared type. Emits only a complete value
 * (on toggle/select, or when a text field is confirmed): Themis validates and answers.
 * Reusable anywhere a setting is shown (Impostazioni, chat quick menu…).
 */
@Component({
  selector: 'hx-setting-control',
  imports: [NgTemplateOutlet, ToggleComponent, SegmentedComponent, TimeFieldComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @let it = item();
    @switch (it.type) {
      @case ('bool') {
        <hx-toggle [checked]="!!it.value" [disabled]="disabled()" (changed)="commit.emit($event)" />
      }
      @case ('enum') {
        @if (segmented()) {
          <hx-segmented [options]="segments()" [value]="indexOf(it.value)" (changed)="pick($event)"
                        [class.off]="disabled()" />
        } @else {
          <select class="hx-select" [disabled]="disabled()" (change)="pick($any($event.target).value)"
                  [attr.aria-label]="it.label">
            @for (o of options(); track $index) {
              <option [value]="'' + $index" [selected]="same(o.value, it.value)">{{ o.label }}</option>
            }
          </select>
        }
      }
      @case ('model') {
        <input class="hx-input mono" [attr.list]="listId()" [value]="text(it.value)" [disabled]="disabled()"
               [attr.aria-label]="it.label" placeholder="nome del modello"
               (focus)="loadChoices()" (change)="commitText($any($event.target).value)" (keydown.enter)="blur($event)" />
        <datalist [id]="listId()">
          @for (o of choices(); track $index) { <option [value]="o.value">{{ o.label }}</option> }
        </datalist>
        @if (loadingChoices()) { <span class="hint">carico i modelli…</span> }
      }
      @case ('int') { <ng-container [ngTemplateOutlet]="num" /> }
      @case ('float') { <ng-container [ngTemplateOutlet]="num" /> }
      @case ('time') {
        <hx-time [value]="text(it.value)" [disabled]="disabled()" (valueChange)="$event && commit.emit($event)" />
      }
      @case ('text') {
        <textarea class="hx-textarea" rows="4" [value]="text(it.value)" [disabled]="disabled()"
                  [attr.aria-label]="it.label" (change)="commitText($any($event.target).value)"></textarea>
      }
      @case ('list') {
        <textarea class="hx-textarea mono" rows="3" [value]="lines(it.value)" [disabled]="disabled()"
                  [attr.aria-label]="it.label" placeholder="un valore per riga"
                  (change)="commitList($any($event.target).value)"></textarea>
      }
      @case ('object') {
        <textarea class="hx-textarea mono" rows="5" [value]="json(it.value)" [disabled]="disabled()"
                  [attr.aria-label]="it.label" (change)="commitJson($any($event.target).value)"></textarea>
      }
      @default {
        <input class="hx-input" [value]="text(it.value)" [disabled]="disabled()" [attr.aria-label]="it.label"
               [placeholder]="it.type === 'duration' ? 'es. 30s, 5m, 2h' : ''"
               (change)="commitText($any($event.target).value)" (keydown.enter)="blur($event)" />
      }
    }
    <ng-template #num>
      <span class="num">
        <input class="hx-input" type="number" [value]="item().value" [disabled]="disabled()" [attr.aria-label]="item().label"
               [attr.min]="item().min ?? null" [attr.max]="item().max ?? null" [attr.step]="item().type === 'int' ? 1 : 'any'"
               (change)="commitNumber($any($event.target).value)" (keydown.enter)="blur($event)" />
        @if (item().unit) { <span class="unit">{{ item().unit }}</span> }
      </span>
    </ng-template>`,
  styles: [`
    :host { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
    .num { display: inline-flex; align-items: center; gap: 8px; }
    .num .hx-input { width: 130px; }
    .unit, .hint { font-size: 12px; color: var(--text-3); }
    hx-segmented { align-self: flex-start; flex-wrap: wrap; }
    hx-segmented.off { opacity: .5; pointer-events: none; }
  `],
})
export class SettingControlComponent {
  private api = inject(CentralSettingsApi);
  private toast = inject(ToastService);

  item = input.required<SettingItem>();
  disabled = input(false);
  /** Table cells: always a dropdown, never a wide segmented control. */
  compact = input(false);
  commit = output<unknown>();

  readonly choices = signal<SettingOption[]>([]);
  readonly loadingChoices = signal(false);
  readonly listId = computed(() => 'opts-' + this.item().key.replace(/[^a-z0-9]/gi, '-'));

  readonly options = computed(() => this.item().options ?? []);
  readonly segmented = computed(() => {
    const o = this.options();
    return !this.compact() && o.length > 1 && o.length <= 4 && o.reduce((n, x) => n + String(x.label).length, 0) <= 44;
  });
  readonly segments = computed<SegmentOption[]>(() => this.options().map((o, i) => ({ value: String(i), label: o.label })));

  same(a: unknown, b: unknown) { return JSON.stringify(a) === JSON.stringify(b); }
  indexOf(v: unknown) { const i = this.options().findIndex(o => this.same(o.value, v)); return i < 0 ? null : String(i); }
  pick(index: string) { const o = this.options()[+index]; if (o) this.commit.emit(o.value); }

  text(v: unknown) { return v === null || v === undefined ? '' : String(v); }
  lines(v: unknown) { return Array.isArray(v) ? v.join('\n') : ''; }
  json(v: unknown) { return v === null || v === undefined ? '' : JSON.stringify(v, null, 2); }
  blur(e: Event) { (e.target as HTMLElement).blur(); }

  commitText(v: string) { this.commit.emit(v.trim()); }
  commitNumber(v: string) {
    if (v.trim() === '') return;
    const n = Number(v);
    if (Number.isNaN(n)) { this.toast.error('Numero non valido'); return; }
    this.commit.emit(n);
  }
  commitList(v: string) { this.commit.emit(v.split('\n').map(s => s.trim()).filter(Boolean)); }
  commitJson(v: string) {
    try { this.commit.emit(JSON.parse(v)); } catch { this.toast.error('JSON non valido'); }
  }

  /** Model names come from the owning module (e.g. installed Ollama models), via Themis. */
  async loadChoices() {
    const it = this.item();
    if (!it.options_source && !it.options?.length) return;
    this.loadingChoices.set(true);
    try { this.choices.set(await this.api.options(it.key)); } catch { this.choices.set([]); }
    finally { this.loadingChoices.set(false); }
  }
}
