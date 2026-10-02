import { Component, input, output, signal } from '@angular/core';
import { SettingsPanelComponent } from './settings-panel/settings-panel.component';
import { CommandPaletteComponent } from './command-palette/command-palette.component';
import { SessionListComponent } from './session-list/session-list.component';
import { DocumentListComponent } from './document-list/document-list.component';
import { NgClass } from '@angular/common';

type Panel = 'sessions' | 'settings' | 'commands' | 'documents';

@Component({
  selector: 'app-sidebar',
  standalone: true,
  imports: [SettingsPanelComponent, CommandPaletteComponent, SessionListComponent, DocumentListComponent, NgClass],
  host: { '[class.open]': 'sidebarOpen()' },
  template: `
    <div class="sidebar-backdrop" [class.show]="sidebarOpen()" (click)="closeSidebar.emit()"></div>
    <aside class="sidebar" [class.open]="sidebarOpen()">
      <div class="sidebar-header">
        <span class="sidebar-title">🏛️ Hestia</span>
      </div>
      <nav class="sidebar-nav">
        <button [ngClass]="{ active: activePanel() === 'sessions' }" (click)="activePanel.set('sessions')">
          💬 Session
        </button>
        <button [ngClass]="{ active: activePanel() === 'commands' }" (click)="activePanel.set('commands')">
          ⌨️ Commands
        </button>
        <button [ngClass]="{ active: activePanel() === 'settings' }" (click)="activePanel.set('settings')">
          ⚙️ Settings
        </button>
        <button [ngClass]="{ active: activePanel() === 'documents' }" (click)="activePanel.set('documents')">
          📎 Documents
        </button>
      </nav>
      <div class="sidebar-content">
        @switch (activePanel()) {
          @case ('sessions') { <app-session-list /> }
          @case ('commands') { <app-command-palette /> }
          @case ('settings') { <app-settings-panel /> }
          @case ('documents') { <app-document-list /> }
        }
      </div>
    </aside>
  `,
  styles: [`
    :host { display:block; height:100%; flex-shrink:0; width:0; overflow:hidden; transition:width var(--transition-smooth); }
    :host(.open) { width:var(--sidebar-width); overflow:visible; }
    .sidebar-backdrop { display:none; position:fixed; inset:0; background:rgba(0,0,0,0.5); z-index:40; }
    .sidebar-backdrop.show { display:block; }
    .sidebar {
      width:var(--sidebar-width); height:100%; background:var(--bg-secondary);
      border-right:1px solid var(--border); display:flex; flex-direction:column;
      position:fixed; left:0; top:0; bottom:0; z-index:50;
      transform:translateX(-100%); transition:transform var(--transition-smooth);
    }
    :host(.open) .sidebar { transform:translateX(0); }
    @media (min-width:768px) {
      .sidebar { position:static; transform:none; height:100%; }
      :host(.open) .sidebar { transform:none; }
      .sidebar-backdrop { display:none!important; }
    }
    .sidebar-header {
      display: flex; align-items: center; justify-content: space-between;
      padding: 12px 16px; border-bottom: 1px solid var(--border);
    }
    .sidebar-title { font-weight: 700; font-size: 16px; }
    .sidebar-nav {
      display: flex; flex-direction: column; gap: 2px; padding: 8px;
    }
    .sidebar-nav button {
      display: flex; align-items: center; gap: 8px;
      padding: 10px 12px; border: none; border-radius: var(--radius-md);
      background: none; color: var(--text-secondary); font-size: 14px;
      cursor: pointer; font-family: 'Inter', sans-serif;
      transition: all var(--transition-fast);
    }
    .sidebar-nav button:hover { background: var(--bg-hover); color: var(--text-primary); }
    .sidebar-nav button.active { background: var(--accent-light); color: var(--accent); font-weight: 500; }
    .sidebar-content { flex: 1; overflow-y: auto; padding: 8px; }
  `]
})
export class SidebarComponent {
  sidebarOpen = input(false);
  closeSidebar = output<void>();
  activePanel = signal<Panel>('sessions');
}
