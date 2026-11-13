import { ChangeDetectionStrategy, Component, HostListener, computed, effect, inject, signal, untracked } from '@angular/core';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { DatePipe } from '@angular/common';
import { APP_MODULES } from '../app.modules';
import { AuthService } from '../services/auth.service';
import { SignalRService } from '../services/signalr.service';
import { SessionService } from '../services/session.service';
import { SettingsService } from '../services/settings.service';
import { ButtonComponent, DialogHostComponent, IconComponent, ResizeHandleComponent, ToastHostComponent, ToastService, savedWidth } from '../ui';
import { AssistantDrawerComponent } from '../features/assistant/assistant-drawer.component';
import { AssistantService } from '../services/assistant.service';
import { NotificationsService } from '../services/notifications.service';
import { PresenceService, PresenceState, ago, reasonLabel } from '../services/presence.service';
import { PluginsService } from '../features/plugins/plugins.service';
import { PluginPage } from '../features/plugins/plugins.types';
import { CommandPaletteComponent } from '../features/plugins/command-palette.component';
import { MetisService } from '../services/metis.service';
import { AppearanceService } from '../services/appearance.service';
import { AppearanceLayerComponent } from './appearance-layer.component';
import { LiveOverlayComponent } from './live-overlay.component';
import { QuickBubbleComponent } from './quick-bubble.component';
import { ChatHistoryComponent } from '../features/chat/chat-history.component';
import { ChatSummary, ChatsService, TAG_CSS } from '../services/chats.service';
import { ChatService } from '../services/chat.service';
import { LiveVoiceService } from '../services/live-voice.service';

interface NavEntry { id: string; label: string; icon: string; link: string; online: boolean; child: boolean; parent: string; badge: number;
  /** Set by the view: has sub-pages · they are shown · the page on screen is one of them. */
  kids?: boolean; open?: boolean; within?: boolean; }
interface NavSection { key: 'pinned' | 'app' | 'dashboards' | 'modules' | 'system'; label: string; items: NavEntry[]; }
interface Crumb { label: string; link?: string; }
/** Pages of the app that belong to «Sistema» next to the system modules' own pages. */
const SYSTEM_PAGES = [
  { id: 'app.sistema', label: 'Panoramica', icon: 'grid', link: '/sistema' },
  { id: 'app.aggiornamenti', label: 'Aggiornamenti', icon: 'refresh', link: '/aggiornamenti' },
  { id: 'app.macchine', label: 'Macchine', icon: 'host', link: '/macchine' },
  { id: 'app.download', label: 'Download', icon: 'download', link: '/download' },
];
/** Sections whose pages show «Sezione › Pagina» above the page. */
const CRUMB_SECTIONS = ['pinned', 'dashboards', 'modules', 'system'];

/** App frame: collapsible, resizable sidebar (APP_MODULES + module pages + dashboards, arranged by the user) + routed page + global overlays.
 *  One rule for the sidebar (docs/work/2026-11-13-sidebar-e-chat): on top the bell, Chat and Cerca; then sections that
 *  all fold the same way (Generale, Fissati, Conversazioni, Dashboard, Moduli, Sistema), a module with sub-pages folds
 *  too; the page on screen is marked with its parent, its section opens by itself and «Sezione › Pagina» is written
 *  above the page. «Scrivi qui» and «Parla» live in the bubble (layout/quick-bubble), not in the sidebar. */
@Component({
  selector: 'app-shell',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, DatePipe, ButtonComponent, IconComponent, ResizeHandleComponent, ToastHostComponent, DialogHostComponent, AssistantDrawerComponent, CommandPaletteComponent, AppearanceLayerComponent, LiveOverlayComponent, ChatHistoryComponent, QuickBubbleComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="shell" [class.collapsed]="collapsed()" [class.mobile-open]="mobileOpen()">
      <aside class="nav hx-glass" [style.width.px]="collapsed() ? null : navWidth()">
        @if (!collapsed()) { <hx-resize [(width)]="navWidth" [min]="200" [max]="420" [def]="248" key="nav" /> }
        <div class="brand">
          <svg class="logo" viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
            <path d="M12 2.5 21.5 12 12 21.5 2.5 12Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" />
            <path d="M12 7.2 16.8 12 12 16.8 7.2 12Z" fill="currentColor" />
          </svg>
          <span class="name">Hestia</span>
          @if (!plugins.online()) { <span class="offline" title="Sei offline: i moduli mostrano gli ultimi dati salvati"><hx-icon name="offline" [size]="14" />offline</span> }
          <a class="icon-btn bell" routerLink="/notifications" (click)="mobileOpen.set(false)" [attr.aria-label]="bellLabel()" [attr.title]="bellLabel()">
            <hx-icon name="bell" [size]="17" />
            @if (notifications.badge(); as n) { <b class="dot">{{ n > 99 ? '99+' : n }}</b> }
          </a>
          <button class="icon-btn collapse" (click)="toggleCollapse()" [attr.aria-label]="collapsed() ? 'Espandi' : 'Comprimi'">
            <hx-icon name="sidebar" [size]="17" />
          </button>
        </div>
        <div class="quick">
          <a class="item" routerLink="/chat" routerLinkActive="active" (click)="mobileOpen.set(false)" title="Chat">
            <hx-icon name="chat" [size]="18" /><span>Chat</span>
          </a>
          <button class="item" (click)="openSearch(); mobileOpen.set(false)" title="Cerca azioni, pagine, impostazioni (Ctrl+K)">
            <hx-icon name="search" [size]="18" /><span>Cerca</span><kbd>Ctrl K</kbd>
          </button>
        </div>
        <!-- One scroll area between the fixed top and bottom (A5): sections, collapsible, with pinned entries first. -->
        <div class="scroll">
          @for (sec of view(); track sec.key) {
            @if (sec.key === 'dashboards') {
              <button type="button" class="sect" (click)="plugins.toggleNavSection('chats')" [attr.aria-expanded]="!isSectionClosed('chats')">
                <span>Conversazioni</span><hx-icon [name]="isSectionClosed('chats') ? 'chevron-right' : 'chevron-down'" [size]="13" />
              </button>
              @if (!isSectionClosed('chats') || collapsed()) {
                <nav>
                  @for (c of chats.recent(); track c.session_id) {
                    @if (renaming() === c.session_id) {
                      <input #ri class="hx-input ren" [value]="c.title" aria-label="Titolo della conversazione"
                             (keydown.enter)="rename(c, ri.value)" (keydown.escape)="renaming.set('')" (blur)="rename(c, ri.value)">
                    } @else {
                      <div class="row">
                        <button class="item chat" [class.active]="c.session_id === session.sessionId() && onChat()" (click)="openChat(c.session_id)" [attr.title]="c.title">
                          <hx-icon [name]="c.pinned ? 'pin' : 'chat'" [size]="16" /><span>{{ c.title }}</span>
                          @if (c.tags.length) { <i class="tdot" [style.background]="tagCss(c.tags[0].color)"></i> }
                        </button>
                        <button type="button" class="pin" (click)="openChatMenu($event, c)" aria-haspopup="menu"
                                aria-label="Altro: rinomina, fissa, elimina" title="Altro"><hx-icon name="more" [size]="14" /></button>
                      </div>
                    }
                  }
                  <button class="item chat all" [class.active]="chats.historyOpen()" (click)="chats.historyOpen.set(!chats.historyOpen()); mobileOpen.set(false)" title="Tutte le conversazioni, con ricerca ed etichette">
                    <hx-icon name="history" [size]="16" /><span>Tutte le conversazioni</span>
                  </button>
                </nav>
              }
            }
            @if (sec.items.length) {
              <button type="button" class="sect" (click)="plugins.toggleNavSection(sec.key)"
                      [attr.aria-expanded]="!sec.closed">
                <span>{{ sec.label }}</span><hx-icon [name]="sec.closed ? 'chevron-right' : 'chevron-down'" [size]="13" />
              </button>
              @if (!sec.closed || collapsed()) {
                <nav>
                  @for (e of sec.items; track e.id) {
                    <div class="row" [class.child]="e.child" [class.dragging]="dragId() === e.id"
                         [attr.draggable]="sec.key === 'pinned' && !collapsed()"
                         (dragstart)="dragStart(e.id, sec.key)" (dragover)="dragOver($event, e.id, sec.key)"
                         (drop)="drop($event)" (dragend)="dragId.set(null)">
                      <a class="item" [class.child]="e.child" [class.off]="!e.online" [class.within]="e.within" [class.kids]="e.kids" [routerLink]="e.link" routerLinkActive="active"
                         (click)="mobileOpen.set(false)" [attr.title]="e.online ? e.label : e.label + ' (non raggiungibile)'">
                        <hx-icon [name]="e.icon" [size]="e.child ? 16 : 18" /><span>{{ e.label }}</span>
                        @if (e.badge) { <b class="count">{{ e.badge > 99 ? '99+' : e.badge }}</b> }
                      </a>
                      @if (e.kids) {
                        <button type="button" class="fold" (click)="plugins.toggleNavSection('m:' + e.id)" [attr.aria-expanded]="e.open"
                                [attr.aria-label]="(e.open ? 'Chiudi le pagine di ' : 'Apri le pagine di ') + e.label" [attr.title]="e.open ? 'Chiudi' : 'Apri'">
                          <hx-icon [name]="e.open ? 'chevron-down' : 'chevron-right'" [size]="13" /></button>
                      }
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
            <button class="item presence" [attr.data-tone]="online() ? presence.tone() : 'off'" (click)="togglePresence($event)"
                    [attr.title]="'Stato: ' + p.label + ' · ' + connLabel() + ' · ultima interazione ' + ago(p.idle_minutes)"
                    [attr.aria-expanded]="presenceOpen()">
              <span class="pdot"></span><span class="plabel">{{ online() ? p.label : connLabel() }}</span>
            </button>
            @if (presenceOpen()) {
              <div class="presence-pop" role="dialog" aria-label="Stato dell'assistente"
                   [style.left.px]="presencePos().left" [style.bottom.px]="presencePos().bottom"
                   [style.max-height.px]="presencePos().maxHeight">
                <div class="ptitle"><hx-icon [name]="presence.icon().name" [tone]="presence.icon().tone" [size]="15" />{{ p.label }}</div>
                @if (p.help) { <div class="pline">{{ p.help }}</div> }
                <div class="pline dim">Sito: {{ connLabel() }}</div>
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
        } @else {
          <!-- One status line: the connection shows here only until the assistant's state is known. -->
          <div class="conn" [attr.data-state]="signalR.connectionState()">
            <span class="dot"></span><span>{{ connLabel() }}</span>
          </div>
        }
      </aside>
      @if (chats.historyOpen()) { @defer { <hx-chat-history /> } }
      <div class="scrim" (click)="mobileOpen.set(false)"></div>
      <main>
        <button class="icon-btn burger" (click)="mobileOpen.set(true)" [attr.aria-label]="notifications.badge() ? 'Menu, ' + bellLabel() : 'Menu'">
          <hx-icon name="menu" />@if (notifications.badge(); as n) { <b class="dot">{{ n > 99 ? '99+' : n }}</b> }
        </button>
        @if (crumbs().length) {
          <nav class="crumbs" aria-label="Dove sei">
            @for (c of crumbs(); track $index) {
              @if ($index) { <hx-icon name="chevron-right" [size]="12" /> }
              @if (c.link && !$last) { <a [routerLink]="c.link">{{ c.label }}</a> } @else { <span [class.cur]="$last">{{ c.label }}</span> }
            }
          </nav>
        }
        <router-outlet />
      </main>
    </div>
    @if (chatMenu(); as m) {
      <div class="hx-ctx-scrim" (click)="chatMenu.set(null)"></div>
      <div class="hx-ctx hx-fade-in" role="menu" [style.left.px]="m.x" [style.top.px]="m.y">
        <button type="button" role="menuitem" (click)="startRename(m.chat)"><hx-icon name="edit" [size]="16" />Rinomina</button>
        <button type="button" role="menuitem" (click)="pinChat(m.chat)"><hx-icon name="pin" [size]="16" />{{ m.chat.pinned ? 'Togli da fissate' : 'Fissa in cima' }}</button>
        <button type="button" role="menuitem" class="danger" (click)="deleteChat(m.chat)"><hx-icon name="trash" [size]="16" />Elimina</button>
      </div>
    }
    <hx-quick-bubble />
    @defer (when assistant.isOpen()) { <hx-assistant /> }
    @defer (on idle) { <hx-command-palette /> }
    <hx-appearance-layer />
    @defer (when live.on) { <hx-live-overlay /> }
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
    .logo { color: var(--accent); flex-shrink: 0; }
    .quick { display: flex; flex-direction: column; gap: 2px; flex-shrink: 0; margin-bottom: 4px; }
    .item kbd { margin-left: auto; font: 10.5px var(--font-mono, monospace); color: var(--text-3); }
    .collapsed .item kbd { display: none; }
    .icon-btn { position: relative; }
    .dot { position: absolute; top: 1px; right: 0; min-width: 15px; height: 15px; padding: 0 4px; border-radius: var(--radius-full); background: var(--accent);
           color: var(--accent-contrast); font: 600 9.5px/15px var(--font-sans); text-align: center; }
    .item.within { color: var(--text); } .item.within hx-icon { color: var(--accent); }
    .item.kids { padding-right: 34px; }
    .fold { position: absolute; right: 4px; top: 50%; transform: translateY(-50%); width: 26px; height: 26px; border-radius: var(--radius-md);
            display: inline-grid; place-items: center; background: none; border: 0; color: var(--text-3); cursor: pointer; }
    .fold:hover { background: var(--surface-3); color: var(--text); }
    .row:has(.fold) .pin { right: 30px; }
    .collapsed .fold { display: none; } .collapsed .item.kids { padding-right: 10px; }
    .ren { height: 32px; font-size: 13.5px; width: 100%; }
    .crumbs { flex-shrink: 0; display: flex; flex-direction: row; align-items: center; gap: 5px; padding: 8px 24px 0; font-size: 12px; color: var(--text-3); white-space: nowrap; overflow: hidden; }
    .crumbs a { color: var(--text-3); text-decoration: none; } .crumbs a:hover { color: var(--text); text-decoration: underline; }
    .crumbs .cur { color: var(--text-2); overflow: hidden; text-overflow: ellipsis; }
    .item.chat { height: 32px; font-size: 13.5px; padding-right: 32px; } .item.chat.all { padding-right: 10px; } .item.chat span { overflow: hidden; text-overflow: ellipsis; }
    .item.chat.all { color: var(--text-3); }
    .tdot { width: 7px; height: 7px; border-radius: 50%; margin-left: auto; flex-shrink: 0; }
    .name { font-family: var(--font-serif); font-size: 19px; font-weight: 500; flex: 1; white-space: nowrap; }
    .icon-btn { width: 32px; height: 32px; border-radius: var(--radius-md); display: inline-grid; place-items: center; color: var(--text-3); }
    .icon-btn:hover { background: var(--surface-2); color: var(--text); }
    nav { display: flex; flex-direction: column; gap: 2px; }
    .brand, .nav > nav, .presence-wrap, .conn { flex-shrink: 0; }
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
    .presence[data-tone=off] .pdot { background: var(--warning); animation: hx-pulse 1.4s ease-in-out infinite; }
    .presence .plabel { overflow: hidden; text-overflow: ellipsis; }
    /* fixed: the sidebar clips its overflow (resizable/collapsible width), so the popover lives in the viewport */
    .presence-pop { position: fixed; width: min(300px, calc(100vw - 16px)); z-index: 900; padding: 12px; overflow-y: auto;
                    background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-lg, 10px);
                    box-shadow: var(--shadow-3); display: flex; flex-direction: column; gap: 4px;
                    backdrop-filter: var(--glass, none); -webkit-backdrop-filter: var(--glass, none); }
    .ptitle { font-weight: 600; font-size: 13.5px; margin-bottom: 2px; display: flex; align-items: center; gap: 6px; }
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
    main { flex: 1; min-width: 0; display: flex; flex-direction: column; position: relative; background: transparent; }
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
      .crumbs { padding: 8px 12px 0 56px; min-height: 30px; }
    }
  `],
})
export class ShellComponent {
  /** Chat has its own place on top of the sidebar. */
  readonly top = APP_MODULES.filter(m => !m.bottom && m.path !== 'chat');
  readonly bottom = APP_MODULES.filter(m => m.bottom);
  auth = inject(AuthService);
  signalR = inject(SignalRService);
  assistant = inject(AssistantService);
  notifications = inject(NotificationsService);
  presence = inject(PresenceService);
  plugins = inject(PluginsService);
  private toasts = inject(ToastService);
  private metis = inject(MetisService);
  private look = inject(AppearanceService);
  /** Module pages (client plugins): parents followed by their sub-pages. */
  readonly pluginNav = computed(() => {
    const pages = this.plugins.navPages();
    const top = pages.filter(p => !p.parent || !pages.some(x => x.module === p.module && x.local_id === p.parent));
    return top.flatMap(p => [p, ...pages.filter(c => c.parent === p.local_id && c.module === p.module)]);
  });
  /** The «Stato del sistema» dashboard opens from the Sistema page, not from a second sidebar entry. */
  readonly otherDashboards = computed(() => this.plugins.dashboards().filter(d => d.id !== 'home' && d.id !== 'sistema'));

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
    const fixed: NavEntry[] = SYSTEM_PAGES.map(x => ({ ...x, online: true, child: false, parent: '', badge: 0 }));
    const system = sys.length ? [fixed[0], ...sys, ...fixed.slice(1)] : fixed.slice(1);
    const all = new Map([...app, ...dash, ...mods, ...system].map(e => [e.id, e] as [string, NavEntry]));
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
      { key: 'app', label: 'Generale', items: rest(app) },
      { key: 'pinned', label: 'Fissati', items: pinned },
      { key: 'dashboards', label: 'Dashboard', items: rest(dash) },
      { key: 'modules', label: 'Moduli', items: rest(mods) },
      { key: 'system', label: 'Sistema', items: rest(system) },
    ];
  });

  /** Id of the sidebar entry of the page on screen: the longest link that starts the address; a page opened from
   *  an item (no entry of its own) marks its module's first page. */
  readonly activeId = computed(() => {
    const path = this.url().split(/[?#]/)[0];
    const entries = this.sections().flatMap(sec => sec.items);
    const at = (e: NavEntry) => { const l = e.link.split('?')[0]; return path === l || path.startsWith(l + '/'); };
    const hit = entries.filter(at).sort((a, b) => b.link.length - a.link.length)[0];
    if (hit) return hit.id;
    const mod = /^\/p\/([^/]+)\//.exec(path)?.[1];
    return mod ? entries.find(e => !e.child && e.link.startsWith(`/p/${mod}/`))?.id ?? '' : '';
  });

  /** What the sidebar draws: a closed section or module opens by itself while the page on screen is inside it. */
  readonly view = computed(() => {
    const active = this.activeId();
    const folded = this.plugins.navCollapsed();
    return this.sections().map(sec => {
      const parentOf = (e: NavEntry) => e.child && sec.items.some(p => p.id === e.parent) ? e.parent : '';
      const activeParent = parentOf(sec.items.find(e => e.id === active) ?? ({ child: false } as NavEntry));
      const items = sec.items.map(e => {
        const kids = sec.items.filter(c => parentOf(c) === e.id);
        const open = !folded.includes('m:' + e.id) || activeParent === e.id;
        return { ...e, kids: kids.length > 0, open, within: activeParent === e.id,
                 badge: kids.length && !open ? e.badge + kids.reduce((n, c) => n + c.badge, 0) : e.badge };
      });
      const shown = items.filter(e => { const p = parentOf(e); return !p || !!items.find(x => x.id === p)?.open; });
      return { ...sec, items: shown, closed: folded.includes(sec.key) && !sec.items.some(e => e.id === active) };
    });
  });

  /** «Sezione › Pagina» above a page of a module, a dashboard or the system (the sidebar may be closed or far away). */
  readonly crumbs = computed<Crumb[]>(() => {
    const active = this.activeId();
    for (const sec of this.sections()) {
      const e = sec.items.find(x => x.id === active);
      if (!e || !CRUMB_SECTIONS.includes(sec.key)) continue;
      const parent = e.child ? sec.items.find(x => x.id === e.parent) : undefined;
      return [{ label: sec.label }, ...(parent ? [{ label: parent.label, link: parent.link }] : []), { label: e.label }];
    }
    return [];
  });

  readonly bellLabel = computed(() => {
    const n = this.notifications.badge();
    return n ? `Notifiche: ${n} da leggere` : 'Notifiche';
  });

  /** «…» on a conversation: rename, pin, delete. Drawn outside the sidebar, which clips what overflows it. */
  chatMenu = signal<{ chat: ChatSummary; x: number; y: number } | null>(null);
  renaming = signal('');
  openChatMenu(ev: MouseEvent, chat: ChatSummary): void {
    ev.stopPropagation();
    const r = (ev.currentTarget as HTMLElement).getBoundingClientRect();
    this.chatMenu.set({ chat, x: Math.max(8, Math.min(r.left, window.innerWidth - 200)), y: Math.min(r.bottom + 4, window.innerHeight - 130) });
  }
  startRename(c: ChatSummary): void {
    this.chatMenu.set(null);
    this.renaming.set(c.session_id);
    setTimeout(() => { const el = document.querySelector<HTMLInputElement>('.nav input.ren'); el?.focus(); el?.select(); });
  }
  async rename(c: ChatSummary, title: string): Promise<void> {
    if (this.renaming() !== c.session_id) return;      // Enter then blur: once
    this.renaming.set('');
    const t = title.trim();
    if (!t || t === c.title) return;
    if (!(await this.chats.setMeta(c.session_id, { title: t })).ok) this.toasts.error('Non salvato');
  }
  async pinChat(c: ChatSummary): Promise<void> {
    this.chatMenu.set(null);
    if (!(await this.chats.setMeta(c.session_id, { pinned: !c.pinned })).ok) this.toasts.error('Non salvato');
  }
  deleteChat(c: ChatSummary): void {
    this.chatMenu.set(null);
    void this.chats.confirmRemove(c);
  }

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
  session = inject(SessionService);
  chats = inject(ChatsService);
  live = inject(LiveVoiceService);
  private chat = inject(ChatService);
  private url = signal('');
  readonly onChat = computed(() => this.url().startsWith('/chat'));
  tagCss(c: string) { return TAG_CSS[c] || TAG_CSS['gray']; }
  private settings = inject(SettingsService);
  private router = inject(Router);
  collapsed = signal(this.readCollapsed());
  /** Expanded sidebar width, dragged from its right edge (<hx-resize>), kept per browser. */
  navWidth = signal(savedWidth('nav', 248));
  mobileOpen = signal(false);
  online = computed(() => this.signalR.connectionState() === 'connected');
  connLabel = computed(() => ({ connected: 'Connesso', connecting: 'Connessione…', disconnected: 'Disconnesso' })[this.signalR.connectionState()]);
  private bootstrapped = false;

  constructor() {
    this.router.events.subscribe(() => this.url.set(this.router.url));
    // The sidebar's latest conversations follow each finished answer.
    let streaming = false;
    effect(() => {
      const now = this.chat.isStreaming();
      if (streaming && !now) untracked(() => void this.chats.refreshRecent());
      streaming = now;
    });
    effect(() => { if (this.plugins.modules().has('oracle')) untracked(() => void this.chats.refreshRecent()); });
    // The entry of the page on screen is always in sight, also when the list is long.
    effect(() => {
      if (!this.activeId()) return;
      setTimeout(() => document.querySelector('.nav .scroll a.item.active')?.scrollIntoView({ block: 'nearest' }), 150);
    });
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
    this.metis.start();
    this.look.start();
    await Promise.all([this.session.load(), this.settings.load()]);
  }

  openSearch(): void { window.dispatchEvent(new CustomEvent('hestia:palette')); }

  async openChat(id: string): Promise<void> {
    this.mobileOpen.set(false);
    await this.chats.open(id);
  }

  /** «Parla» from anywhere: same live mode as the chat page (layout/live-overlay shows it on other pages). */
  toggleLive(): void {
    if (this.live.on) { this.live.stop(); return; }
    void this.live.start().then(() => { if (this.live.error()) this.toasts.error(this.live.error()); });
  }

  /** Ctrl+J = «Scrivi qui» from anywhere; Ctrl+Shift+Space = «Parla». */
  @HostListener('document:keydown', ['$event'])
  onKey(e: KeyboardEvent) {
    if (e.key === 'Escape' && this.chatMenu()) { this.chatMenu.set(null); return; }
    if (e.key === 'Escape' && this.presenceOpen()) { this.presenceOpen.set(false); return; }
    if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.code === 'Space') { e.preventDefault(); this.toggleLive(); return; }
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
