/** Client plugins as the WebUI sees them (Hub catalog, client=webui). SPEC docs/work/2026-10-17-client-plugins §4. */

export type WidgetSize = 's' | 'm' | 'l' | 'xl';

export interface PluginModule {
  module: string;
  title: string;
  icon: string;
  color: string;
  description: string;
  version: string;
  online: boolean;
  kind?: 'domain' | 'core';  // core = system module, shown under «Sistema» in the sidebar
}

interface Contribution {
  id: string;            // "<module>.<local id>"
  local_id: string;
  module: string;
  label: string;
  icon?: string;
  online: boolean;
}

export interface PluginPage extends Contribution {
  element: string;
  order: number;
  parent: string;        // local id of the parent page ('' = top level)
  detail: boolean;       // opened from an item ('case/:id'), no sidebar entry
  help?: string;
  badge?: { source: string; field: string } | null;   // GET under api_prefix → number shown next to the entry
}

export interface ParamSpec { type: string; label: string; default?: unknown; options?: string[]; }

export interface PluginWidget extends Contribution {
  element: string;
  sizes: WidgetSize[];
  size: WidgetSize;
  auto: boolean;
  params: Record<string, ParamSpec>;
  open_page: string;
  help?: string;
}

export interface QuickActionDef extends Contribution {
  method: string;
  path: string;
  group: string;
  source: string;
  confirm: string | null;
  undo: { method: string; path: string } | null;
  params: Record<string, ParamSpec>;
  favorite: boolean;
  order: number;
}

/** A panel shown inside the module's own settings (Impostazioni → Sistema → <module>), e.g. the backup history. */
export interface PluginSettingsPanel extends Contribution {
  element: string;
  order: number;
  help?: string;
}

export interface PluginBundle { id: string; module: string; entry: string; api_prefix: string; sdk: string; version: string; online: boolean; }

export interface PluginCatalog {
  revision: number;
  ui_revision: string;
  modules: PluginModule[];
  contributions: { webui?: { page?: PluginPage[]; widget?: PluginWidget[]; quick_action?: QuickActionDef[];
                             settings_panel?: PluginSettingsPanel[]; bundle?: PluginBundle[] } };
}

/** One placed widget on a dashboard (WebUI setting webui.dashboards). */
export interface DashboardItem {
  widget: string;                       // "<module>.<widget id>"
  size: WidgetSize;
  params?: Record<string, unknown>;
  title?: string;
}

export interface Dashboard {
  id: string;
  title: string;
  icon?: string;
  auto?: boolean;                       // Home before the user edits it: composed from auto widgets
  kind?: 'domain' | 'core';             // which auto widgets an automatic dashboard takes (Home: domain, Sistema: core)
  removed?: boolean;                    // the user deleted the ready-made «Sistema»: kept as a marker so it does not come back
  created_by?: 'user' | 'oracle' | string;
  items: DashboardItem[];
  dismissed?: string[];                 // auto widgets the user removed from an automatic dashboard
}

/** A quick-action chip of the moment (static action, or one item of a dynamic `source`). */
export interface QuickChipView {
  key: string;                          // "<module>.<action>" or "<module>.<action>:<chip id>" (pin key)
  action: QuickActionDef;
  chipId: string;                       // fills {id}; '' for static actions
  label: string;
  icon?: string;
  state?: 'todo' | 'done' | 'late';
  hint?: string;
  favorite?: boolean;
}
