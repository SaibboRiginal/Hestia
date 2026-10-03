/** Overlays: modal, popover, dropdown menu, toast host + service, confirm/choice dialog. */
import {
  ChangeDetectionStrategy, Component, ElementRef, HostListener, Injectable, computed, effect,
  inject, input, output, signal, viewChild,
} from '@angular/core';
import { IconComponent } from './icon.component';
import { ButtonComponent, ButtonVariant } from './button.component';

// ── Modal ──────────────────────────────────────────────────────────────────

/**
 * <hx-modal [open]="show()" title="Nuovo evento" size="md" (closed)="show.set(false)">
 *   body…
 *   <ng-container footer> <button hx-btn>…</button> </ng-container>
 * </hx-modal>
 * ESC and backdrop click emit (closed). Sizes: sm 400 · md 560 · lg 760 · xl 960.
 */
@Component({
  selector: 'hx-modal',
  imports: [ButtonComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (open()) {
      <div class="backdrop hx-fade-in" (mousedown)="onBackdrop($event)">
        <div class="dlg" role="dialog" aria-modal="true" [attr.aria-label]="title()" [attr.data-size]="size()" #dlg tabindex="-1">
          @if (title()) {
            <header>
              <h2>{{ title() }}</h2>
              <button hx-btn variant="ghost" size="sm" icon="x" iconOnly aria-label="Chiudi" (click)="closed.emit()"></button>
            </header>
          }
          <div class="body"><ng-content /></div>
          <footer><ng-content select="[footer]" /></footer>
        </div>
      </div>
    }`,
  styles: [`
    .backdrop { position: fixed; inset: 0; background: var(--overlay); z-index: 1000; display: grid; place-items: center; padding: 16px; }
    .dlg { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-xl); box-shadow: var(--shadow-3);
           width: 100%; max-height: calc(100vh - 32px); display: flex; flex-direction: column; outline: none; }
    .dlg[data-size=sm] { max-width: 400px; } .dlg[data-size=md] { max-width: 560px; }
    .dlg[data-size=lg] { max-width: 760px; } .dlg[data-size=xl] { max-width: 960px; }
    header { display: flex; align-items: center; gap: 8px; padding: 16px 18px 6px 22px; }
    h2 { flex: 1; font-family: var(--font-serif); font-weight: 500; font-size: 19px; }
    .body { padding: 10px 22px 6px; overflow: auto; }
    footer { display: flex; justify-content: flex-end; gap: 8px; padding: 12px 18px 16px; }
    footer:empty { display: none; }
  `],
})
export class ModalComponent {
  open = input(false);
  title = input('');
  size = input<'sm' | 'md' | 'lg' | 'xl'>('md');
  dismissable = input(true);
  closed = output<void>();
  private dlg = viewChild<ElementRef<HTMLElement>>('dlg');

  constructor() {
    effect(() => { if (this.open()) queueMicrotask(() => this.dlg()?.nativeElement.focus()); });
  }

  @HostListener('document:keydown.escape')
  onEsc() { if (this.open() && this.dismissable()) this.closed.emit(); }

  onBackdrop(e: MouseEvent) {
    if (this.dismissable() && e.target === e.currentTarget) this.closed.emit();
  }
}

// ── Popover ────────────────────────────────────────────────────────────────

export type Anchor = DOMRect | { x: number; y: number; width?: number; height?: number } | null;

/**
 * Floating panel next to an anchor rect (e.g. an element's getBoundingClientRect()).
 * <hx-popover [open]="!!sel()" [anchor]="selRect()" (closed)="sel.set(null)" [width]="340">…</hx-popover>
 * Auto-flips to stay in the viewport; closes on ESC / outside click.
 */
@Component({
  selector: 'hx-popover',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (open() && anchor()) {
      <div class="pop hx-fade-in" #pop [style.left.px]="pos().x" [style.top.px]="pos().y" [style.width.px]="width()"
           (mousedown)="$event.stopPropagation()">
        <ng-content />
      </div>
    }`,
  styles: [`
    .pop { position: fixed; z-index: 900; background: var(--surface); border: 1px solid var(--border);
           border-radius: var(--radius-lg); box-shadow: var(--shadow-3); max-height: calc(100vh - 24px); overflow: auto; }
  `],
})
export class PopoverComponent {
  open = input(false);
  anchor = input<Anchor>(null);
  width = input(320);
  closed = output<void>();
  private pop = viewChild<ElementRef<HTMLElement>>('pop');
  private measured = signal(240);

  pos = computed(() => {
    const a = this.anchor();
    if (!a) return { x: 0, y: 0 };
    const w = this.width(), h = this.measured(), m = 8;
    const ax = a.x, ay = a.y, aw = a.width ?? 0, ah = a.height ?? 0;
    let x = ax + aw + m;                                  // right of anchor
    if (x + w > window.innerWidth - m) x = ax - w - m;    // flip left
    if (x < m) x = Math.min(Math.max(m, ax), window.innerWidth - w - m);
    let y = ay;
    if (y + h > window.innerHeight - m) y = Math.max(m, window.innerHeight - h - m);
    if (x === ax && aw === 0) y = ay + ah + m;
    return { x, y };
  });

  constructor() {
    effect(() => {
      if (this.open() && this.anchor()) {
        requestAnimationFrame(() => {
          const el = this.pop()?.nativeElement;
          if (el) this.measured.set(el.offsetHeight);
        });
      }
    });
  }

  @HostListener('document:mousedown')
  onOutside() { if (this.open()) this.closed.emit(); }

  @HostListener('document:keydown.escape')
  onEsc() { if (this.open()) this.closed.emit(); }
}

// ── Dropdown menu ──────────────────────────────────────────────────────────

export interface MenuItem { id: string; label: string; icon?: string; danger?: boolean; disabled?: boolean; divider?: boolean; }

/**
 * <hx-menu [items]="items" (select)="onPick($event)">
 *   <button hx-btn variant="ghost" icon="more" iconOnly trigger></button>
 * </hx-menu>
 */
@Component({
  selector: 'hx-menu',
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <span class="trg" (click)="toggle($event)"><ng-content select="[trigger]" /></span>
    @if (openState()) {
      <div class="menu hx-fade-in" [class.up]="up()" [class.left]="align() === 'left'" (mousedown)="$event.stopPropagation()">
        @for (it of items(); track it.id) {
          @if (it.divider) { <div class="div"></div> }
          @else {
            <button type="button" [disabled]="it.disabled" [class.danger]="it.danger" (click)="pick(it)">
              @if (it.icon) { <hx-icon [name]="it.icon" [size]="16" /> }
              <span>{{ it.label }}</span>
            </button>
          }
        }
      </div>
    }`,
  styles: [`
    :host { position: relative; display: inline-flex; }
    .trg { display: inline-flex; }
    .menu { position: absolute; top: calc(100% + 4px); right: 0; min-width: 190px; z-index: 950; padding: 5px;
            background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-md); box-shadow: var(--shadow-2); }
    .menu.left { right: auto; left: 0; }
    .menu.up { top: auto; bottom: calc(100% + 4px); }
    button { width: 100%; display: flex; align-items: center; gap: 9px; padding: 7px 9px; border-radius: var(--radius-sm);
             font-size: 13.5px; color: var(--text); text-align: left; }
    button:hover:not(:disabled) { background: var(--surface-2); }
    button:disabled { opacity: .45; cursor: default; }
    button.danger { color: var(--danger); }
    .div { height: 1px; background: var(--border); margin: 4px 2px; }
  `],
})
export class MenuComponent {
  items = input<MenuItem[]>([]);
  align = input<'left' | 'right'>('right');
  up = input(false);
  select = output<string>();
  openState = signal(false);

  toggle(e: MouseEvent) { e.stopPropagation(); this.openState.update(v => !v); }
  pick(it: MenuItem) { this.openState.set(false); this.select.emit(it.id); }

  @HostListener('document:mousedown')
  close() { this.openState.set(false); }
}

// ── Toasts ─────────────────────────────────────────────────────────────────

export interface Toast { id: number; text: string; tone: 'info' | 'success' | 'danger' | 'warning'; action?: { label: string; run: () => void }; }

/** inject(ToastService).show('Salvato', 'success') — rendered by <hx-toast-host> (once, in the shell). */
@Injectable({ providedIn: 'root' })
export class ToastService {
  readonly toasts = signal<Toast[]>([]);
  private seq = 0;

  show(text: string, tone: Toast['tone'] = 'info', action?: Toast['action'], ms = 4500): void {
    const id = ++this.seq;
    this.toasts.update(t => [...t, { id, text, tone, action }].slice(-5));
    setTimeout(() => this.dismiss(id), ms);
  }
  success(text: string) { this.show(text, 'success'); }
  error(text: string) { this.show(text, 'danger', undefined, 7000); }
  dismiss(id: number) { this.toasts.update(t => t.filter(x => x.id !== id)); }
}

@Component({
  selector: 'hx-toast-host',
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @for (t of svc.toasts(); track t.id) {
      <div class="toast hx-fade-in" [attr.data-tone]="t.tone" role="status">
        <hx-icon [name]="t.tone === 'success' ? 'check' : t.tone === 'danger' ? 'alert' : 'info'" [size]="16" />
        <span class="txt">{{ t.text }}</span>
        @if (t.action) { <button class="act" (click)="t.action.run(); svc.dismiss(t.id)">{{ t.action.label }}</button> }
        <button class="x" (click)="svc.dismiss(t.id)" aria-label="Chiudi"><hx-icon name="x" [size]="14" /></button>
      </div>
    }`,
  styles: [`
    :host { position: fixed; bottom: 18px; left: 50%; transform: translateX(-50%); z-index: 1100; display: flex; flex-direction: column; gap: 8px; align-items: center; pointer-events: none; }
    .toast { pointer-events: auto; display: flex; align-items: center; gap: 9px; min-width: 260px; max-width: min(520px, calc(100vw - 32px));
             padding: 9px 10px 9px 13px; border-radius: var(--radius-md); background: var(--text); color: var(--bg); box-shadow: var(--shadow-3); font-size: 13.5px; }
    .toast[data-tone=success] hx-icon { color: var(--success); }
    .toast[data-tone=danger] hx-icon { color: var(--danger); }
    .toast[data-tone=warning] hx-icon { color: var(--warning); }
    .txt { flex: 1; }
    .act { color: var(--accent); font-weight: 600; font-size: 13px; padding: 2px 6px; }
    .x { color: inherit; opacity: .6; display: inline-flex; padding: 2px; }
  `],
})
export class ToastHostComponent { svc = inject(ToastService); }

// ── Confirm / choice dialog ────────────────────────────────────────────────

export interface ChoiceOption<T = string> { value: T; label: string; variant?: ButtonVariant; }
interface ChoiceRequest { title: string; message: string; options: ChoiceOption<unknown>[]; resolve: (v: unknown) => void; }

/**
 * const ok = await inject(DialogService).confirm('Annullare la regola?', 'Non verrà più eseguita.');
 * const which = await dialogs.choose('Spostare…', '', [{value:'one',label:'Solo questa'},{value:'all',label:'Tutta la serie'}]);
 * Resolves null on cancel. Rendered by <hx-dialog-host> (once, in the shell).
 */
@Injectable({ providedIn: 'root' })
export class DialogService {
  readonly current = signal<ChoiceRequest | null>(null);

  choose<T>(title: string, message: string, options: ChoiceOption<T>[]): Promise<T | null> {
    return new Promise(resolve => this.current.set({ title, message, options, resolve: resolve as (v: unknown) => void }));
  }

  async confirm(title: string, message = '', confirmLabel = 'Conferma', danger = false): Promise<boolean> {
    const r = await this.choose(title, message, [
      { value: 'no', label: 'Annulla', variant: 'ghost' },
      { value: 'yes', label: confirmLabel, variant: danger ? 'danger' : 'primary' },
    ]);
    return r === 'yes';
  }

  settle(value: unknown) {
    const c = this.current();
    this.current.set(null);
    c?.resolve(value);
  }
}

@Component({
  selector: 'hx-dialog-host',
  imports: [ModalComponent, ButtonComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (svc.current(); as c) {
      <hx-modal [open]="true" [title]="c.title" size="sm" (closed)="svc.settle(null)">
        @if (c.message) { <p class="msg">{{ c.message }}</p> }
        <ng-container footer>
          @for (o of c.options; track $index) {
            <button hx-btn [variant]="o.variant || 'secondary'" (click)="svc.settle(o.value)">{{ o.label }}</button>
          }
        </ng-container>
      </hx-modal>
    }`,
  styles: [`.msg { color: var(--text-2); font-size: 14px; padding-bottom: 6px; }`],
})
export class DialogHostComponent { svc = inject(DialogService); }
