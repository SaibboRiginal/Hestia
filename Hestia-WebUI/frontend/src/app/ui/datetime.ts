import { ChangeDetectionStrategy, Component, ElementRef, booleanAttribute, computed, input, model, viewChild } from '@angular/core';
import { IconComponent } from './icon.component';

/**
 * Date / time fields that never depend on the browser or OS locale (Italian format, 24h only).
 * Native <input type="datetime-local"> follows the OS → AM/PM on en-US Windows: don't use it.
 *
 *   <hx-date [(value)]="'2026-10-04'" />            value: 'YYYY-MM-DD' ('' = empty)
 *   <hx-time [(value)]="'09:30'" />                 value: 'HH:mm'
 *   <hx-datetime [(value)]="'2026-10-04T09:30'" />  value: 'YYYY-MM-DDTHH:mm' (same as datetime-local)
 */
const pad = (n: number) => String(n).padStart(2, '0');

export function parseItDate(text: string): string | null {
  const t = text.trim();
  if (!t) return '';
  let m = t.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);                    // ISO
  const [y, mo, d] = m ? [+m[1], +m[2], +m[3]]
    : ((m = t.match(/^(\d{1,2})[/.\-\s](\d{1,2})(?:[/.\-\s](\d{2,4}))?$/))
        ? [m[3] ? (m[3].length === 2 ? 2000 + +m[3] : +m[3]) : new Date().getFullYear(), +m[2], +m[1]] : [0, 0, 0]);
  if (!y) return null;
  const dt = new Date(y, mo - 1, d);
  return dt.getMonth() === mo - 1 && dt.getDate() === d ? `${y}-${pad(mo)}-${pad(d)}` : null;
}

export function parseTime24(text: string): string | null {
  const t = text.trim().replace(/[.,h ]/g, ':');
  if (!t) return '';
  const m = t.match(/^(\d{1,2})(?::?(\d{2}))?$/);
  if (!m) return null;
  const h = +m[1], mi = m[2] ? +m[2] : 0;
  return h < 24 && mi < 60 ? `${pad(h)}:${pad(mi)}` : null;
}

const isoToIt = (v: string) => { const m = v.match(/^(\d{4})-(\d{2})-(\d{2})$/); return m ? `${m[3]}/${m[2]}/${m[1]}` : ''; };
const TIMES = Array.from({ length: 96 }, (_, i) => `${pad(Math.floor(i / 4))}:${pad((i % 4) * 15)}`);

@Component({
  selector: 'hx-date',
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <input #txt class="hx-input" [class.bad]="bad" [value]="shown()" placeholder="gg/mm/aaaa" [disabled]="disabled()"
           (change)="commit(txt.value)" (keydown.enter)="commit(txt.value)" [attr.aria-label]="label() || 'Data'" />
    <button type="button" class="pick" (click)="openPicker()" [disabled]="disabled()" aria-label="Scegli data"><hx-icon name="calendar" [size]="15" /></button>
    <input #native type="date" class="native" tabindex="-1" aria-hidden="true" [value]="value()" (change)="value.set(native.value)" />`,
  styles: [`
    :host { position: relative; display: block; }
    .hx-input { padding-right: 34px; font-variant-numeric: tabular-nums; }
    .hx-input.bad { border-color: var(--danger); }
    .pick { position: absolute; right: 4px; top: 50%; transform: translateY(-50%); width: 28px; height: 28px; display: grid; place-items: center;
            border-radius: var(--radius-sm); color: var(--text-3); }
    .pick:hover { background: var(--surface-2); color: var(--text); }
    .native { position: absolute; right: 0; bottom: 0; width: 1px; height: 1px; opacity: 0; pointer-events: none; }
  `],
})
export class DateFieldComponent {
  value = model('');
  label = input('');
  disabled = input(false, { transform: booleanAttribute });
  bad = false;
  shown = computed(() => isoToIt(this.value()));
  private native = viewChild<ElementRef<HTMLInputElement>>('native');
  commit(text: string) {
    const v = parseItDate(text);
    this.bad = v === null;
    if (v !== null) this.value.set(v);
  }
  openPicker() { const el = this.native()?.nativeElement as HTMLInputElement & { showPicker?: () => void }; el?.showPicker?.(); }
}

let seq = 0;

@Component({
  selector: 'hx-time',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <input #txt class="hx-input" [class.bad]="bad" [value]="value()" placeholder="hh:mm" maxlength="5" [disabled]="disabled()"
           [attr.list]="listId" (change)="commit(txt.value)" (keydown.enter)="commit(txt.value)" [attr.aria-label]="label() || 'Ora'" />
    <datalist [id]="listId">@for (t of times; track t) { <option [value]="t"></option> }</datalist>`,
  styles: [`:host { display: block; } .hx-input { font-variant-numeric: tabular-nums; } .hx-input.bad { border-color: var(--danger); }`],
})
export class TimeFieldComponent {
  value = model('');
  label = input('');
  disabled = input(false, { transform: booleanAttribute });
  readonly times = TIMES;
  readonly listId = `hx-time-${++seq}`;
  bad = false;
  commit(text: string) {
    const v = parseTime24(text);
    this.bad = v === null;
    if (v !== null) this.value.set(v);
  }
}

@Component({
  selector: 'hx-datetime',
  imports: [DateFieldComponent, TimeFieldComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <hx-date [value]="date()" (valueChange)="set($event, time())" [disabled]="disabled()" />
    <hx-time [value]="time()" (valueChange)="set(date(), $event)" [disabled]="disabled()" />`,
  styles: [`:host { display: grid; grid-template-columns: minmax(0, 1fr) 92px; gap: 6px; }`],
})
export class DateTimeFieldComponent {
  value = model('');
  disabled = input(false, { transform: booleanAttribute });
  date = computed(() => this.value().slice(0, 10));
  time = computed(() => this.value().slice(11, 16));
  set(d: string, t: string) { this.value.set(d ? `${d}T${t || '00:00'}` : ''); }
}
