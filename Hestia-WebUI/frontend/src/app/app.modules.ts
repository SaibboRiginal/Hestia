import { Type } from '@angular/core';

/**
 * WebUI module registry — ONE place to add a page.
 * Each entry becomes a route (/path, lazy loaded) and a sidebar item.
 * Guide: DESIGN-SYSTEM.md § "Add a module".
 */
export interface AppModule {
  path: string;
  label: string;
  icon: string;                       // hx-icon name
  load: () => Promise<Type<unknown>>; // standalone page component
  bottom?: boolean;                   // pinned to the bottom of the sidebar
}

export const APP_MODULES: AppModule[] = [
  { path: 'chat', label: 'Chat', icon: 'chat',
    load: () => import('./features/chat/chat-page.component').then(m => m.ChatPageComponent) },
  { path: 'calendar', label: 'Agenda di Hestia', icon: 'calendar',
    load: () => import('./features/calendar/calendar-page.component').then(m => m.CalendarPageComponent) },
  { path: 'commands', label: 'Comandi & MCP', icon: 'terminal',
    load: () => import('./features/commands/commands-page.component').then(m => m.CommandsPageComponent) },
  { path: 'documents', label: 'Documenti', icon: 'file',
    load: () => import('./features/documents/documents-page.component').then(m => m.DocumentsPageComponent) },
  { path: 'settings', label: 'Impostazioni', icon: 'settings', bottom: true,
    load: () => import('./features/settings/settings-page.component').then(m => m.SettingsPageComponent) },
];
