import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpErrorResponse, HttpParams } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';

/** Central settings (Themis) as seen by the WebUI: `/api/webui/central-settings/*` → Hub → Themis. */

export type SettingType = 'enum' | 'bool' | 'int' | 'float' | 'string' | 'text' | 'model' | 'time' | 'duration' | 'list' | 'object';
export type SettingStatus = 'ok' | 'restart_required' | 'offline';

export interface SettingOption { value: unknown; label: string; }

export interface SettingItem {
  key: string;
  module: string;
  label: string;
  type: SettingType;
  default: unknown;
  value: unknown;
  group: string;
  help?: string;
  options?: SettingOption[];
  options_source?: string;
  min?: number;
  max?: number;
  unit?: string;
  apply: 'live' | 'restart';
  scope: 'system' | 'user';
  oracle: 'propose' | 'read' | 'none';
  advanced: boolean;
  order: number;
  depends_on?: { key: string; equals?: unknown; not_equals?: unknown };
  row?: string;
  column?: string;
  /** stored | default (system) · profile | client | session | default (user) */
  source: string;
  status?: SettingStatus;
  updated_by?: string | null;
  updated_at?: string | null;
}

export interface PresetGroup {
  module: string;
  group: string;
  active: string;                 // preset id, or "custom"
  presets: { id: string; label: string; help?: string; values: Record<string, unknown> }[];
}

export interface SettingsPage { revision: string; items: SettingItem[]; presets: PresetGroup[]; }

export interface ModuleInfo {
  module: string;
  definitions: number;
  groups?: string[];
  health?: string;                // healthy | degraded | unhealthy | unknown | unregistered …
  version?: string | null;
  service_type?: string | null;
  topology_tags?: string[];
  pending_proposals?: number;
}

export interface ModulesPage { revision: string; modules: ModuleInfo[]; other_services: ModuleInfo[]; }

export interface HistoryRow {
  key: string;
  old_value: unknown;
  new_value: unknown;
  actor?: string | null;
  reason?: string | null;
  created_at?: string | null;
}

export interface Proposal {
  proposal_id: string;
  key: string;
  value: unknown;
  reason?: string;
  proposer: string;
  label?: string;              // setting label (added by Themis)
  status: string;
  created_at?: string;
  expires_at?: string;
}

/** Italian message from a Themis error ({detail}), for toasts. */
export function apiError(e: unknown, fallback = 'Operazione non riuscita'): string {
  if (e instanceof HttpErrorResponse) {
    const d = e.error?.detail;
    if (typeof d === 'string' && d) return d;
    if (e.status === 0) return 'WebUI non raggiungibile';
  }
  return fallback;
}

@Injectable({ providedIn: 'root' })
export class CentralSettingsApi {
  private http = inject(HttpClient);
  private base = '/api/webui/central-settings';

  private get<T>(path: string, query: Record<string, string | null | undefined> = {}) {
    let params = new HttpParams();
    for (const [k, v] of Object.entries(query)) if (v) params = params.set(k, v);
    return firstValueFrom(this.http.get<T>(`${this.base}/${path}`, { params }));
  }
  private k(key: string) { return `key/${encodeURIComponent(key)}`; }

  revision() { return this.get<{ revision: string }>('revision'); }
  modules() { return this.get<ModulesPage>('modules'); }
  items(module?: string | null, q?: string | null) { return this.get<SettingsPage>('items', { module, q }); }
  async options(key: string): Promise<SettingOption[]> {
    return (await this.get<{ options: SettingOption[] }>(`${this.k(key)}/options`))?.options ?? [];
  }
  async history(key: string): Promise<HistoryRow[]> {
    return (await this.get<{ history: HistoryRow[] }>(`${this.k(key)}/history`))?.history ?? [];
  }
  async proposals(): Promise<Proposal[]> {
    return (await this.get<{ proposals: Proposal[] }>('proposals'))?.proposals ?? [];
  }

  set(key: string, value: unknown) {
    return firstValueFrom(this.http.put<{ value: unknown; revision: string }>(`${this.base}/${this.k(key)}`, { value }));
  }
  reset(key: string) {
    return firstValueFrom(this.http.delete<{ value: unknown; revision: string }>(`${this.base}/${this.k(key)}`));
  }
  undo(key: string) {
    return firstValueFrom(this.http.post<{ value: unknown; revision: string }>(`${this.base}/${this.k(key)}/undo`, {}));
  }
  applyPreset(module: string, presetId: string) {
    return firstValueFrom(this.http.post<{ applied: Record<string, unknown> }>(
      `${this.base}/presets/${encodeURIComponent(module)}/${encodeURIComponent(presetId)}/apply`, {}));
  }
  decide(id: string, approve: boolean) {
    return firstValueFrom(this.http.post<{ status: string }>(
      `${this.base}/proposals/${encodeURIComponent(id)}/${approve ? 'approve' : 'reject'}`, {}));
  }
}
