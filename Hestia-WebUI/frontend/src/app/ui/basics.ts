/** Small presentational components: badge, spinner, empty state, field, page header, toggle, segmented. */
import { ChangeDetectionStrategy, Component, booleanAttribute, input, model, output } from '@angular/core';
import { IconComponent } from './icon.component';

export type Tone = 'neutral' | 'accent' | 'success' | 'danger' | 'warning' | 'info';

/** <hx-badge tone="success">ok</hx-badge> — optional [dot]="true" or [color]="'var(--cal-2)'". */
@Component({
  selector: 'hx-badge',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { '[attr.data-tone]': 'tone()', '[style.--badge-color]': 'color()' },
  template: `@if (dot()) { <span class="dot"></span> }<ng-content />`,
  styles: [`
    :host { display: inline-flex; align-items: center; gap: 5px; height: 21px; padding: 0 8px;
            border-radius: var(--radius-full); font-size: 11.5px; font-weight: 500; white-space: nowrap;
            background: var(--surface-2); color: var(--text-2); }
    :host([data-tone=accent]) { background: var(--accent-soft); color: var(--accent); }
    :host([data-tone=success]) { background: var(--success-soft); color: var(--success); }
    :host([data-tone=danger]) { background: var(--danger-soft); color: var(--danger); }
    :host([data-tone=warning]) { background: var(--warning-soft); color: var(--warning); }
    :host([data-tone=info]) { background: var(--info-soft); color: var(--info); }
    .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--badge-color, currentColor); }
  `],
})
export class BadgeComponent {
  tone = input<Tone>('neutral');
  dot = input(false, { transform: booleanAttribute });
  color = input<string | null>(null);
}

/** <hx-spinner [size]="20" /> */
@Component({
  selector: 'hx-spinner',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { '[style.width.px]': 'size()', '[style.height.px]': 'size()', role: 'status', 'aria-label': 'Caricamento' },
  template: ``,
  styles: [`:host { display: inline-block; border: 2px solid var(--border-strong); border-top-color: var(--accent);
                    border-radius: 50%; animation: hx-spin .8s linear infinite; }`],
})
export class SpinnerComponent { size = input(18); }

/** <hx-empty icon="calendar" title="Niente qui">testo + azioni</hx-empty> */
@Component({
  selector: 'hx-empty',
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="ic"><hx-icon [name]="icon()" [size]="26" /></div>
    <div class="t">{{ title() }}</div>
    <div class="d"><ng-content /></div>`,
  styles: [`
    :host { display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center;
            gap: 6px; padding: 40px 20px; color: var(--text-3); }
    .ic { width: 52px; height: 52px; border-radius: 50%; background: var(--surface-2); display: grid; place-items: center; color: var(--text-2); margin-bottom: 6px; }
    .t { font-weight: 600; color: var(--text); font-size: 15px; }
    .d { font-size: 13.5px; max-width: 380px; display: flex; flex-direction: column; align-items: center; gap: 10px; }
  `],
})
export class EmptyStateComponent {
  icon = input('info');
  title = input('');
}

/** <hx-field label="Titolo" hint="..." [error]="err"> <input class="hx-input"> </hx-field> */
@Component({
  selector: 'hx-field',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (label()) { <label class="l">{{ label() }} @if (required()) { <span class="req">*</span> }</label> }
    <ng-content />
    @if (error()) { <div class="e">{{ error() }}</div> } @else if (hint()) { <div class="h">{{ hint() }}</div> }`,
  styles: [`
    :host { display: flex; flex-direction: column; gap: 5px; min-width: 0; }
    .l { font-size: 12.5px; font-weight: 500; color: var(--text-2); }
    .req { color: var(--danger); }
    .h { font-size: 12px; color: var(--text-3); }
    .e { font-size: 12px; color: var(--danger); }
  `],
})
export class FieldComponent {
  label = input('');
  hint = input<string | null | undefined>('');
  error = input<string | null | undefined>('');
  required = input(false, { transform: booleanAttribute });
}

/** <hx-page-header title="Calendario" subtitle="..."> <button hx-btn>…</button> </hx-page-header> */
@Component({
  selector: 'hx-page-header',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="txt">
      <h1>{{ title() }}</h1>
      @if (subtitle()) { <p>{{ subtitle() }}</p> }
    </div>
    <div class="actions"><ng-content /></div>`,
  styles: [`
    :host { display: flex; align-items: center; gap: 12px; padding: 18px 24px 14px; border-bottom: 1px solid var(--border); flex-shrink: 0; }
    .txt { flex: 1; min-width: 0; }
    h1 { font-family: var(--font-serif); font-weight: 500; font-size: 22px; color: var(--text); line-height: 1.2; }
    p { font-size: 13px; color: var(--text-3); margin-top: 2px; }
    .actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    @media (max-width: 720px) { :host { padding: 12px 14px 10px; flex-wrap: wrap; } h1 { font-size: 19px; } }
  `],
})
export class PageHeaderComponent {
  title = input('');
  subtitle = input('');
}

/** <hx-toggle [(checked)]="x" label="Attivo" /> */
@Component({
  selector: 'hx-toggle',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <button type="button" role="switch" class="sw" [class.on]="checked()" [attr.aria-checked]="checked()"
            [disabled]="disabled()" (click)="checked.set(!checked()); changed.emit(checked())"><span></span></button>
    @if (label()) { <span class="lbl" (click)="!disabled() && checked.set(!checked())">{{ label() }}</span> }`,
  styles: [`
    :host { display: inline-flex; align-items: center; gap: 8px; }
    .sw { width: 34px; height: 20px; border-radius: 10px; background: var(--surface-3); position: relative; transition: background var(--dur) var(--ease); flex-shrink: 0; }
    .sw span { position: absolute; top: 2px; left: 2px; width: 16px; height: 16px; border-radius: 50%; background: var(--surface); box-shadow: var(--shadow-1); transition: transform var(--dur) var(--ease); }
    .sw.on { background: var(--accent); }
    .sw.on span { transform: translateX(14px); }
    .sw:disabled { opacity: .5; }
    .lbl { font-size: 14px; color: var(--text-2); cursor: pointer; user-select: none; }
  `],
})
export class ToggleComponent {
  checked = model(false);
  label = input('');
  disabled = input(false);
  changed = output<boolean>();
}

export interface SegmentOption<T = string> { value: T; label?: string; icon?: string; title?: string; }

/** <hx-segmented [options]="opts" [(value)]="view" /> */
@Component({
  selector: 'hx-segmented',
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @for (o of options(); track o.value) {
      <button type="button" [class.on]="o.value === value()" [attr.title]="o.title || o.label"
              (click)="value.set(o.value); changed.emit(o.value)">
        @if (o.icon) { <hx-icon [name]="o.icon" [size]="15" /> }
        @if (o.label) { <span>{{ o.label }}</span> }
      </button>
    }`,
  styles: [`
    :host { display: inline-flex; background: var(--surface-2); border-radius: var(--radius-md); padding: 3px; gap: 2px; }
    button { height: 28px; padding: 0 11px; border-radius: calc(var(--radius-md) - 3px); font-size: 13px; color: var(--text-2);
             display: inline-flex; align-items: center; gap: 5px; transition: background var(--dur-fast), color var(--dur-fast); }
    button:hover { color: var(--text); }
    button.on { background: var(--surface); color: var(--text); box-shadow: var(--shadow-1); font-weight: 500; }
  `],
})
export class SegmentedComponent<T = string> {
  options = input<SegmentOption<T>[]>([]);
  value = model<T | null>(null);
  changed = output<T>();
}
