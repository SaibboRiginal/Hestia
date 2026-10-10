import { ChangeDetectionStrategy, Component, OnDestroy, OnInit, computed, inject } from '@angular/core';
import { ButtonVariant, MenuItem, UI } from '../../ui';
import {
  HestiaNotification, NotificationFilter, NotificationsService, ToastMode, clientLabel,
} from '../../services/notifications.service';

interface DayGroup { label: string; items: HestiaNotification[]; }

const SOURCE_LABELS: Record<string, string> = {
  themis: 'Impostazioni', hephaestus: 'Sviluppo', chronos: 'Agenda', argus: 'Diagnosi', athena: 'Athena',
  scout: 'Scout', hecate: 'Account', system: 'Sistema', service: 'Sistema', real_estate: 'Scout', settings: 'Impostazioni',
};
const LEVEL_ICON: Record<string, string> = { info: 'bell', success: 'check', warning: 'alert', error: 'alert' };

/** Notifiche: Hermes inbox, shared by every client (read on Telegram = read here). */
@Component({
  selector: 'app-notifications-page',
  imports: [...UI],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <hx-page-header title="Notifiche" [subtitle]="subtitle()">
      @if (svc.counts().unread) {
        <button hx-btn variant="ghost" size="sm" icon="check" (click)="svc.markAllSeen()">Segna tutte lette</button>
      }
      <hx-menu [items]="toastMenu()" (select)="setToast($event)">
        <button trigger hx-btn variant="ghost" size="sm" icon="settings" iconOnly title="Avvisi a comparsa"></button>
      </hx-menu>
    </hx-page-header>

    <div class="toolbar">
      <hx-segmented [options]="filters()" [value]="svc.filter()" (changed)="setFilter($event)" />
      <select class="hx-select src" [value]="svc.source()" (change)="setSource($any($event.target).value)">
        <option value="">Tutti i moduli</option>
        @for (s of sourceOptions(); track s) { <option [value]="s">{{ sourceLabel(s) }}</option> }
      </select>
      <hx-toggle [checked]="svc.showOtherClients()" (changed)="svc.showOtherClients.set($event)" label="Anche da altri client" />
    </div>

    <div class="body">
      @if (svc.loading() && !svc.items().length) {
        <div class="center"><hx-spinner /></div>
      } @else if (!groups().length) {
        <hx-empty icon="bell" [title]="emptyTitle()" />
      } @else {
        @for (g of groups(); track g.label) {
          <h3 class="day">{{ g.label }}</h3>
          @for (n of g.items; track n.id) {
            <article class="ntf hx-fade-in" [class.unread]="!n.read" [attr.data-level]="n.level">
              <div class="ico"><hx-icon [name]="levelIcon(n.level)" [size]="16" /></div>
              <div class="main">
                <div class="meta">
                  <span class="src">{{ sourceLabel(n.source) }}</span>
                  @if (n.other_client && n.origin) { <hx-badge tone="neutral">da {{ clientLabel(n.origin.client) }}</hx-badge> }
                  <span class="time">{{ time(n.created_at) }}</span>
                  @if (!n.read) { <span class="dot" title="Da leggere"></span> }
                </div>
                @if (n.title) { <div class="title">{{ n.title }}</div> }
                <div class="msg hx-prose" [innerHTML]="n.message"></div>
                @if (n.pending && n.actions.length) {
                  <div class="actions">
                    @for (a of n.actions; track a.id) {
                      <button hx-btn size="sm" [variant]="variant(a.style)" [loading]="svc.busy() === n.id"
                              [disabled]="svc.busy() === n.id" (click)="svc.answer(n, a)">{{ a.label }}</button>
                    }
                  </div>
                } @else if (n.answer && (n.state === 'answered' || n.state === 'expired')) {
                  <div class="outcome" [attr.data-status]="n.answer.status">
                    <hx-icon [name]="n.state === 'expired' ? 'clock' : 'check'" [size]="14" />
                    <span>{{ outcome(n) }}</span>
                  </div>
                }
                @if (n.seen && n.seen.by !== 'webui' && n.state === 'seen') {
                  <div class="seen">Vista su {{ clientLabel(n.seen.by) }}</div>
                }
              </div>
            </article>
          }
        }
        @if (svc.hasMore()) {
          <div class="center"><button hx-btn variant="secondary" size="sm" [loading]="svc.loading()" (click)="svc.load(true)">Carica altre</button></div>
        }
      }
    </div>
  `,
  styles: [`
    :host { display: flex; flex-direction: column; flex: 1; min-height: 0; }
    .toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 10px 14px; padding: 0 24px 12px; border-bottom: 1px solid var(--border); }
    .src { width: auto; min-width: 150px; }
    .body { flex: 1; overflow: auto; padding: 8px 24px 24px; max-width: 860px; width: 100%; }
    .center { display: flex; justify-content: center; padding: 24px; }
    .day { font: 500 12px var(--font-sans); color: var(--text-3); text-transform: uppercase; letter-spacing: .04em; margin: 18px 0 8px; }
    .ntf { display: flex; gap: 12px; padding: 12px 14px; border: 1px solid var(--border); border-radius: var(--radius-lg);
           background: var(--surface); margin-bottom: 8px; }
    .ntf.unread { border-color: var(--border-strong); box-shadow: var(--shadow-1); }
    .ico { width: 30px; height: 30px; border-radius: 50%; display: grid; place-items: center; flex-shrink: 0;
           background: var(--surface-2); color: var(--text-3); }
    .ntf[data-level=warning] .ico { background: var(--warning-soft); color: var(--warning); }
    .ntf[data-level=error] .ico { background: var(--danger-soft); color: var(--danger); }
    .ntf[data-level=success] .ico { background: var(--success-soft); color: var(--success); }
    .main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 4px; }
    .meta { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--text-3); }
    .meta .src { font-weight: 600; color: var(--text-2); }
    .meta .time { margin-left: auto; }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--accent); }
    .title { font-weight: 600; font-size: 14px; }
    .msg { font-size: 14px; color: var(--text); white-space: pre-line; overflow-wrap: anywhere; }
    .actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 6px; }
    .outcome { display: inline-flex; align-items: center; gap: 6px; font-size: 12.5px; color: var(--success); margin-top: 4px; }
    .outcome[data-status=expired], .outcome[data-status=error] { color: var(--text-3); }
    .seen { font-size: 12px; color: var(--text-3); }
    @media (max-width: 860px) {
      hx-page-header { padding-left: 56px; }
      .toolbar { padding: 0 16px 12px; }
      .body { padding: 8px 16px 24px; }
    }
  `],
})
export class NotificationsPageComponent implements OnInit, OnDestroy {
  svc = inject(NotificationsService);
  clientLabel = clientLabel;

  filters = computed(() => {
    const c = this.svc.counts();
    return [
      { value: 'unread' as NotificationFilter, label: c.unread ? `Da leggere · ${c.unread}` : 'Da leggere' },
      { value: 'pending' as NotificationFilter, label: c.pending ? `Da rispondere · ${c.pending}` : 'Da rispondere' },
      { value: 'all' as NotificationFilter, label: 'Tutte' },
    ];
  });
  subtitle = computed(() => {
    const c = this.svc.counts();
    if (!c.unread && !c.pending) return 'Tutto letto';
    return [c.unread ? `${c.unread} da leggere` : '', c.pending ? `${c.pending} da rispondere` : ''].filter(Boolean).join(' · ');
  });
  emptyTitle = computed(() => ({ unread: 'Nessuna notifica da leggere', pending: 'Niente in attesa di risposta', all: 'Nessuna notifica' })[this.svc.filter()]);
  sourceOptions = computed(() => {
    const list = this.svc.sources();
    const current = this.svc.source();
    return current && !list.includes(current) ? [current, ...list] : list;
  });
  toastMenu = computed<MenuItem[]>(() => {
    const m = this.svc.toastMode();
    const icon = (v: ToastMode) => (m === v ? 'check' : 'minus');
    return [
      { id: 'all', icon: icon('all'), label: 'Avvisi a comparsa per tutte' },
      { id: 'important', icon: icon('important'), label: 'Solo importanti e da rispondere' },
      { id: 'none', icon: icon('none'), label: 'Nessun avviso a comparsa' },
    ];
  });
  groups = computed<DayGroup[]>(() => {
    const out: DayGroup[] = [];
    for (const n of this.svc.visible()) {
      const label = dayLabel(n.created_at);
      const last = out.at(-1);
      if (last && last.label === label) last.items.push(n); else out.push({ label, items: [n] });
    }
    return out;
  });

  private seenTimer: ReturnType<typeof setTimeout> | null = null;

  ngOnInit() { this.svc.pageOpen.set(true); void this.reload(); }
  ngOnDestroy() { this.svc.pageOpen.set(false); if (this.seenTimer) clearTimeout(this.seenTimer); }

  setFilter(f: NotificationFilter) { this.svc.filter.set(f); void this.reload(); }
  setSource(s: string) { this.svc.source.set(s); void this.reload(); }

  /** Shown on the page in a visible tab = seen (on every client). */
  private async reload() {
    await this.svc.refresh();
    if (this.seenTimer) clearTimeout(this.seenTimer);
    this.seenTimer = setTimeout(() => {
      if (document.visibilityState !== 'visible') return;
      for (const n of this.svc.visible()) if (!n.read) void this.svc.markSeen(n);
    }, 1500);
  }
  setToast(id: string) { this.svc.setToastMode(id as ToastMode); }

  sourceLabel(s: string) { return SOURCE_LABELS[s] || (s ? s.charAt(0).toUpperCase() + s.slice(1) : 'Hestia'); }
  levelIcon(l: string) { return LEVEL_ICON[l] || 'bell'; }
  variant(style: string): ButtonVariant { return style === 'primary' ? 'primary' : style === 'danger' ? 'danger' : 'secondary'; }
  time(iso: string) { return new Date(iso).toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit', hour12: false }); }
  outcome(n: HestiaNotification): string {
    const a = n.answer || {};
    if (n.state === 'expired' || a.status === 'expired') return 'Scaduta';
    const parts = [a.outcome_text || a.label || 'Gestita'];
    if (a.by && a.by !== 'webui' && CLIENT_NAMES.has(a.by)) parts.push(`da ${clientLabel(a.by)}`);
    if (a.at) parts.push(this.time(a.at));
    return parts.join(' · ');
  }
}

const CLIENT_NAMES = new Set(['telegram', 'webui']);

function dayLabel(iso: string): string {
  const d = new Date(iso);
  const today = new Date();
  const yesterday = new Date(); yesterday.setDate(today.getDate() - 1);
  const same = (a: Date, b: Date) => a.toDateString() === b.toDateString();
  if (same(d, today)) return 'Oggi';
  if (same(d, yesterday)) return 'Ieri';
  return d.toLocaleDateString('it-IT', { weekday: 'long', day: 'numeric', month: 'long' });
}
