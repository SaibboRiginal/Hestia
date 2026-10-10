import { ChangeDetectionStrategy, Component, ElementRef, computed, inject, input, signal } from '@angular/core';
import { BadgeComponent, ButtonComponent, IconComponent, PopoverComponent, SpinnerComponent } from '../../ui';
import { fmt } from '../calendar/date-utils';
import { CentralSettingsApi, HistoryRow, SettingItem } from './central-settings.api';
import { CentralSettingsStore, isModified } from './central-settings.store';
import { SettingControlComponent } from './setting-control.component';

/** Human text for a stored value (option label, sì/no…). */
export function showValue(item: SettingItem, v: unknown): string {
  if (v === null || v === undefined) return 'predefinito';
  if (item.type === 'bool') return v ? 'sì' : 'no';
  const opt = item.options?.find(o => JSON.stringify(o.value) === JSON.stringify(v));
  if (opt) return opt.label;
  if (Array.isArray(v)) return v.join(', ') || '—';
  if (typeof v === 'object') return JSON.stringify(v);
  const s = String(v);
  return item.unit ? `${s} ${item.unit}` : s;
}

const ACTORS: Record<string, string> = {
  webui: 'tu (WebUI)', telegram: 'tu (Telegram)', user: 'tu', oracle: 'proposta di Hestia', athena: 'proposta di Athena',
};

/**
 * <hx-setting [item] /> — one central setting: label, help, state badges, the control and a
 * popover with the last changes (undo) and "ripristina predefinito". Changes go through the store.
 */
@Component({
  selector: 'hx-setting',
  imports: [SettingControlComponent, BadgeComponent, ButtonComponent, IconComponent, PopoverComponent, SpinnerComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @let it = item();
    <div class="meta">
      <div class="lbl">
        <span>{{ it.label }}</span>
        @if (modified()) { <hx-badge tone="accent" dot title="Diverso dal predefinito">modificato</hx-badge> }
        @if (it.status === 'restart_required') {
          <hx-badge tone="warning" dot title="Il valore salvato vale dal prossimo riavvio del modulo">riavvio necessario</hx-badge>
        } @else if (it.status === 'offline') {
          <hx-badge tone="danger" dot title="Il modulo non risponde: il valore è salvato e verrà usato quando torna">modulo offline</hx-badge>
        } @else if (it.apply === 'restart') {
          <hx-badge title="Cambiarlo richiede il riavvio del modulo">al riavvio</hx-badge>
        }
        @if (it.scope === 'user') { <hx-badge tone="info" title="Personale: profilo → client → sessione">personale</hx-badge> }
      </div>
      @if (!enabled()) { <div class="dep"><hx-icon name="info" [size]="13" /> {{ store.dependencyLabel(it) }}</div> }
      @else if (it.help) { <div class="help">{{ it.help }}</div> }
    </div>
    <div class="ctl">
      <hx-setting-control [item]="it" [disabled]="!enabled() || store.saving() === it.key" (commit)="store.set(it, $event)" />
    </div>
    <div class="act">
      @if (store.saving() === it.key) { <hx-spinner [size]="14" /> }
      <button hx-btn variant="ghost" size="sm" icon="clock" iconOnly aria-label="Cronologia e ripristino"
              title="Cronologia e ripristino" (click)="openHistory($event)"></button>
    </div>
    <hx-popover [open]="historyOpen()" [anchor]="anchor()" [width]="330" (closed)="historyOpen.set(false)">
      <div class="pop">
        <div class="ph">{{ it.label }}</div>
        <div class="pk">{{ it.key }} · predefinito: {{ show(it.default) }}</div>
        @if (loadingHistory()) { <div class="row-c"><hx-spinner [size]="16" /></div> }
        @else if (!history().length) { <div class="empty">Nessuna modifica registrata.</div> }
        @else {
          <ol>
            @for (h of history(); track $index) {
              <li>
                <span class="hv">{{ show(h.old_value) }} → <b>{{ show(h.new_value) }}</b></span>
                <span class="hm">{{ when(h.created_at) }} · {{ actor(h.actor) }}@if (h.reason) { · {{ h.reason }} }</span>
              </li>
            }
          </ol>
        }
        <div class="pa">
          <button hx-btn size="sm" icon="undo" [disabled]="!history().length" (click)="undo()">Annulla ultima</button>
          <button hx-btn size="sm" variant="ghost" icon="refresh" [disabled]="!modified()" (click)="reset()">Ripristina predefinito</button>
        </div>
      </div>
    </hx-popover>`,
  styles: [`
    :host { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 300px) 34px; gap: 6px 16px; align-items: center;
            padding: 12px 4px; border-bottom: 1px solid var(--border); }
    :host(:last-child) { border-bottom: 0; }
    .lbl { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; font-size: 14px; color: var(--text); font-weight: 500; }
    .help, .dep { font-size: 12.5px; color: var(--text-3); margin-top: 3px; line-height: 1.4; }
    .dep { display: flex; align-items: center; gap: 5px; }
    :host(.dim) .meta { opacity: .6; }
    .act { display: flex; align-items: center; justify-content: flex-end; gap: 4px; }
    @media (max-width: 700px) {
      :host { grid-template-columns: minmax(0, 1fr) 34px; }
      .ctl { grid-column: 1 / 2; grid-row: 2; }
      .act { grid-column: 2; grid-row: 1; }
    }
    .pop { padding: 12px 14px; display: flex; flex-direction: column; gap: 8px; }
    .ph { font-weight: 600; font-size: 14px; }
    .pk { font-size: 11.5px; color: var(--text-3); font-family: var(--font-mono); word-break: break-all; }
    .empty { font-size: 13px; color: var(--text-3); }
    .row-c { display: flex; justify-content: center; padding: 8px; }
    ol { list-style: none; display: flex; flex-direction: column; gap: 8px; max-height: 240px; overflow: auto; }
    li { display: flex; flex-direction: column; gap: 2px; font-size: 13px; }
    .hv { color: var(--text-2); word-break: break-word; }
    .hv b { color: var(--text); font-weight: 600; }
    .hm { font-size: 11.5px; color: var(--text-3); }
    .pa { display: flex; flex-wrap: wrap; gap: 6px; padding-top: 4px; border-top: 1px solid var(--border); }
  `],
  host: { '[class.dim]': '!enabled()' },
})
export class SettingRowComponent {
  readonly store = inject(CentralSettingsStore);
  private api = inject(CentralSettingsApi);
  private el = inject(ElementRef<HTMLElement>);

  item = input.required<SettingItem>();
  readonly enabled = computed(() => this.store.enabled(this.item()));
  readonly modified = computed(() => isModified(this.item()));

  readonly historyOpen = signal(false);
  readonly anchor = signal<{ x: number; y: number; width: number; height: number } | null>(null);
  readonly history = signal<HistoryRow[]>([]);
  readonly loadingHistory = signal(false);

  show(v: unknown) { return showValue(this.item(), v); }
  actor(a?: string | null) { return a ? (ACTORS[a] ?? a) : '—'; }
  when(t?: string | null) {
    if (!t) return '';
    const d = new Date(t);
    return isNaN(d.getTime()) ? '' : `${fmt.dayMonth(d)} ${fmt.time(d)}`;
  }

  async openHistory(e: MouseEvent) {
    e.stopPropagation();
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    this.anchor.set({ x: r.left, y: r.top, width: r.width, height: r.height });
    this.historyOpen.set(true);
    this.loadingHistory.set(true);
    try { this.history.set(await this.api.history(this.item().key)); } catch { this.history.set([]); }
    finally { this.loadingHistory.set(false); }
  }

  async undo() { this.historyOpen.set(false); await this.store.undo(this.item()); }
  async reset() { this.historyOpen.set(false); await this.store.reset(this.item()); }
}
