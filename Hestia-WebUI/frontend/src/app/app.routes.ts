import { Routes } from '@angular/router';
import { authGuard } from './guards/auth.guard';
import { APP_MODULES } from './app.modules';
import { ShellComponent } from './layout/shell.component';
import { pluginPageMatcher } from './features/plugins/plugin-routes';

export const routes: Routes = [
  { path: 'login', loadComponent: () => import('./features/login/login-page.component').then(m => m.LoginPageComponent) },
  {
    path: '',
    component: ShellComponent,
    canActivate: [authGuard],
    children: [
      ...APP_MODULES.map(m => ({ path: m.path, loadComponent: m.load, title: `${m.label} · Hestia` })),
      // Built-in pages that moved into their module as plugins (old links, bookmarks, ?task=… keep working).
      { path: 'notifications', redirectTo: '/p/hermes/notifiche' },
      { path: 'commands', redirectTo: '/p/mcp/comandi' },
      { path: 'forge', redirectTo: '/p/hephaestus/sviluppo' },
      { path: 'documents', redirectTo: '/p/oracle/documenti' },
      { path: 'calendar', redirectTo: '/p/chronos/agenda' },
      { path: 'd/:id', loadComponent: () => import('./features/plugins/dashboard-page.component').then(m => m.DashboardPageComponent), title: 'Dashboard · Hestia' },
      { matcher: pluginPageMatcher, loadComponent: () => import('./features/plugins/plugin-page.component').then(m => m.PluginPageComponent), title: 'Hestia' },
      { path: '', pathMatch: 'full' as const, redirectTo: 'home' },
    ],
  },
  { path: '**', redirectTo: '' },
];
