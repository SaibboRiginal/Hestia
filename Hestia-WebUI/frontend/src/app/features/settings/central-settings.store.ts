import { Injectable, computed, inject, signal } from '@angular/core';
import { ToastService } from '../../ui';
import {
  CentralSettingsApi, ModuleInfo, PresetGroup, Proposal, SettingItem, apiError,
} from './central-settings.api';

/** Pretty module names (Hub service names are lowercase ids). */
export function moduleLabel(id: string): string {
  return id ? id.charAt(0).toUpperCase() + id.slice(1) : id;
}

/** True when the setting differs from its declared default. */
export function isModified(i: SettingItem): boolean {
  return i.source !== 'default' && JSON.stringify(i.value) !== JSON.stringify(i.default);
}

/**
 * Impostazioni → Sistema state. Themis is the source of truth: after every change the store
 * reloads what Themis answers (validated value, status), and a cheap revision poll picks up
 * changes made elsewhere (Telegram, an approved proposal, another browser).
 */
@Injectable({ providedIn: 'root' })
export class CentralSettingsStore {
  private api = inject(CentralSettingsApi);
  private toast = inject(ToastService);

  readonly modules = signal<ModuleInfo[]>([]);
  readonly others = signal<ModuleInfo[]>([]);
  readonly items = signal<SettingItem[]>([]);
  readonly presets = signal<PresetGroup[]>([]);
  readonly proposals = signal<Proposal[]>([]);
  readonly selected = signal<string | null>(null);   // null = overview (dashboard)
  readonly query = signal('');
  readonly onlyModified = signal(false);
  readonly showAdvanced = signal(false);
  readonly loading = signal(false);
  readonly offline = signal(false);
  readonly saving = signal<string | null>(null);
  private revision = '';
  private timer: ReturnType<typeof setInterval> | null = null;

  /** Items after the "solo modificate" / "avanzate" filters (search is done by Themis). */
  readonly visible = computed(() => this.items().filter(i =>
    (this.showAdvanced() || !i.advanced || isModified(i)) && (!this.onlyModified() || isModified(i))));

  readonly hiddenAdvanced = computed(() => this.showAdvanced() ? 0 : this.items().filter(i => i.advanced && !isModified(i)).length);

  /** Visible items grouped by module, then by group (search across modules shows several). */
  readonly sections = computed(() => {
    const out: { module: string; groups: { group: string; items: SettingItem[]; presets?: PresetGroup }[] }[] = [];
    for (const i of [...this.visible()].sort((a, b) => a.module.localeCompare(b.module) || a.order - b.order)) {
      let m = out.find(x => x.module === i.module);
      if (!m) out.push(m = { module: i.module, groups: [] });
      let g = m.groups.find(x => x.group === i.group);
      if (!g) m.groups.push(g = { group: i.group, items: [],
        presets: this.presets().find(p => p.module === i.module && p.group === i.group) });
      g.items.push(i);
    }
    return out;
  });

  readonly restartNeeded = computed(() => this.items().filter(i => i.status === 'restart_required'));
  readonly modulesById = computed(() => new Map(this.modules().map(m => [m.module, m])));

  /** Value of any loaded setting (for depends_on). */
  value(key: string): unknown { return this.items().find(i => i.key === key)?.value; }

  enabled(i: SettingItem): boolean {
    const d = i.depends_on;
    if (!d) return true;
    const v = this.value(d.key);
    if (v === undefined) return true;                  // dependency not loaded (other module): don't block
    if ('equals' in d) return JSON.stringify(v) === JSON.stringify(d.equals);
    if ('not_equals' in d) return JSON.stringify(v) !== JSON.stringify(d.not_equals);
    return !!v;
  }

  dependencyLabel(i: SettingItem): string {
    const dep = this.items().find(x => x.key === i.depends_on?.key);
    return dep ? `Attiva solo con «${dep.label}»` : '';
  }

  // ── loading ───────────────────────────────────────────────────────────
  async init(): Promise<void> {
    await Promise.all([this.loadModules(), this.loadItems(), this.loadProposals()]);
    this.startPolling();
  }

  async loadModules(): Promise<void> {
    try {
      const page = await this.api.modules();
      this.modules.set(page.modules ?? []);
      this.others.set(page.other_services ?? []);
      this.revision = page.revision ?? this.revision;
      this.offline.set(false);
    } catch {
      this.offline.set(true);
    }
  }

  async loadItems(): Promise<void> {
    const q = this.query().trim();
    const module = q ? null : this.selected();
    if (!q && !module) { this.items.set([]); this.presets.set([]); return; }
    this.loading.set(true);
    try {
      const page = await this.api.items(module, q || null);
      this.items.set(page.items ?? []);
      this.presets.set(page.presets ?? []);
      this.revision = page.revision ?? this.revision;
      this.offline.set(false);
    } catch {
      this.offline.set(true);
    } finally {
      this.loading.set(false);
    }
  }

  async loadProposals(): Promise<void> {
    try { this.proposals.set(await this.api.proposals()); } catch { /* panel still usable */ }
  }

  async refresh(): Promise<void> {
    await Promise.all([this.loadModules(), this.loadItems(), this.loadProposals()]);
  }

  select(module: string | null): void {
    this.selected.set(module);
    this.query.set('');
    void this.loadItems();
  }

  search(q: string): void {
    this.query.set(q);
    void this.loadItems();
  }

  startPolling(): void {
    if (this.timer) return;
    this.timer = setInterval(async () => {
      if (document.hidden) return;
      try {
        const { revision } = await this.api.revision();
        if (revision && revision !== this.revision) {
          this.revision = revision;
          await this.refresh();
        }
      } catch { /* Themis down: next tick */ }
    }, 15000);
  }

  stopPolling(): void {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
  }

  // ── changes (always the user's) ─────────────────────────────────────
  async set(item: SettingItem, value: unknown): Promise<void> {
    if (JSON.stringify(value) === JSON.stringify(item.value)) return;
    const before = item.value;
    this.saving.set(item.key);
    try {
      await this.api.set(item.key, value);
      await this.loadItems();
      void this.loadModules();
      const restart = item.apply === 'restart';
      this.toast.show(restart ? `${item.label}: salvato, serve il riavvio di ${moduleLabel(item.module)}` : `${item.label}: salvato`,
        restart ? 'warning' : 'success', { label: 'Annulla', run: () => void this.set({ ...item, value }, before) });
    } catch (e) {
      this.toast.error(apiError(e, 'Salvataggio non riuscito'));
      await this.loadItems();
    } finally {
      this.saving.set(null);
    }
  }

  async reset(item: SettingItem): Promise<void> {
    this.saving.set(item.key);
    try {
      await this.api.reset(item.key);
      await this.loadItems();
      this.toast.success(`${item.label}: ripristinato il predefinito`);
    } catch (e) {
      this.toast.error(apiError(e));
    } finally {
      this.saving.set(null);
    }
  }

  async undo(item: SettingItem): Promise<void> {
    try {
      await this.api.undo(item.key);
      await this.loadItems();
      this.toast.success(`${item.label}: modifica annullata`);
    } catch (e) {
      this.toast.error(apiError(e, 'Niente da annullare'));
    }
  }

  async applyPreset(group: PresetGroup, presetId: string): Promise<void> {
    const preset = group.presets.find(p => p.id === presetId);
    if (!preset) return;
    try {
      await this.api.applyPreset(group.module, presetId);
      await this.loadItems();
      this.toast.success(`${group.group}: preset «${preset.label}» applicato`);
    } catch (e) {
      this.toast.error(apiError(e));
      await this.loadItems();
    }
  }

  async decide(p: Proposal, approve: boolean): Promise<void> {
    try {
      await this.api.decide(p.proposal_id, approve);
      this.toast.success(approve ? 'Proposta approvata' : 'Proposta rifiutata');
    } catch (e) {
      this.toast.error(apiError(e, 'Proposta già decisa altrove'));
    }
    await this.refresh();
  }
}
