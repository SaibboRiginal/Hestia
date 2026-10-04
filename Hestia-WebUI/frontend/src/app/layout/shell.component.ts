import { ChangeDetectionStrategy, Component, HostListener, computed, effect, inject, signal, untracked } from '@angular/core';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { APP_MODULES } from '../app.modules';
import { AuthService } from '../services/auth.service';
import { SignalRService } from '../services/signalr.service';
import { SessionService } from '../services/session.service';
import { SettingsService } from '../services/settings.service';
import { ThemeService } from '../core/theme/theme.service';
import { DialogHostComponent, IconComponent, ToastHostComponent } from '../ui';
import { AssistantDrawerComponent } from '../features/assistant/assistant-drawer.component';
import { AssistantService } from '../services/assistant.service';

/** App frame: collapsible sidebar (modules from APP_MODULES) + routed page + global overlays. */
@Component({
  selector: 'app-shell',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, IconComponent, ToastHostComponent, DialogHostComponent, AssistantDrawerComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="shell" [class.collapsed]="collapsed()" [class.mobile-open]="mobileOpen()">
      <aside class="nav">
        <div class="brand">
          <span class="logo">◈</span>
          <span class="name">Hestia</span>
          <button class="icon-btn collapse" (click)="toggleCollapse()" [attr.aria-label]="collapsed() ? 'Espandi' : 'Comprimi'">
            <hx-icon name="sidebar" [size]="17" />
          </button>
        </div>
        <button class="item ask" (click)="assistant.toggle(); mobileOpen.set(false)" title="Crea con Hestia (Ctrl+J)">
          <hx-icon name="sparkle" [size]="18" /><span>Crea con Hestia</span><kbd>Ctrl J</kbd>
        </button>
        <nav>
          @for (m of top; track m.path) {
            <a class="item" [routerLink]="'/' + m.path" routerLinkActive="active" (click)="mobileOpen.set(false)" [attr.title]="m.label">
              <hx-icon [name]="m.icon" [size]="18" /><span>{{ m.label }}</span>
            </a>
          }
        </nav>
        <div class="spacer"></div>
        <nav>
          @for (m of bottom; track m.path) {
            <a class="item" [routerLink]="'/' + m.path" routerLinkActive="active" (click)="mobileOpen.set(false)" [attr.title]="m.label">
              <hx-icon [name]="m.icon" [size]="18" /><span>{{ m.label }}</span>
            </a>
          }
          <button class="item" (click)="theme.toggleMode()" [attr.title]="'Tema: ' + theme.active().label">
            <hx-icon [name]="theme.active().mode === 'dark' ? 'sun' : 'moon'" [size]="18" />
            <span>{{ theme.active().mode === 'dark' ? 'Tema chiaro' : 'Tema scuro' }}</span>
          </button>
          <button class="item" (click)="logout()" title="Esci">
            <hx-icon name="logout" [size]="18" /><span>Esci</span>
          </button>
        </nav>
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
    <hx-toast-host />
    <hx-dialog-host />
  `,
  styles: [`
    :host { display: block; height: 100vh; }
    .shell { display: flex; height: 100%; }
    .nav { width: var(--nav-width); flex-shrink: 0; background: var(--bg-subtle); border-right: 1px solid var(--border);
           display: flex; flex-direction: column; padding: 10px 8px; gap: 2px; transition: width var(--dur) var(--ease); overflow: hidden; }
    .brand { display: flex; align-items: center; gap: 9px; padding: 4px 6px 12px 8px; }
    .logo { color: var(--accent); font-size: 20px; line-height: 1; }
    .name { font-family: var(--font-serif); font-size: 19px; font-weight: 500; flex: 1; white-space: nowrap; }
    .icon-btn { width: 32px; height: 32px; border-radius: var(--radius-md); display: inline-grid; place-items: center; color: var(--text-3); }
    .icon-btn:hover { background: var(--surface-2); color: var(--text); }
    nav { display: flex; flex-direction: column; gap: 2px; }
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
    .spacer { flex: 1; }
    .conn { display: flex; align-items: center; gap: 7px; font-size: 11.5px; color: var(--text-3); padding: 8px 12px 2px; white-space: nowrap; }
    .conn .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--warning); flex-shrink: 0; }
    .conn[data-state=connected] .dot { background: var(--success); }
    .conn[data-state=disconnected] .dot { background: var(--danger); }
    .collapsed .nav { width: var(--nav-width-collapsed); }
    .collapsed .name, .collapsed .item span, .collapsed .conn span:last-child { display: none; }
    .collapsed .brand { flex-direction: column; padding-left: 0; padding-right: 0; }
    main { flex: 1; min-width: 0; display: flex; flex-direction: column; position: relative; background: var(--bg); }
    .burger { display: none; position: absolute; top: 12px; left: 10px; z-index: 5; }
    .scrim { display: none; }
    @media (max-width: 860px) {
      .nav { position: fixed; inset: 0 auto 0 0; z-index: 800; transform: translateX(-100%); transition: transform var(--dur) var(--ease); width: var(--nav-width) !important; box-shadow: var(--shadow-3); }
      .collapsed .name, .collapsed .item span, .collapsed .conn span:last-child { display: initial; }
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
  theme = inject(ThemeService);
  assistant = inject(AssistantService);
  private session = inject(SessionService);
  private settings = inject(SettingsService);
  private router = inject(Router);
  collapsed = signal(this.readCollapsed());
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
    await Promise.all([this.session.load(), this.settings.load()]);
  }

  /** "Crea con Hestia" from anywhere. */
  @HostListener('document:keydown', ['$event'])
  onKey(e: KeyboardEvent) {
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
