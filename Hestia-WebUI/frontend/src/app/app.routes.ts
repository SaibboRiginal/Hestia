import { Routes } from '@angular/router';
import { authGuard } from './guards/auth.guard';
import { APP_MODULES } from './app.modules';
import { ShellComponent } from './layout/shell.component';

export const routes: Routes = [
  { path: 'login', loadComponent: () => import('./features/login/login-page.component').then(m => m.LoginPageComponent) },
  {
    path: '',
    component: ShellComponent,
    canActivate: [authGuard],
    children: [
      ...APP_MODULES.map(m => ({ path: m.path, loadComponent: m.load, title: `${m.label} · Hestia` })),
      { path: '', pathMatch: 'full' as const, redirectTo: 'chat' },
    ],
  },
  { path: '**', redirectTo: '' },
];
