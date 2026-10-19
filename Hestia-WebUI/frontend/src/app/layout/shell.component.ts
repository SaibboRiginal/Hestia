import { ChangeDetectionStrategy, Component, HostListener, computed, effect, inject, signal, untracked } from '@angular/core';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { DatePipe } from '@angular/common';
import { APP_MODULES } from '../app.modules';
import { AuthService } from '../services/auth.service';
import { SignalRService } from '../services/signalr.service';
import { SessionService } from '../services/session.service';
import { SettingsService } from '../services/settings.service';
import { ButtonComponent, DialogHostComponent, IconComponent, ResizeHandleComponent, ToastHostComponent, savedWidth } from '../ui';
import { AssistantDrawerComponent } from '../features/assistant/assistant-drawer.component';
import { AssistantService } from '../services/assistant.service';
import { NotificationsService } from '../services/notifications.service';
import { PresenceService, PresenceState, ago, reasonLabel } from '../services/presence.service';
import { PluginsService } from '../features/plugins/plugins.service';
import { PluginPage } from '../features/plugins/plugins.types';
import { CommandPaletteComponent } from '../features/plugins/command-palette.component';

interface NavEntry { id: string; label: string; icon: string; link: string; online: boolean; child: boolean; parent: string; badge: number; }
interface NavSection { key: 'pinned' | 'app' | 'dashboards' | 'modules' | 'system'; label: string; items: NavEntry[]; }

/** App frame: collapsible, resizable sidebar (APP_MODULES + module pages + dashboards, arranged by the user) + routed page + global overlays. */
@Component({
  selector: 'app-shell',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, DatePipe, ButtonComponent, IconComponent, ResizeHandleComponent, ToastHostComponent, DialogHostComponent, AssistantDrawerComponent, CommandPaletteComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="shell" [class.collapsed]="collapsed()" [class.mobile-open]="mobileOpen()">
      <aside class="nav" [style.width.px]="collapsed() ? null : navWidth()">
        @if (!collapsed()) { <hx-resize [(width)]="navWidth" [min]="200" [max]="420" [def]="248" key="nav" /> }
        <div class="brand">
          <span class="logo">◈</span>
          <span class="name">Hestia</span>
          @if (!plugins.online()) { <span class="offline" title="Sei offline: i moduli mostrano gli ultimi dati salvati"><hx-icon name="offline" [size]="14" />offline</span> }
          <button class="icon-btn collapse" (click)="toggleCollapse()" [attr.aria-label]="collapsed() ? 'Espandi' : 'Comprimi'">
            <hx-icon name="sidebar" [size]="17" />
          </button>
        </div>
        <button class="item ask" (click)="assistant.toggle(); mobileOpen.set(false)" title="Crea con Hestia (Ctrl+J)">
          <hx-icon name="sparkle" [size]="18" /><span>Crea con Hestia</span><kbd>Ctrl J</kbd>
        </button>
        <!-- One scroll area between the fixed top and bottom (A5): sections, collapsible, with pinned entries first. -->
        <div class="scroll">
          @for (sec of sections(); track sec.key) {
            @if (sec.items.length) {
              <button type="button" class="sect" (click)="plugins.toggleNavSection(sec.key)"
                      [attr.aria-expanded]="!isSectionClosed(sec.key)">
                <span>{{ sec.label }}</span><hx-icon [name]="isSectionClosed(sec.key) ? 'chevron-right' : 'chevron-down'" [size]="13" />
              </button>
              @if (!isSectionClosed(sec.key) || collapsed()) {
                <nav>
                  @for (e of sec.items; track e.id) {
                    <div class="row" [class.child]="e.child" [class.dragging]="dragId() === e.id"
                         [attr.draggable]="sec.key === 'pinned' && !collapsed()"
                         (dragstart)="dragStart(e.id, sec.key)" (dragover)="dragOver($event, e.id, sec.key)"
                         (drop)="drop($event)" (dragend)="dragId.set(null)">
                      <a class="item" [class.child]="e.child" [class.off]="!e.online" [routerLink]="e.link" routerLinkActive="active"
                         (click)="mobileOpen.set(false)" [attr.title]="e.online ? e.label : e.label + ' (non raggiungibile)'">
                        <hx-icon [name]="e.icon" [size]="e.child ? 16 : 18" /><span>{{ e.label }}</span>
                        @if (e.badge) { <b class="count">{{ e.badge > 99 ? '99+' : e.badge }}</b> }
                      </a>
                      <button type="button" class="pin" [class.on]="sec.key === 'pinned'" (click)="plugins.toggleNavPin(e.id)"
                              [attr.aria-label]="sec.key === 'pinned' ? 'Togli da Fissati' : 'Fissa in cima'"
                              [attr.title]="sec.key === 'pinned' ? 'Togli da Fissati' : 'Fissa in cima'">
                        <hx-icon name="pin" [size]="14" />
                      </button>
                    </div>
                  }
                </nav>
              }
            }
          }
        </div>
        <nav>
          @for (m of bottom; track m.path) {
            <a class="item" [routerLink]="'/' + m.path" routerLinkActive="active" (click)="mobileOpen.set(false)" [attr.title]="m.label">
              <hx-icon [name]="m.icon" [size]="18" /><span>{{ m.label }}</span>
            </a>
          }
          @if (!auth.local()) {
            <button class="item" (click)="logout()" title="Esci">
              <hx-icon name="logout" [size]="18" /><span>Esci</span>
            </button>
          }
        </nav>
        @if (presence.state(); as p) {
          <div class="presence-wrap">
            <button class="item presence" [attr.data-tone]="presence.tone()" (click)="togglePresence($event)"
                    [attr.title]="'Stato: ' + p.label + ' · ultima interazione ' + ago(p.idle_minutes)"
                    [attr.aria-expanded]="presenceOpen()">
              <span class="pdot"></span><span class="plabel">{{ p.label }}</span>
            </button>
            @if (presenceOpen()) {
              <div class="presence-pop" role="dialog" aria-label="Stato dell'assistente"
                   [style.left.px]="presencePos().left" [style.bottom.px]="presencePos().bottom"
                   [style.max-height.px]="presencePos().maxHeight">
                <div class="ptitle">{{ p.emoji }} {{ p.label }}</div>
                @if (p.help) { <div class="pline">{{ p.help }}</div> }
                <div class="pline dim">Ultima interazione: {{ ago(p.idle_minutes) }}{{ p.last_interaction_client ? ' (' + p.last_interaction_client + ')' : '' }}</div>
                @if (p.dnd_until) { <div class="pline">Non disturbare fino alle {{ p.dnd_until | date:'HH:mm' }}</div> }
                @for (a of p.activities; track a.key) { <div class="pline">• {{ a.label || a.key }}</div> }
                <div class="ptabs">
                  <button type="button" [class.on]="presenceTab() === 'effects'" (click)="presenceTab.set('effects')">Cosa cambia</button>
                  <button type="button" [class.on]="presenceTab() === 'history'" (click)="openPresenceHistory()">Storico</button>
                </div>
                @if (presenceTab() === 'effects') {
                  <div class="pnote">Lo stato decide cosa può fare il sistema in quel momento:</div>
                  @for (e of presence.effects(); track e) { <div class="pline">• {{ e }}</div> }
                } @else {
                  <div class="phist">
                    @for (h of presence.history() ?? []; track $index) {
                      <div class="hrow">
                        <span class="ht">{{ h.at | date:'dd/MM HH:mm' }}</span>
                        <span class="hl">{{ h.label }}@if (reasonLabel(h.reason)) {<span class="hr"> · {{ reasonLabel(h.reason) }}</span>}</span>
                      </div>
                    } @empty { <div class="pline dim">{{ presence.history() === null ? 'Carico…' : 'Nessun cambio registrato.' }}</div> }
                  </div>
                }
                <div class="pactions">
                  @if (p.base === 'dnd') {
                    <button hx-btn variant="secondary" size="sm" icon="bell" [loading]="presence.busy()" (click)="presence.dnd(false)">Disattiva</button>
                  } @else {
                    <button hx-btn variant="secondary" size="sm" icon="bell-off" [loading]="presence.busy()" (click)="presence.dnd(true)"
                            [attr.title]="dndHint(p)">Non disturbare</button>
                  }
                  <a hx-btn variant="ghost" size="sm" routerLink="/settings" (click)="presenceOpen.set(false)">Impostazioni</a>
                </div>
                @if (p.base !== 'dnd') { <div class="pnote">{{ dndHint(p) }}</div> }
              </div>
            }
          </div>
        }
        <div class="conn" [attr.data-state]="signalR.connectionState()">
          <span class="dot"></span><span>{{ connLabel() }}</span>
        </div>
      </aside>
      <div class="scrim" (click)="mobileOpen.set(false)"></div>
      <main>
        <button class="icon-btn burger" (click)="mobileOpen.set(true)" aria-label="Menu"><hx-icon name="menu" /></button>
        <router-outlet />
      </main>
    </div>
    @defer (when assistant.isOpen()) { <hx-assistant /> }
    @defer (on idle) { <hx-command-palette /> }
    <hx-toast-host />
    <hx-dialog-host />
  `,
  styles: [`
    .offline { display: inline-flex; align-items: center; gap: 4px; font-size: 11.5px; color: var(--warning, #d9a441); padding: 2px 8px; border-radius: 999px; background: var(--surface-2, transparent); border: 1px solid var(--border); }
    :host { display: block; height: 100vh; }
    .shell { display: flex; height: 100%; }
    .nav { position: relative; width: var(--nav-width); flex-shrink: 0; background: var(--bg-subtle); border-right: 1px solid var(--border);
           display: flex; flex-direction: column; padding: 10px 8px; gap: 2px; transition: width var(--dur) var(--ease); overflow: hidden; }
    .nav hx-resize { right: 0; }
    .brand { display: flex; align-items: center; gap: 9px; padding: 4px 6px 12px 8px; }
    .logo { color: var(--accent); font-size: 20px; line-height: 1; }
    .name { font-family: var(--font-serif); font-size: 19px; font-weight: 500; flex: 1; white-space: nowrap; }
    .icon-btn { width: 32px; height: 32px; border-radius: var(--radius-md); display: inline-grid; place-items: center; color: var(--text-3); }
    .icon-btn:hover { background: var(--surface-2); color: var(--text); }
    nav { display: flex; flex-direction: column; gap: 2px; }
    .brand, .item.ask, .nav > nav, .presence-wrap, .conn { flex-shrink: 0; }
    .scroll { flex: 1; min-height: 0; overflow-y: auto; overflow-x: hidden; display: flex; flex-direction: column; gap: 2px;
              margin: 0 -8px; padding: 0 8px 8px; scrollbar-width: thin; }
    .sect { display: flex; align-items: center; gap: 4px; width: 100%; background: none; border: 0; cursor: pointer; text-align: left;
            font: 600 11px var(--font-sans); color: var(--text-3); text-transform: uppercase; letter-spacing: .04em; padding: 12px 12px 4px; white-space: nowrap; }
    .sect:hover { color: var(--text-2); }
    .sect hx-icon { opacity: 0; transition: opacity var(--dur) var(--ease); }
    .sect:hover hx-icon, .sect:focus-visible hx-icon, .sect[aria-expanded=false] hx-icon { opacity: 1; }
    .collapsed .sect { visibility: hidden; height: 8px; padding: 0; pointer-events: none; }
    .row { position: relative; }
    .row.dragging { opacity: .4; }
    .pin { position: absolute; right: 4px; top: 50%; transform: translateY(-50%); width: 26px; height: 26px; border-radius: var(--radius-md);
           display: inline-grid; place-items: center; background: none; border: 0; color: var(--text-3); cursor: pointer; opacity: 0; }
    .row:hover .pin, .pin:focus-visible { opacity: 1; }
    .row:hover .item .count { visibility: hidden; }
    .pin:hover { background: var(--surface-3); color: var(--text); }
    .pin.on { color: var(--accent); }
    .collapsed .pin { display: none; }
    @media (hover: none) { .pin { opacity: .6; } .row .item .count { visibility: visible; } }
    .item.child { padding-left: 30px; height: 32px; font-size: 13.5px; }
    .collapsed .item.child { padding-left: 10px; }
    .item.off { opacity: .55; }
    .item { display: flex; align-items: center; gap: 11px; height: 36px; padding: 0 10px; border-radius: var(--radius-md);
            color: var(--text-2); font-size: 14px; white-space: nowrap; text-decoration: none !important; width: 100%; text-align: left; }
    .item:hover { background: var(--surface-2); color: var(--text); }
    .item.active { background: var(--surface-3); color: var(--text); font-weight: 500; }
    .item hx-icon { color: var(--text-3); }
    .item.active hx-icon { color: var(--accent); }
    .item.ask { margin-bottom: 6px; border: 1px solid var(--border); background: var(--surface); }
    .item.ask hx-icon { color: var(--accent); }
    .item.ask kbd { margin-left: auto; font: 10.5px var(--font-mono, monospace); color: var(--text-3); }
    .collapsed .item.ask kbd { display: none; }
    .item { position: relative; }
    .count { margin-left: auto; min-width: 18px; height: 18px; padding: 0 5px; border-radius: var(--radius-full); background: var(--accent);
             color: var(--accent-contrast); font: 600 11px/18px var(--font-sans); text-align: center; }
    .collapsed .count { position: absolute; top: 3px; left: 22px; margin: 0; min-width: 15px; height: 15px; line-height: 15px; font-size: 9.5px; padding: 0 3px; }
    .conn { display: flex; align-items: center; gap: 7px; font-size: 11.5px; color: var(--text-3); padding: 8px 12px 2px; white-space: nowrap; }
    .conn .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--warning); flex-shrink: 0; }
    .conn[data-state=connected] .dot { background: var(--success); }
    .conn[data-state=disconnected] .dot { background: var(--danger); }
    .presence-wrap { position: relative; }
    .presence { gap: 9px; font-size: 12.5px; height: 30px; }
    .presence .pdot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; margin: 0 4px; background: var(--text-3); }
    .presence[data-tone=awake] .pdot { background: var(--success); }
    .presence[data-tone=idle] .pdot { background: var(--warning); }
    .presence[data-tone=sleep] .pdot { background: var(--accent); }
    .presence[data-tone=dnd] .pdot { background: var(--danger); }
    .presence .plabel { overflow: hidden; text-overflow: ellipsis; }
    /* fixed: the sidebar clips its overflow (resizable/collapsible width), so the popover lives in the viewport */
    .presence-pop { position: fixed; width: min(300px, calc(100vw - 16px)); z-index: 900; padding: 12px; overflow-y: auto;
                    background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-lg, 10px);
                    box-shadow: var(--shadow-3); display: flex; flex-direction: column; gap: 4px; }
    .ptitle { font-weight: 600; font-size: 13.5px; margin-bottom: 2px; }
    .pline { font-size: 12.5px; color: var(--text-2); }
    .pline.dim { color: var(--text-3); }
    .pactions { display: flex; gap: 6px; margin-top: 8px; flex-wrap: wrap; }
    .pnote { font-size: 11.5px; color: var(--text-3); line-height: 1.4; }
    .ptabs { display: flex; gap: 4px; margin: 6px 0 2px; border-bottom: 1px solid var(--border); }
    .ptabs button { background: none; border: 0; border-bottom: 2px solid transparent; padding: 4px 6px; font: inherit;
                    font-size: 12px; color: var(--text-2); cursor: pointer; margin-bottom: -1px; }
    .ptabs button.on { color: var(--text); border-bottom-color: var(--accent); }
    .phist { max-height: 200px; overflow-y: auto; display: flex; flex-direction: column; gap: 3px; }
    .hrow { display: flex; gap: 8px; font-size: 12px; }
    .ht { color: var(--text-3); flex-shrink: 0; font-variant-numeric: tabular-nums; }
    .hl { color: var(--text-2); }
    .hr { color: var(--text-3); }
    .collapsed .presence .plabel { display: none; }
    .collapsed .nav { width: var(--nav-width-collapsed); }
    .collapsed .name, .collapsed .item span, .collapsed .conn span:last-child { display: none; }
    .collapsed .brand { flex-direction: column; padding-left: 0; padding-right: 0; }
    main { flex: 1; min-width: 0; display: flex; flex-direction: column; position: relative; background: var(--bg); }
    .burger { display: none; position: absolute; top: 12px; left: 10px; z-index: 5; }
    .scrim { display: none; }
    @media (max-width: 860px) {
      .nav { position: fixed; inset: 0 auto 0 0; z-index: 800; transform: translateX(-100%); transition: transform var(--dur) var(--ease); width: var(--nav-width) !important; box-shadow: var(--shadow-3); }
      .collapsed .name, .collapsed .item span, .collapsed .conn span:last-child { display: initial; }
      .collapsed .count { position: static; margin-left: auto; min-width: 18px; height: 18px; line-height: 18px; font-size: 11px; padding: 0 5px; }
      .collapse { display: none; }
      .mobile-open .nav { transform: none; }

      .mobile-open .scrim { display: block; position: fixed; inset: 0; background: var(--overlay); z-index: 790; }
      .burger { display: inline-grid; }
    }
  `],
})
export class ShellComponent {
  readonly top = APP_MODULES.filter(m => !m.bottom);
  readonly bottom = APP_MODULES.filter(m => m.bottom);
  auth = inject(AuthService);
  signalR = inject(SignalRService);
  assistant = inject(AssistantService);
  notifications = inject(NotificationsService);
  presence = inject(PresenceService);
  plugins = inject(PluginsService);
  /** Module pages (client plugins): parents followed by their sub-pages. */
  readonly pluginNav = computed(() => {
    const pages = this.plugins.navPages();
    const top = pages.filter(p => !p.parent || !pages.some(x => x.module === p.module && x.local_id === p.parent));
    return top.flatMap(p => [p, ...pages.filter(c => c.parent === p.local_id && c.module === p.module)]);
  });
  readonly otherDashboards = computed(() => this.plugins.dashboards().filter(d => d.id !== 'home'));

  /** Every sidebar entry by section; pinned ones move to «Fissati» (in the user's order) and leave their section. */
  readonly sections = computed<NavSection[]>(() => {
    const kinds = this.plugins.modules();
    const badges = this.plugins.badges();
    const app: NavEntry[] = this.top.map(m => ({ id: `app.${m.path}`, label: m.label, icon: m.icon, link: '/' + m.path, online: true,
      child: false, parent: '', badge: 0 }));
    const dash: NavEntry[] = this.otherDashboards().map(d => ({ id: `dash.${d.id}`, label: d.title, icon: d.icon || 'grid', link: '/d/' + d.id,
      online: true, child: false, parent: '', badge: 0 }));
    const page = (p: PluginPage): NavEntry => ({ id: p.id, label: p.label, icon: p.icon || 'puzzle', link: this.plugins.link(p.module, p.local_id),
      online: p.online, child: !!p.parent, parent: p.parent ? `${p.module}.${p.parent}` : '', badge: badges[p.id] ?? 0 });
    const nav = this.pluginNav();
    const mods = nav.filter(p => kinds.get(p.module)?.kind !== 'core').map(page);
    const sys = nav.filter(p => kinds.get(p.module)?.kind === 'core').map(page);
    const all = new Map([...app, ...dash, ...mods, ...sys].map(e => [e.id, e] as [string, NavEntry]));
    const pinnedIds = this.plugins.navPinned().filter(id => all.has(id));
    const taken = new Set(pinnedIds);
    // A pinned parent brings its (unpinned) sub-pages; a sub-page pinned alone is shown as a normal entry.
    const pinned: NavEntry[] = pinnedIds.flatMap(id => {
      const e = all.get(id)!;
      const kids = [...all.values()].filter(c => c.parent === id && !taken.has(c.id));
      kids.forEach(c => taken.add(c.id));
      return [{ ...e, child: false }, ...kids];
    });
    const rest = (list: NavEntry[]) => list.filter(e => !taken.has(e.id));
    return [
      { key: 'pinned', label: 'Fissati', items: pinned },
      { key: 'app', label: 'Generale', items: rest(app) },
      { key: 'dashboards', label: 'Dashboard', items: rest(dash) },
      { key: 'modules', label: 'Moduli', items: rest(mods) },
      { key: 'system', label: 'Sistema', items: rest(sys) },
    ];
  });

  isSectionClosed(key: string): boolean { return this.plugins.navCollapsed().includes(key); }

  /** Drag to reorder inside «Fissati» (native drag and drop; the order is saved on drop). */
  dragId = signal<string | null>(null);
  private dragOrder: string[] | null = null;
  dragStart(id: string, section: string): void {
    if (section !== 'pinned') return;
    this.dragId.set(id);
    this.dragOrder = [...this.plugins.navPinned()];
  }
  dragOver(ev: DragEvent, overId: string, section: string): void {
    const id = this.dragId();
    if (!id || section !== 'pinned' || !this.dragOrder) return;
    ev.preventDefault();
    const order = this.dragOrder;
    const from = order.indexOf(id), to = order.indexOf(overId);
    if (from < 0 || to < 0 || from === to) return;
    order.splice(to, 0, order.splice(from, 1)[0]);
    this.plugins.navPinned.set([...order]);
  }
  drop(ev: DragEvent): void {
    if (!this.dragId() || !this.dragOrder) return;
    ev.preventDefault();
    void this.plugins.setNavPinned(this.dragOrder);
    this.dragOrder = null;
    this.dragId.set(null);
  }
  presenceOpen = signal(false);
  presencePos = signal({ left: 8, bottom: 8, maxHeight: 480 });

  /** Opens the state popover above its button, in viewport coordinates (never clipped by the sidebar). */
  togglePresence(ev: MouseEvent): void {
    if (this.presenceOpen()) { this.presenceOpen.set(false); return; }
    const r = (ev.currentTarget as HTMLElement).getBoundingClientRect();
    const width = Math.min(300, window.innerWidth - 16);
    this.presencePos.set({
      left: Math.max(8, Math.min(r.left, window.innerWidth - width - 8)),
      bottom: window.innerHeight - r.top + 6,
      maxHeight: Math.max(160, r.top - 14),
    });
    this.presenceOpen.set(true);
  }

  @HostListener('window:resize')
  closePresenceOnResize(): void { if (this.presenceOpen()) this.presenceOpen.set(false); }
  presenceTab = signal<'effects' | 'history'>('effects');
  reasonLabel = reasonLabel;

  openPresenceHistory(): void {
    this.presenceTab.set('history');
    void this.presence.loadHistory();
  }

  dndHint(p: PresenceState): string {
    const m = p.dnd_minutes ?? 120;
    const d = m % 60 === 0 ? `${m / 60} ${m === 60 ? 'ora' : 'ore'}` : `${m} min`;
    return `«Non disturbare»: per ${d} ti arrivano solo le notifiche urgenti; le altre le ricevi in un riepilogo quando finisce.`;
  }
  readonly ago = ago;
  private session = inject(SessionService);
  private settings = inject(SettingsService);
  private router = inject(Router);
  collapsed = signal(this.readCollapsed());
  /** Expanded sidebar width, dragged from its right edge (<hx-resize>), kept per browser. */
  navWidth = signal(savedWidth('nav', 248));
  mobileOpen = signal(false);
  connLabel = computed(() => ({ connected: 'Connesso', connecting: 'Connessione…', disconnected: 'Disconnesso' })[this.signalR.connectionState()]);
  private bootstrapped = false;

  constructor() {
    // Connect whenever authenticated (URL token or login form); reset on logout.
    effect(() => {
      const authed = this.auth.isAuthenticated();
      untracked(() => {
        if (authed && !this.bootstrapped) { this.bootstrapped = true; void this.bootstrap(); }
        if (!authed) this.bootstrapped = false;
      });
    });
  }

  private async bootstrap() {
    if (this.signalR.connectionState() !== 'connected') await this.signalR.connect();
    this.notifications.start();
    this.presence.start();
    this.plugins.start();
    await Promise.all([this.session.load(), this.settings.load()]);
  }

  /** "Crea con Hestia" from anywhere. */
  @HostListener('document:keydown', ['$event'])
  onKey(e: KeyboardEvent) {
    if (e.key === 'Escape' && this.presenceOpen()) { this.presenceOpen.set(false); return; }
    if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === 'j') {
      e.preventDefault();
      this.assistant.toggle();
    }
  }

  toggleCollapse() {
    this.collapsed.update(v => !v);
    try { localStorage.setItem('hestia_nav_collapsed', this.collapsed() ? '1' : '0'); } catch { /* */ }
  }

  logout() {
    this.auth.logout();
    void this.signalR.disconnect();
    this.router.navigate(['/login']);
  }

  private readCollapsed(): boolean {
    try { return localStorage.getItem('hestia_nav_collapsed') === '1'; } catch { return false; }
  }
}
