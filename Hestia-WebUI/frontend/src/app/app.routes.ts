import { Routes } from '@angular/router';
import { authGuard } from './guards/auth.guard';
import { setupGuard } from './guards/setup.guard';
import { APP_MODULES } from './app.modules';
import { ShellComponent } from './layout/shell.component';
import { pluginPageMatcher } from './features/plugins/plugin-routes';
import { tr } from './core/i18n';

export const routes: Routes = [
  { path: 'login', loadComponent: () => import('./features/login/login-page.component').then(m => m.LoginPageComponent) },
  // Guided setup after the install (docs/work/2026-10-30-setup-un-click §4.2): full screen, outside the shell.
  // The address is the same in every language (the installer prints it); the old Italian one still works.
  { path: 'setup', canActivate: [authGuard], title: tr('Setup · Hestia'),
    loadComponent: () => import('./features/setup/setup-page.component').then(m => m.SetupPageComponent) },
  { path: 'welcome', redirectTo: 'setup' },
  {
    path: '',
    component: ShellComponent,
    canActivate: [authGuard, setupGuard],
    children: [
      ...APP_MODULES.map(m => ({ path: m.path, loadComponent: m.load, title: `${m.label} · Hestia` })),
      // Built-in pages that moved into their module as plugins (old links, bookmarks, ?task=… keep working).
      { path: 'notifications', redirectTo: '/p/hermes/notifications' },
      { path: 'commands', redirectTo: '/p/mcp/commands' },
      { path: 'forge', redirectTo: '/p/hephaestus/development' },
      { path: 'documents', redirectTo: '/p/oracle/documents' },
      { path: 'calendar', redirectTo: '/p/chronos/agenda' },
      { path: 'download', loadComponent: () => import('./features/downloads/downloads-page.component').then(m => m.DownloadsPageComponent), title: tr('Downloads · Hestia') },
      { path: 'updates', loadComponent: () => import('./features/updates/updates-page.component').then(m => m.UpdatesPageComponent), title: tr('Updates · Hestia') },
      { path: 'machines', loadComponent: () => import('./features/machines/machines-page.component').then(m => m.MachinesPageComponent), title: tr('Machines · Hestia') },
      { path: 'system', loadComponent: () => import('./features/system/system-page.component').then(m => m.SystemPageComponent), title: tr('System · Hestia') },
      { path: 'd/:id', loadComponent: () => import('./features/plugins/dashboard-page.component').then(m => m.DashboardPageComponent), title: tr('Dashboard · Hestia') },
      { matcher: pluginPageMatcher, loadComponent: () => import('./features/plugins/plugin-page.component').then(m => m.PluginPageComponent), title: 'Hestia' },
      { path: '', pathMatch: 'full' as const, redirectTo: 'home' },
    ],
  },
  { path: '**', redirectTo: '' },
];
