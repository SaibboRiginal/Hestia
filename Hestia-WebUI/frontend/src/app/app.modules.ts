import { Type } from '@angular/core';

/**
 * WebUI module registry — ONE place to add a page.
 * Each entry becomes a route (/path, lazy loaded) and a sidebar item.
 * Guide: DESIGN-SYSTEM.md § "Add a module".
 * Pages of Hestia modules (client plugins) are NOT listed here: they come from Hub's catalog at runtime
 * (features/plugins, routes /p/<module>/…, dashboards /d/<id>). Agenda, Notifiche, Comandi & MCP, Sviluppo and Documenti
 * became plugin pages of Chronos, Hermes, Hestia-MCP, Hephaestus and Oracle: their old paths redirect (app.routes.ts).
 */
export interface AppModule {
  path: string;
  label: string;
  icon: string;                       // hx-icon name
  load: () => Promise<Type<unknown>>; // standalone page component
  bottom?: boolean;                   // pinned to the bottom of the sidebar
}

export const APP_MODULES: AppModule[] = [
  { path: 'home', label: 'Home', icon: 'home',
    load: () => import('./features/plugins/dashboard-page.component').then(m => m.DashboardPageComponent) },
  { path: 'chat', label: 'Chat', icon: 'chat',
    load: () => import('./features/chat/chat-page.component').then(m => m.ChatPageComponent) },
  { path: 'scopri', label: 'Scopri', icon: 'sparkle',
    load: () => import('./features/scopri/scopri-page.component').then(m => m.ScopriPageComponent) },
  { path: 'settings', label: 'Impostazioni', icon: 'settings', bottom: true,
    load: () => import('./features/settings/settings-page.component').then(m => m.SettingsPageComponent) },
];
