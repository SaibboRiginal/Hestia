import { Injectable, computed, inject, signal } from '@angular/core';
import { DialogService, ToastService } from '../../ui';
import { PluginsService } from './plugins.service';
import { QuickActionDef, QuickChipView } from './plugins.types';

const fill = (path: string, id: string) => path.replace(/\{id\}/g, encodeURIComponent(id));

/**
 * One-tap quick actions (SPEC §4.2b), drawn by the WebUI itself (no bundle load): static actions are one chip,
 * dynamic ones ask their `source` for the chips of the moment. Shared by the Home strip and the Ctrl+K palette.
 */
@Injectable({ providedIn: 'root' })
export class QuickActionsService {
  private plugins = inject(PluginsService);
  private toasts = inject(ToastService);
  private dialogs = inject(DialogService);

  readonly chips = signal<QuickChipView[]>([]);
  readonly loading = signal(false);
  readonly busy = signal<string>('');
  private loadedFor = '';

  /** Pinned first (in pin order), then favourites, then what is due (todo/late), then the rest. */
  readonly sorted = computed(() => {
    const pins = this.plugins.quickPins();
    const rank = (c: QuickChipView) => {
      const p = pins.indexOf(c.key);
      if (p >= 0) return p;
      if (c.favorite) return 1000;
      if (c.state === 'late') return 2000;
      if (c.state === 'todo') return 2100;
      return 3000 + c.action.order;
    };
    return [...this.chips()].sort((a, b) => rank(a) - rank(b) || a.label.localeCompare(b.label));
  });
  /** What Home shows before "Altre": pins, favourites, due today; everything when nothing qualifies. */
  readonly primary = computed(() => {
    const pins = this.plugins.quickPins();
    const main = this.sorted().filter(c => pins.includes(c.key) || c.favorite || c.state === 'todo' || c.state === 'late');
    return main.length ? main : this.sorted().slice(0, 8);
  });
  readonly secondary = computed(() => { const main = new Set(this.primary()); return this.sorted().filter(c => !main.has(c)); });

  async reload(force = false): Promise<void> {
    const actions = this.plugins.quickActions();
    const sig = actions.map(a => `${a.id}:${a.online}`).join('|');
    if (!force && sig === this.loadedFor && this.chips().length) return;
    this.loadedFor = sig;
    this.loading.set(true);
    const lists = await Promise.all(actions.map(a => this.chipsOf(a)));
    this.chips.set(lists.flat());
    this.loading.set(false);
  }

  private async chipsOf(a: QuickActionDef): Promise<QuickChipView[]> {
    if (!a.source) return [{ key: a.id, action: a, chipId: '', label: a.label, icon: a.icon, favorite: a.favorite }];
    if (!a.online) return [];
    const r = await this.plugins.call<unknown>(a.module, 'GET', a.source);
    if (!r.ok) return [];
    const items = (Array.isArray(r.data) ? r.data : (r.data as { items?: unknown[] })?.items ?? []) as Array<Record<string, unknown>>;
    return items.filter(i => i && i['id'] != null).map(i => ({
      key: `${a.id}:${i['id']}`, action: a, chipId: String(i['id']), label: String(i['label'] ?? a.label),
      icon: (i['icon'] as string) || a.icon, state: i['state'] as QuickChipView['state'], hint: i['hint'] as string | undefined,
      favorite: !!i['favorite'],
    }));
  }

  /** Runs a chip (optionally with {date, note, …params}); toast with «Annulla» when the action has an undo. */
  async run(chip: QuickChipView, body?: Record<string, unknown>): Promise<boolean> {
    const a = chip.action;
    if (a.confirm && !(await this.dialogs.confirm(chip.label, a.confirm, 'Conferma'))) return false;
    this.busy.set(chip.key);
    const r = await this.plugins.call(a.module, a.method, fill(a.path, chip.chipId), { body: body ?? (a.method === 'GET' ? undefined : {}) });
    this.busy.set('');
    if (!r.ok) {
      this.toasts.error(r.error === 'offline' ? 'Sei offline: riprova quando torni in linea'
        : r.error === 'unreachable' ? `${this.plugins.modules().get(a.module)?.title ?? a.module} non raggiungibile` : 'Non sono riuscito a farlo');
      return false;
    }
    const msg = (r.data as { message?: string } | null)?.message || chip.label;
    const prev = chip.state;
    this.chips.update(list => list.map(c => c.key === chip.key && c.chipId ? { ...c, state: 'done' } : c));
    this.toasts.show(msg, 'success', a.undo ? { label: 'Annulla', run: () => void this.undo(chip, prev) } : undefined, a.undo ? 7000 : 4500);
    this.plugins.emit(a.module, 'refresh');
    void this.reload(true);
    return true;
  }

  private async undo(chip: QuickChipView, prev?: QuickChipView['state']): Promise<void> {
    const u = chip.action.undo;
    if (!u) return;
    const r = await this.plugins.call(chip.action.module, u.method, fill(u.path, chip.chipId));
    if (!r.ok) { this.toasts.error('Annullamento non riuscito'); return; }
    this.chips.update(list => list.map(c => c.key === chip.key ? { ...c, state: prev } : c));
    this.toasts.show('Annullato', 'info');
    this.plugins.emit(chip.action.module, 'refresh');
    void this.reload(true);
  }
}
