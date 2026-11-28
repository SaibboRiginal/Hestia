import { ChangeDetectionStrategy, Component, HostListener, computed, effect, inject, signal, untracked } from '@angular/core';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { DatePipe, NgTemplateOutlet } from '@angular/common';
import { AuthService } from '../services/auth.service';
import { SignalRService } from '../services/signalr.service';
import { SessionService } from '../services/session.service';
import { SettingsService } from '../services/settings.service';
import { ButtonComponent, DialogHostComponent, IconComponent, LogoComponent, ResizeHandleComponent, ToastHostComponent, ToastService, savedWidth } from '../ui';
import { AssistantDrawerComponent } from '../features/assistant/assistant-drawer.component';
import { AssistantService } from '../services/assistant.service';
import { NotificationsService } from '../services/notifications.service';
import { PresenceService, PresenceState, ago, reasonLabel } from '../services/presence.service';
import { PluginsService } from '../features/plugins/plugins.service';
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
import { NavGroup, NavLink, NavService } from './nav.service';
import { assistantName, tr, TrPipe } from '../core/i18n';

interface RailButton { g: NavGroup; label: string; icon: string; }

/**
 * App frame (docs/work/2026-11-27-webui-rethink, piece 1): an icon rail that is always there (Today, Chat, Agenda,
 * Spaces, the assistant, the pinned pages; Search, Notifications, Settings and the assistant's state at the bottom),
 * a context panel next to it that lists what fits where you are (spaces, conversations, the agenda's or the
 * assistant's pages, Settings and the system pages), resizable and closable, and the routed page. Sub-pages are tabs
 * of their page (plugin-page), never list entries. On a phone the rail becomes a bottom bar and the panel a drawer.
 * «Write here» and «Talk» live in the bubble (layout/quick-bubble).
 */
@Component({
  selector: 'app-shell',
  imports: [TrPipe, NgTemplateOutlet, RouterOutlet, RouterLink, RouterLinkActive, DatePipe, ButtonComponent, IconComponent, LogoComponent, ResizeHandleComponent, ToastHostComponent, DialogHostComponent, AssistantDrawerComponent, CommandPaletteComponent, AppearanceLayerComponent, LiveOverlayComponent, ChatHistoryComponent, QuickBubbleComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="shell" [class.panel-closed]="panelClosed()" [class.mobile-open]="mobileOpen()">
      <nav class="rail hx-glass" [attr.aria-label]="'Main menu' | tr">
        <a class="logo" routerLink="/home" [title]="name" [attr.aria-label]="name"><hx-logo [size]="30" /></a>
        @for (b of railTop(); track b.g) {
          <a class="rb" [routerLink]="nav.linkOf(b.g)" [class.on]="nav.group() === b.g" [attr.aria-current]="nav.group() === b.g ? 'page' : null"
             (click)="openPanel()" [title]="b.label"><hx-icon [name]="b.icon" [size]="20" /><span>{{ b.label }}</span></a>
        }
        @if (nav.pins().length) {
          <div class="sep"></div>
          @for (p of nav.pins(); track p.id) {
            <a class="rb pinned" [routerLink]="p.link" routerLinkActive="on" [title]="p.label">
              <span class="tile" [style.--h]="p.color"><hx-icon [name]="p.icon" [size]="16" /></span><span>{{ p.label }}</span>
              @if (p.badge) { <b class="dot">{{ p.badge > 99 ? '99+' : p.badge }}</b> }
            </a>
          }
        }
        <div class="grow"></div>
        @if (!plugins.online()) { <span class="rb off" [title]="'You are offline: the modules show the last saved data' | tr"><hx-icon name="offline" [size]="18" /><span>{{ "offline" | tr }}</span></span> }
        <button class="rb" (click)="openSearch()" [title]="'Search actions, pages, settings (Ctrl+K)' | tr"><hx-icon name="search" [size]="20" /><span>{{ "Search" | tr }}</span></button>
        <a class="rb" [routerLink]="nav.linkOf('notifications')" [class.on]="nav.group() === 'notifications'" [attr.aria-label]="bellLabel()" [title]="bellLabel()">
          <hx-icon name="bell" [size]="20" /><span>{{ "Notices" | tr }}</span>
          @if (notifications.badge(); as n) { <b class="dot">{{ n > 99 ? '99+' : n }}</b> }
        </a>
        <a class="rb" routerLink="/settings" [class.on]="nav.group() === 'settings'" [title]="'Settings' | tr"><hx-icon name="settings" [size]="20" /><span>{{ "Settings" | tr }}</span></a>
        @if (presence.state(); as p) {
          <div class="presence-wrap">
            <button class="presence" [attr.data-tone]="online() ? presence.tone() : 'off'" (click)="togglePresence($event)"
                    [attr.title]="('Status:' | tr) + ' ' + p.label + ' · ' + connLabel() + (' · last interaction ' | tr) + ago(p.idle_minutes)"
                    [attr.aria-expanded]="presenceOpen()">
              <span class="pdot"></span><span class="plabel">{{ online() ? p.label : connLabel() }}</span>
            </button>
            @if (presenceOpen()) {
              <div class="presence-pop" role="dialog"  [attr.aria-label]="'Assistant status' | tr"
                   [style.left.px]="presencePos().left" [style.bottom.px]="presencePos().bottom"
                   [style.max-height.px]="presencePos().maxHeight">
                <div class="ptitle"><hx-icon [name]="presence.icon().name" [tone]="presence.icon().tone" [size]="15" />{{ p.label }}</div>
                @if (p.help) { <div class="pline">{{ p.help }}</div> }
                <div class="pline dim">{{ 'Site:' | tr }} {{ connLabel() }}</div>
                <div class="pline dim">{{ "Last interaction:" | tr }} {{ ago(p.idle_minutes) }}{{ p.last_interaction_client ? ' (' + p.last_interaction_client + ')' : '' }}</div>
                @if (p.dnd_until) { <div class="pline">{{ "Do not disturb until" | tr }} {{ p.dnd_until | date:'HH:mm' }}</div> }
                @for (a of p.activities; track a.key) { <div class="pline">• {{ a.label || a.key }}</div> }
                <div class="ptabs">
                  <button type="button" [class.on]="presenceTab() === 'effects'" (click)="presenceTab.set('effects')">{{ "What changes" | tr }}</button>
                  <button type="button" [class.on]="presenceTab() === 'history'" (click)="openPresenceHistory()">{{ "History" | tr }}</button>
                </div>
                @if (presenceTab() === 'effects') {
                  <div class="pnote">{{ "The state decides what the system can do at that moment:" | tr }}</div>
                  @for (e of presence.effects(); track e) { <div class="pline">• {{ e }}</div> }
                } @else {
                  <div class="phist">
                    @for (h of presence.history() ?? []; track $index) {
                      <div class="hrow">
                        <span class="ht">{{ h.at | date:'dd/MM HH:mm' }}</span>
                        <span class="hl">{{ h.label }}@if (reasonLabel(h.reason)) {<span class="hr"> · {{ reasonLabel(h.reason) }}</span>}</span>
                      </div>
                    } @empty { <div class="pline dim">{{ presence.history() === null ? ('Loading…' | tr) : ('No change recorded.' | tr) }}</div> }
                  </div>
                }
                <div class="pactions">
                  @if (p.base === 'dnd') {
                    <button hx-btn variant="secondary" size="sm" icon="bell" [loading]="presence.busy()" (click)="presence.dnd(false)">{{ "alt::Turn off" | tr }}</button>
                  } @else {
                    <button hx-btn variant="secondary" size="sm" icon="bell-off" [loading]="presence.busy()" (click)="presence.dnd(true)"
                            [attr.title]="dndHint(p)">{{ "Do not disturb" | tr }}</button>
                  }
                  <a hx-btn variant="ghost" size="sm" routerLink="/settings" (click)="presenceOpen.set(false)">{{ "Settings" | tr }}</a>
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
      </nav>
      <aside class="panel hx-glass" [style.width.px]="navWidth()" [attr.aria-label]="groupLabel()">
        <hx-resize [(width)]="navWidth" [min]="200" [max]="380" [def]="236" key="panel" />
        <div class="p-head">
          <span class="p-title">{{ groupLabel() }}</span>
          <button class="icon-btn" (click)="togglePanel()" [attr.aria-label]="'Close the panel' | tr" [title]="'Close the panel' | tr"><hx-icon name="sidebar" [size]="17" /></button>
        </div>
        @switch (nav.group()) {
          @case ('chat') {
            <a hx-btn variant="primary" size="sm" icon="plus" class="new-chat" routerLink="/chat" (click)="newChat()">{{ "New conversation" | tr }}</a>
            <div class="p-scroll">
              @for (c of chats.recent(); track c.session_id) {
                @if (renaming() === c.session_id) {
                  <input #ri class="hx-input ren" [value]="c.title" [attr.aria-label]="'Conversation title' | tr"
                         (keydown.enter)="rename(c, ri.value)" (keydown.escape)="renaming.set('')" (blur)="rename(c, ri.value)">
                } @else {
                  <div class="row">
                    <button class="item" [class.active]="c.session_id === session.sessionId()" (click)="openChat(c.session_id)" [attr.title]="c.title">
                      <hx-icon [name]="c.pinned ? 'pin' : 'chat'" [size]="16" /><span>{{ c.title }}</span>
                      @if (c.tags.length) { <i class="tdot" [style.background]="tagCss(c.tags[0].color)"></i> }
                    </button>
                    <button type="button" class="more" (click)="openChatMenu($event, c)" aria-haspopup="menu"
                            [attr.aria-label]="'More: rename, pin, delete' | tr" [title]="'Other' | tr"><hx-icon name="more" [size]="14" /></button>
                  </div>
                }
              } @empty { <p class="p-empty">{{ "Your conversations will appear here." | tr }}</p> }
              <button class="item dim" [class.active]="chats.historyOpen()" (click)="chats.historyOpen.set(!chats.historyOpen()); mobileOpen.set(false)" [title]="'All conversations, with search and labels' | tr">
                <hx-icon name="history" [size]="16" /><span>{{ "All conversations" | tr }}</span>
              </button>
            </div>
          }
          @case ('today') {
            <div class="p-scroll">
              @for (l of todayLinks(); track l.id) {
                <a class="item" [routerLink]="l.link" routerLinkActive="active" [routerLinkActiveOptions]="{ exact: true }" (click)="mobileOpen.set(false)"><hx-icon [name]="l.icon" [size]="17" /><span>{{ l.label }}</span></a>
              }
              @if (nav.spaces().length) {
                <div class="p-sect">{{ "Spaces" | tr }}</div>
                @for (l of nav.spaces(); track l.id) { <ng-container *ngTemplateOutlet="space; context: { $implicit: l }" /> }
              }
            </div>
          }
          @case ('settings') {
            <div class="p-scroll">
              <a class="item" routerLink="/settings" routerLinkActive="active" (click)="mobileOpen.set(false)"><hx-icon name="settings" [size]="17" /><span>{{ "Settings" | tr }}</span></a>
              <div class="p-sect">{{ "System" | tr }}</div>
              @for (l of nav.systemLinks(); track l.id) { <ng-container *ngTemplateOutlet="plain; context: { $implicit: l }" /> }
              @if (!auth.local()) {
                <button class="item dim" (click)="logout()" [title]="'Log out' | tr"><hx-icon name="logout" [size]="17" /><span>{{ "Log out" | tr }}</span></button>
              }
            </div>
          }
          @case ('spaces') {
            <div class="p-scroll">
              @for (l of nav.spaces(); track l.id) { <ng-container *ngTemplateOutlet="space; context: { $implicit: l }" /> }
              @empty { <p class="p-empty">{{ "No space yet: the modules you install add theirs here." | tr }}</p> }
            </div>
          }
          @default {
            <div class="p-scroll">
              @for (l of groupLinks(); track l.id) { <ng-container *ngTemplateOutlet="plain; context: { $implicit: l }" /> }
              @empty { <p class="p-empty">{{ "Nothing here yet." | tr }}</p> }
            </div>
          }
        }
      </aside>
      @if (chats.historyOpen()) { @defer { <hx-chat-history /> } }
      <div class="scrim" (click)="mobileOpen.set(false)"></div>
      <main>
        <button class="icon-btn opener" (click)="openDrawer()" [attr.aria-label]="'Open the panel' | tr" [title]="'Open the panel' | tr"><hx-icon name="sidebar" [size]="17" /></button>
        <router-outlet />
      </main>
      <!-- Phone: the rail becomes a bottom bar. -->
      <nav class="tabbar hx-glass" [attr.aria-label]="'Main menu' | tr">
        @for (b of phoneBar(); track b.g) {
          <a [routerLink]="nav.linkOf(b.g)" [class.on]="nav.group() === b.g" (click)="moreOpen.set(false)"><hx-icon [name]="b.icon" [size]="21" /><span>{{ b.label }}</span></a>
        }
        <button type="button" [class.on]="moreOpen() || ['assistant', 'notifications', 'settings'].includes(nav.group())" (click)="moreOpen.set(!moreOpen())" [attr.aria-expanded]="moreOpen()">
          <hx-icon name="more" [size]="21" /><span>{{ "More" | tr }}</span>
          @if (notifications.badge()) { <b class="dot"></b> }
        </button>
      </nav>
      @if (moreOpen()) {
        <div class="hx-ctx-scrim" (click)="moreOpen.set(false)"></div>
        <div class="more-sheet hx-glass hx-fade-in" role="menu">
          <a role="menuitem" [routerLink]="nav.linkOf('assistant')" (click)="moreOpen.set(false)"><hx-icon name="sparkle" [size]="18" />{{ name }}</a>
          <a role="menuitem" [routerLink]="nav.linkOf('notifications')" (click)="moreOpen.set(false)"><hx-icon name="bell" [size]="18" />{{ "Notices" | tr }}@if (notifications.badge(); as n) { <b class="count">{{ n }}</b> }</a>
          <button role="menuitem" (click)="moreOpen.set(false); openSearch()"><hx-icon name="search" [size]="18" />{{ "Search" | tr }}</button>
          <a role="menuitem" routerLink="/settings" (click)="moreOpen.set(false)"><hx-icon name="settings" [size]="18" />{{ "Settings" | tr }}</a>
          @if (!auth.local()) { <button role="menuitem" (click)="moreOpen.set(false); logout()"><hx-icon name="logout" [size]="18" />{{ "Log out" | tr }}</button> }
        </div>
      }
    </div>
    @if (chatMenu(); as m) {
      <div class="hx-ctx-scrim" (click)="chatMenu.set(null)"></div>
      <div class="hx-ctx hx-fade-in" role="menu" [style.left.px]="m.x" [style.top.px]="m.y">
        <button type="button" role="menuitem" (click)="startRename(m.chat)"><hx-icon name="edit" [size]="16" />{{ "Rename" | tr }}</button>
        <button type="button" role="menuitem" (click)="pinChat(m.chat)"><hx-icon name="pin" [size]="16" />{{ m.chat.pinned ? ('Remove from pinned' | tr) : ('Pin to the top' | tr) }}</button>
        <button type="button" role="menuitem" class="danger" (click)="deleteChat(m.chat)"><hx-icon name="trash" [size]="16" />{{ "Delete" | tr }}</button>
      </div>
    }
    <hx-quick-bubble />
    @defer (when assistant.isOpen()) { <hx-assistant /> }
    @defer (on idle) { <hx-command-palette /> }
    <hx-appearance-layer />
    @defer (when live.on) { <hx-live-overlay /> }
    <hx-toast-host />
    <hx-dialog-host />
    <ng-template #plain let-l>
      <a class="item" [class.off]="!l.online" [routerLink]="l.link" routerLinkActive="active" (click)="mobileOpen.set(false)"
         [attr.title]="l.online ? l.label : l.label + (' (not reachable)' | tr)">
        <hx-icon [name]="l.icon" [size]="17" /><span>{{ l.label }}</span>
        @if (l.badge) { <b class="count">{{ l.badge > 99 ? '99+' : l.badge }}</b> }
      </a>
    </ng-template>
    <ng-template #space let-l>
      <div class="row">
        <a class="item" [class.off]="!l.online" [routerLink]="l.link" routerLinkActive="active" (click)="mobileOpen.set(false)"
           [attr.title]="l.online ? l.label : l.label + (' (not reachable)' | tr)">
          <span class="tile" [style.--h]="l.color"><hx-icon [name]="l.icon" [size]="15" /></span><span>{{ l.label }}</span>
          @if (l.badge) { <b class="count">{{ l.badge > 99 ? '99+' : l.badge }}</b> }
        </a>
        <button type="button" class="more pin" [class.on]="isPinned(l)" (click)="plugins.toggleNavPin(l.id)"
                [attr.aria-label]="isPinned(l) ? ('Remove from the bar' | tr) : ('Pin to the bar' | tr)"
                [title]="isPinned(l) ? ('Remove from the bar' | tr) : ('Pin to the bar' | tr)"><hx-icon name="pin" [size]="14" /></button>
      </div>
    </ng-template>
  `,
  styles: [`
    :host { display: block; height: 100vh; height: 100dvh; }
    .shell { display: flex; height: 100%; }
    /* Rail */
    .rail { width: 76px; flex-shrink: 0; display: flex; flex-direction: column; align-items: center; gap: 2px; padding: 12px 6px 10px;
            background: var(--bg-subtle); border-right: 1px solid var(--border); overflow-y: auto; overflow-x: hidden; scrollbar-width: none; z-index: 2; }
    .logo { display: grid; place-items: center; width: 44px; height: 44px; margin-bottom: 8px; border-radius: var(--radius-md); }
    .logo:hover { background: var(--surface-2); }
    .rb { position: relative; width: 62px; flex-shrink: 0; display: flex; flex-direction: column; align-items: center; gap: 3px; padding: 7px 2px;
          border-radius: var(--radius-md); color: var(--text-3); font: 500 10.5px/1.2 var(--font-sans); text-decoration: none !important; background: none; border: 0; cursor: pointer; }
    .rb span:not(.tile) { max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .rb:hover { background: var(--surface-2); color: var(--text); }
    .rb.on { background: var(--accent-soft); color: var(--accent); }
    .rb.off { color: var(--warning); cursor: default; }
    .rb .tile { width: 28px; height: 28px; border-radius: var(--radius-sm); display: grid; place-items: center;
                background: color-mix(in srgb, var(--h) 16%, transparent); color: var(--h); }
    .rb.pinned.on { background: color-mix(in srgb, var(--h, var(--accent)) 12%, transparent); color: var(--text); }
    .sep { width: 32px; height: 1px; background: var(--border); margin: 6px 0; flex-shrink: 0; }
    .grow { flex: 1; min-height: 8px; }
    .dot { position: absolute; top: 3px; right: 9px; min-width: 15px; height: 15px; padding: 0 4px; border-radius: var(--radius-full); background: var(--accent);
           color: var(--accent-contrast); font: 600 9.5px/15px var(--font-sans); text-align: center; }
    /* Context panel */
    .panel { position: relative; flex-shrink: 0; display: flex; flex-direction: column; gap: 2px; padding: 12px 8px; min-height: 0;
             background: color-mix(in srgb, var(--bg-subtle) 70%, transparent); border-right: 1px solid var(--border); overflow: hidden;
             transition: width var(--dur) var(--ease); }
    .panel hx-resize { right: 0; }
    .p-head { display: flex; align-items: center; gap: 8px; padding: 2px 4px 10px 10px; flex-shrink: 0; }
    .p-title { flex: 1; font: 700 17px/1.2 var(--font-display, var(--font-sans)); letter-spacing: -.01em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .p-scroll { flex: 1; min-height: 0; overflow-y: auto; overflow-x: hidden; display: flex; flex-direction: column; gap: 2px; margin: 0 -8px; padding: 0 8px 8px; scrollbar-width: thin; }
    .p-sect { font: 600 11px var(--font-sans); color: var(--text-3); text-transform: uppercase; letter-spacing: .05em; padding: 14px 10px 4px; }
    .p-empty { margin: 0; padding: 8px 10px; font-size: 13px; color: var(--text-3); }
    .new-chat { margin: 0 2px 8px; justify-content: center; flex-shrink: 0; }
    .item { position: relative; display: flex; align-items: center; gap: 10px; min-height: 36px; padding: 0 10px; border-radius: var(--radius-md); width: 100%;
            color: var(--text-2); font-size: 14px; white-space: nowrap; text-decoration: none !important; text-align: left; background: none; border: 0; cursor: pointer; }
    .item span:not(.tile) { overflow: hidden; text-overflow: ellipsis; }
    .item:hover { background: var(--surface-2); color: var(--text); }
    .item.active { background: var(--accent-soft); color: var(--text); font-weight: 600; }
    .item hx-icon { color: var(--text-3); flex-shrink: 0; } .item.active hx-icon { color: var(--accent); }
    .item.off { opacity: .55; } .item.dim { color: var(--text-3); }
    .item .tile { width: 26px; height: 26px; border-radius: var(--radius-sm); display: grid; place-items: center; flex-shrink: 0;
                  background: color-mix(in srgb, var(--h) 16%, transparent); }
    .item .tile hx-icon { color: var(--h); }
    .row { position: relative; }
    .row .item { padding-right: 34px; }
    .more { position: absolute; right: 4px; top: 50%; transform: translateY(-50%); width: 26px; height: 26px; border-radius: var(--radius-md);
            display: inline-grid; place-items: center; background: none; border: 0; color: var(--text-3); cursor: pointer; opacity: 0; }
    .row:hover .more, .more:focus-visible, .more.on { opacity: 1; }
    .more:hover { background: var(--surface-3); color: var(--text); }
    .more.pin.on { color: var(--accent); }
    .row:hover .item .count { visibility: hidden; }
    @media (hover: none) { .more { opacity: .6; } .row .item .count { visibility: visible; } }
    .count { margin-left: auto; min-width: 18px; height: 18px; padding: 0 5px; border-radius: var(--radius-full); background: var(--accent);
             color: var(--accent-contrast); font: 600 11px/18px var(--font-sans); text-align: center; }
    .tdot { width: 7px; height: 7px; border-radius: 50%; margin-left: auto; flex-shrink: 0; }
    .ren { height: 34px; font-size: 13.5px; width: 100%; }
    .icon-btn { width: 32px; height: 32px; border-radius: var(--radius-md); display: inline-grid; place-items: center; color: var(--text-3); background: none; border: 0; cursor: pointer; flex-shrink: 0; }
    .icon-btn:hover { background: var(--surface-2); color: var(--text); }
    .panel-closed .panel { display: none; }
    main { flex: 1; min-width: 0; display: flex; flex-direction: column; position: relative; background: transparent; }
    .opener { display: none; position: absolute; top: 14px; left: 10px; z-index: 5; background: var(--surface); border: 1px solid var(--border); box-shadow: var(--shadow-1); }
    .panel-closed .opener { display: inline-grid; }
    .panel-closed main { --head-inset: 44px; }
    .scrim, .tabbar { display: none; }
    .more-sheet { position: fixed; right: 10px; bottom: calc(70px + env(safe-area-inset-bottom, 0px)); z-index: 950; min-width: 220px; padding: 6px;
                  background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-lg); box-shadow: var(--shadow-3); display: flex; flex-direction: column; }
    .more-sheet a, .more-sheet button { display: flex; align-items: center; gap: 10px; padding: 10px 12px; border-radius: var(--radius-md); color: var(--text);
                  text-decoration: none; background: none; border: 0; font: inherit; text-align: left; cursor: pointer; min-height: var(--tap, 0px); }
    .more-sheet a:hover, .more-sheet button:hover { background: var(--surface-2); }
    .more-sheet hx-icon { color: var(--text-3); }
    .presence .pdot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; margin: 0 4px; background: var(--text-3); }
    .presence[data-tone=awake] .pdot { background: var(--success); }
    .presence[data-tone=idle] .pdot { background: var(--warning); }
    .presence[data-tone=sleep] .pdot { background: var(--accent); }
    .presence[data-tone=dnd] .pdot { background: var(--danger); }
    .presence[data-tone=off] .pdot { background: var(--warning); animation: hx-pulse 1.4s ease-in-out infinite; }
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
    .presence-wrap { width: 100%; display: grid; place-items: center; margin-top: 4px; }
    .presence { width: 44px; height: 30px; justify-content: center; padding: 0; background: none; border: 0; cursor: pointer; border-radius: var(--radius-md); display: flex; align-items: center; }
    .presence:hover { background: var(--surface-2); }
    .presence .plabel { display: none; }
    .conn { display: grid; place-items: center; padding: 8px 0 2px; }
    .conn span:last-child { display: none; }
    .conn .dot { position: static; width: 8px; height: 8px; min-width: 0; padding: 0; border-radius: 50%; background: var(--warning); }
    .conn[data-state=connected] .dot { background: var(--success); }
    .conn[data-state=disconnected] .dot { background: var(--danger); }
    @media (max-width: 860px) {
      .rail { display: none; }
      .panel { position: fixed; inset: 0 auto 0 0; z-index: 800; width: min(300px, 86vw) !important; transform: translateX(-100%); display: flex !important;
               transition: transform var(--dur) var(--ease); box-shadow: var(--shadow-3); background: var(--bg-subtle); padding-top: calc(12px + env(safe-area-inset-top, 0px)); }
      .panel hx-resize { display: none; }
      .mobile-open .panel { transform: none; }
      .mobile-open .scrim { display: block; position: fixed; inset: 0; background: var(--overlay); z-index: 790; }
      .opener, .panel-closed .opener { display: inline-grid; top: 12px; }
      main { --head-inset: 44px; padding-bottom: calc(62px + env(safe-area-inset-bottom, 0px)); }
      .tabbar { display: grid; grid-template-columns: repeat(5, 1fr); position: fixed; left: 0; right: 0; bottom: 0; z-index: 700;
                padding: 4px 4px calc(6px + env(safe-area-inset-bottom, 0px)); background: var(--bg-subtle); border-top: 1px solid var(--border); }
      .tabbar a, .tabbar button { position: relative; display: flex; flex-direction: column; align-items: center; gap: 2px; padding: 6px 0; min-height: 52px; justify-content: center;
                  color: var(--text-3); font: 500 10.5px var(--font-sans); text-decoration: none; background: none; border: 0; cursor: pointer; }
      .tabbar .on { color: var(--accent); }
      .tabbar .dot { top: 4px; right: calc(50% - 16px); min-width: 8px; width: 8px; height: 8px; padding: 0; }
    }
  `],
})
export class ShellComponent {
  /** The site calls itself with the name the owner chose (docs/work/2026-11-17-client-names). */
  readonly name = assistantName();
  auth = inject(AuthService);
  signalR = inject(SignalRService);
  assistant = inject(AssistantService);
  notifications = inject(NotificationsService);
  presence = inject(PresenceService);
  plugins = inject(PluginsService);
  nav = inject(NavService);
  session = inject(SessionService);
  chats = inject(ChatsService);
  live = inject(LiveVoiceService);
  private chat = inject(ChatService);
  private toasts = inject(ToastService);
  private metis = inject(MetisService);
  private look = inject(AppearanceService);
  private settings = inject(SettingsService);
  private router = inject(Router);

  /** Top of the rail: the groups; Agenda only when a module gives it pages. */
  readonly railTop = computed<RailButton[]>(() => {
    const has = this.nav.byPlace();
    return [
      { g: 'today' as NavGroup, label: tr('Today'), icon: 'home' },
      { g: 'chat' as NavGroup, label: tr('Chat'), icon: 'chat' },
      ...(has.agenda.length ? [{ g: 'agenda' as NavGroup, label: tr('Agenda'), icon: 'calendar' }] : []),
      { g: 'spaces' as NavGroup, label: tr('Spaces'), icon: 'grid' },
      ...(has.assistant.length ? [{ g: 'assistant' as NavGroup, label: this.name, icon: 'sparkle' }] : []),
    ];
  });
  /** Phone bar: Today, Chat, Agenda, Spaces + «More». */
  readonly phoneBar = computed(() => this.railTop().filter(b => b.g !== 'assistant').slice(0, 4));

  readonly groupLabel = computed(() => ({
    today: tr('Today'), chat: tr('Chat'), agenda: tr('Agenda'), spaces: tr('Spaces'), assistant: this.name,
    notifications: tr('Notices'), settings: tr('Settings'),
  } as Record<NavGroup, string>)[this.nav.group()]);
  /** Agenda, assistant and notices: their pages. */
  readonly groupLinks = computed<NavLink[]>(() => {
    const g = this.nav.group();
    return g === 'agenda' || g === 'assistant' || g === 'notifications' ? this.nav.byPlace()[g] : [];
  });
  /** Today: Home, the owner's other dashboards, Discover. */
  readonly todayLinks = computed<NavLink[]>(() => [
    { id: 'app.home', label: tr('alt::Home'), icon: 'home', link: '/home', online: true, badge: 0, color: '' },
    ...this.plugins.dashboards().filter(d => d.id !== 'home' && d.id !== 'system')
      .map(d => ({ id: 'dash.' + d.id, label: d.title, icon: d.icon || 'grid', link: '/d/' + d.id, online: true, badge: 0, color: '' })),
    { id: 'app.discover', label: tr('Discover'), icon: 'sparkle', link: '/discover', online: true, badge: 0, color: '' },
  ]);
  isPinned(l: NavLink): boolean { return this.plugins.navPinned().includes(l.id); }

  readonly bellLabel = computed(() => {
    const n = this.notifications.badge();
    return n ? tr("Notifications: {0} to read", n) : tr('Notifications');
  });

  /** Panel open/closed and width, per browser. */
  panelClosed = signal(this.readClosed());
  navWidth = signal(savedWidth('panel', 236));
  mobileOpen = signal(false);
  moreOpen = signal(false);
  togglePanel(): void {
    if (window.innerWidth <= 860) { this.mobileOpen.set(false); return; }
    this.panelClosed.update(v => !v);
    try { localStorage.setItem('hestia_panel_closed', this.panelClosed() ? '1' : '0'); } catch { /* */ }
  }
  /** A rail button shows its list: a closed panel stays closed (the owner closed it), the phone drawer closes. */
  openPanel(): void { this.mobileOpen.set(false); }
  openDrawer(): void {
    if (window.innerWidth <= 860) { this.mobileOpen.set(true); return; }
    this.togglePanel();
  }
  private readClosed(): boolean {
    try { return localStorage.getItem('hestia_panel_closed') === '1'; } catch { return false; }
  }

  online = computed(() => this.signalR.connectionState() === 'connected');
  connLabel = computed(() => ({ connected: tr('Connected'), connecting: tr('Connecting…'), disconnected: tr('Disconnected') })[this.signalR.connectionState()]);
  private bootstrapped = false;

  constructor() {
    // The panel's conversations follow each finished answer.
    let streaming = false;
    effect(() => {
      const now = this.chat.isStreaming();
      if (streaming && !now) untracked(() => void this.chats.refreshRecent());
      streaming = now;
    });
    effect(() => { if (this.plugins.modules().has('oracle')) untracked(() => void this.chats.refreshRecent()); });
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

  openSearch(): void { this.mobileOpen.set(false); window.dispatchEvent(new CustomEvent('hestia:palette')); }

  async openChat(id: string): Promise<void> {
    this.mobileOpen.set(false);
    await this.chats.open(id);
  }

  /** «New conversation» in the Chat panel: a fresh session (the memories stay). */
  async newChat(): Promise<void> {
    this.mobileOpen.set(false);
    await this.session.clear();
    this.chat.clearMessages();
  }

  tagCss(c: string) { return TAG_CSS[c] || TAG_CSS['gray']; }

  /** «…» on a conversation: rename, pin, delete. Drawn outside the panel, which clips what overflows it. */
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
    setTimeout(() => { const el = document.querySelector<HTMLInputElement>('.panel input.ren'); el?.focus(); el?.select(); });
  }
  async rename(c: ChatSummary, title: string): Promise<void> {
    if (this.renaming() !== c.session_id) return;      // Enter then blur: once
    this.renaming.set('');
    const t = title.trim();
    if (!t || t === c.title) return;
    if (!(await this.chats.setMeta(c.session_id, { title: t })).ok) this.toasts.error(tr('Not saved'));
  }
  async pinChat(c: ChatSummary): Promise<void> {
    this.chatMenu.set(null);
    if (!(await this.chats.setMeta(c.session_id, { pinned: !c.pinned })).ok) this.toasts.error(tr('Not saved'));
  }
  deleteChat(c: ChatSummary): void {
    this.chatMenu.set(null);
    void this.chats.confirmRemove(c);
  }

  presenceOpen = signal(false);
  presencePos = signal({ left: 8, bottom: 8, maxHeight: 480 });

  /** Opens the state popover next to its button, in viewport coordinates (never clipped by the rail). */
  togglePresence(ev: MouseEvent): void {
    if (this.presenceOpen()) { this.presenceOpen.set(false); return; }
    const r = (ev.currentTarget as HTMLElement).getBoundingClientRect();
    const width = Math.min(300, window.innerWidth - 16);
    this.presencePos.set({
      left: Math.max(8, Math.min(r.right + 8, window.innerWidth - width - 8)),
      bottom: Math.max(8, window.innerHeight - r.bottom),
      maxHeight: Math.max(160, r.bottom - 14),
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
    const d = m % 60 === 0 ? (m === 60 ? tr('1 hour') : tr('{0} hours', m / 60)) : `${m} min`;
    return tr("«Do not disturb»: for {0} you get only urgent notifications; you receive the others in a summary when it ends.", d);
  }
  readonly ago = ago;

  /** «Talk» from anywhere: same live mode as the chat page (layout/live-overlay shows it on other pages). */
  toggleLive(): void {
    if (this.live.on) { this.live.stop(); return; }
    void this.live.start().then(() => { if (this.live.error()) this.toasts.error(this.live.error()); });
  }

  /** Ctrl+J = «Write here» from anywhere; Ctrl+Shift+Space = «Talk»; Ctrl+B = open/close the panel. */
  @HostListener('document:keydown', ['$event'])
  onKey(e: KeyboardEvent) {
    if (e.key === 'Escape' && this.chatMenu()) { this.chatMenu.set(null); return; }
    if (e.key === 'Escape' && this.presenceOpen()) { this.presenceOpen.set(false); return; }
    if (e.key === 'Escape' && this.moreOpen()) { this.moreOpen.set(false); return; }
    if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.code === 'Space') { e.preventDefault(); this.toggleLive(); return; }
    if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === 'j') {
      e.preventDefault();
      this.assistant.toggle();
    }
  }

  logout() {
    this.auth.logout();
    void this.signalR.disconnect();
    this.router.navigate(['/login']);
  }
}
