import { Component, inject, signal, OnInit } from '@angular/core';
import { RouterOutlet, Router } from '@angular/router';
import { AuthService } from './services/auth.service';
import { SignalRService } from './services/signalr.service';
import { SessionService } from './services/session.service';
import { SettingsService } from './services/settings.service';
import { SidebarComponent } from './components/sidebar/sidebar.component';
import { ChatViewComponent } from './components/chat-view/chat-view.component';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet, SidebarComponent, ChatViewComponent],
  template: `
    @if (auth.isAuthenticated()) {
      <div class="app-shell">
        <app-sidebar [sidebarOpen]="sidebarOpen()" (closeSidebar)="closeSidebar()" />
        <div class="main-area">
          <div class="top-bar">
            <button class="burger" (click)="toggleSidebar()">☰</button>
            <span class="brand">🏛️ Hestia</span>
            <span class="dot" [class.on]="signalR.connectionState() === 'connected'"></span>
            <button class="logout" (click)="logout()">⏻</button>
          </div>
          <app-chat-view />
        </div>
      </div>
    } @else {
      <router-outlet />
    }
  `,
  styles: [`
    :host { display:block; height:100vh; overflow:hidden; }
    .app-shell { display:flex; height:100%; overflow:hidden; }
    .main-area { flex:1; display:flex; flex-direction:column; min-width:0; overflow:hidden; }
    .top-bar { display:flex; align-items:center; gap:12px; padding:0 16px; height:48px; background:var(--bg-secondary); border-bottom:1px solid var(--border); flex-shrink:0; }
    .burger { background:none; border:none; color:var(--text-secondary); font-size:20px; cursor:pointer; padding:4px 8px; border-radius:6px; }
    .burger:hover { background:var(--bg-hover); }
    .brand { font-weight:700; font-size:15px; color:var(--text-primary); }
    .dot { width:8px; height:8px; border-radius:50%; background:var(--danger); margin-left:auto; }
    .dot.on { background:var(--success); }
    .logout { background:none; border:none; color:var(--text-secondary); font-size:18px; cursor:pointer; padding:4px 8px; border-radius:6px; }
    .logout:hover { background:var(--bg-hover); color:var(--danger); }
  `]
})
export class AppComponent implements OnInit {
  auth = inject(AuthService);
  signalR = inject(SignalRService);
  private session = inject(SessionService);
  private settings = inject(SettingsService);
  private router = inject(Router);
  sidebarOpen = signal(localStorage.getItem('sidebar') === 'open');

  toggleSidebar() {
    this.sidebarOpen.update(v => {
      const n = !v;
      localStorage.setItem('sidebar', n ? 'open' : 'closed');
      return n;
    });
  }

  closeSidebar() {
    this.sidebarOpen.set(false);
    localStorage.setItem('sidebar', 'closed');
  }

  async ngOnInit() {
    const p = new URLSearchParams(window.location.search);
    const t = p.get('token');
    if (t) { await this.auth.login(t); history.replaceState({}, '', '/'); }
    if (!this.auth.isAuthenticated()) { this.router.navigate(['/login']); return; }
    await this.signalR.connect();
    await this.session.load();
    await this.settings.load();
  }

  logout() { this.auth.logout(); this.signalR.disconnect(); this.router.navigate(['/login']); }
}
