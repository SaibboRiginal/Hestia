import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { DialogService, DateFieldComponent, ToastService, UI } from '../../ui';
import { PluginsService } from '../plugins/plugins.service';
import { apiError } from './central-settings.api';
import { moduleLabel } from './central-settings.store';
import {
  FORMAT, ImportReport, ModuleExport, RestorePoint, SectionReport, TransferApi, TransferFile, TransferItem, TransferMode,
  decodeFile, encodeFile, fileName,
} from './transfer.api';

/** One row of the tree: a section of a module's data, or its settings (served by Themis). */
interface Sec {
  uid: string;              // `${owner}/${sid}`
  owner: string;            // module that serves it (the module itself, or themis for settings)
  sid: string;
  label: string;
  icon: string;
  count: number | null;
  hasFiles: boolean;
  help?: string;
  missing?: boolean;        // import: the module is not on this Hestia
}
interface Node { module: string; title: string; icon: string; core: boolean; sections: Sec[]; }
interface Pick { on: boolean; keys: string[] | null; }

const SETTINGS = 'themis';
const MODES: { value: TransferMode; label: string; title: string }[] = [
  { value: 'append', label: 'Aggiungi', title: 'Solo le cose nuove; quelle che hai già restano come sono' },
  { value: 'merge', label: 'Unisci', title: 'Nuove + aggiorna quelle già presenti se nel file sono più recenti' },
  { value: 'replace', label: 'Sostituisci', title: 'Vince il file; quello che c’è solo qui viene eliminato (solo nelle sezioni spuntate e intere)' },
];
const OUTCOMES: { key: keyof SectionReport['items']; label: string; tone: string }[] = [
  { key: 'added', label: 'nuovi', tone: 'success' },
  { key: 'updated', label: 'aggiornati', tone: 'info' },
  { key: 'skipped', label: 'ignorati', tone: 'neutral' },
  { key: 'deleted', label: 'eliminati', tone: 'danger' },
  { key: 'problems', label: 'problemi', tone: 'warning' },
];

/**
 * Impostazioni → Esporta e importa (docs/work/2026-10-20-import-export): pick modules → sections → items, download a
 * `.hestia` file; on the other Hestia open it, choose Aggiungi / Unisci / Sostituisci, see the preview, import.
 * A restore point (the same sections as they were) is saved before every import.
 */
@Component({
  selector: 'app-transfer-settings',
  imports: [...UI, DateFieldComponent, DatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="head">
      <hx-segmented [options]="tabs" [(value)]="tab" (changed)="onTab($event)" />
      <span class="hx-grow"></span>
      @if (busy()) { <hx-spinner [size]="16" /> <span class="hx-small hx-muted">{{ busy() }}</span> }
    </div>

    @if (tab() === 'export') {
      <p class="hx-small hx-muted intro">Scegli cosa portare su un altro Hestia: moduli interi, sezioni o singoli elementi.
        Mai chiavi, token o password.</p>
      @if (!nodes().length && !busy()) { <hx-empty icon="download" title="Niente da esportare" /> }
      <div class="tree">
        @for (n of nodes(); track n.module) {
          <div class="mod">
            <div class="row top">
              <input type="checkbox" class="hx-check" [checked]="modState(n) === 'all'" [indeterminate]="modState(n) === 'some'"
                     (change)="toggleModule(n, $any($event.target).checked)" [attr.aria-label]="n.title" />
              <button class="name" (click)="toggleOpen(n.module)">
                <hx-icon [name]="n.icon" [size]="16" /><span>{{ n.title }}</span>
                <hx-icon [name]="opened().has(n.module) ? 'chevron-up' : 'chevron-down'" [size]="14" class="chev" />
              </button>
              <span class="hx-grow"></span>
              <span class="n">{{ moduleCount(n) }}</span>
            </div>
            @if (opened().has(n.module)) {
              @for (s of n.sections; track s.uid) {
                <div class="row sec">
                  <input type="checkbox" class="hx-check" [checked]="pick(s.uid).on" (change)="toggle(s.uid, $any($event.target).checked)"
                         [attr.aria-label]="s.label" />
                  <hx-icon [name]="s.icon" [size]="15" class="si" />
                  <span class="label" [title]="s.help || ''">{{ s.label }}</span>
                  @if (s.hasFiles) { <hx-badge tone="info">file</hx-badge> }
                  <span class="hx-grow"></span>
                  @if (pick(s.uid).keys; as k) { <span class="hx-small accent">{{ k.length }} scelti</span> }
                  <span class="n">{{ s.count ?? '–' }}</span>
                  @if (s.count) { <button hx-btn variant="ghost" size="sm" (click)="openPicker(s)">Scegli</button> }
                </div>
              }
            }
          </div>
        }
      </div>
      <div class="opts">
        <label class="opt"><span>Solo modifiche dal</span><hx-date [(value)]="since" /></label>
        @if (since()) { <button hx-btn variant="ghost" size="sm" icon="x" (click)="since.set('')">Tutto</button> }
        <hx-toggle [(checked)]="includeFiles" label="Includi foto" />
        <span class="hx-grow"></span>
        <button hx-btn variant="primary" icon="download" [disabled]="!selectedCount() || !!busy()" (click)="doExport()">Esporta</button>
      </div>
    }

    @if (tab() === 'import') {
      @if (!file()) {
        <label class="drop" (dragover)="$event.preventDefault()" (drop)="onDrop($event)">
          <hx-icon name="upload" [size]="22" />
          <span>Scegli o trascina qui un file <b>.hestia</b></span>
          <input type="file" accept=".hestia,.json,.gz" (change)="onFile($any($event.target).files?.[0])" hidden />
        </label>
      } @else {
        <div class="filebar">
          <hx-icon name="file" [size]="16" /><b>{{ fileLabel() }}</b>
          <span class="hx-small hx-muted">esportato il {{ file()!.exported_at | date:'d/M/yyyy HH:mm' }}
            @if (file()!.since) { · solo modifiche dal {{ file()!.since | date:'d/M/yyyy' }} }</span>
          <span class="hx-grow"></span>
          <button hx-btn variant="ghost" size="sm" icon="x" (click)="clearFile()">Chiudi</button>
        </div>
        <div class="opts">
          <span class="hx-small">Modo</span>
          <hx-segmented [options]="modes" [(value)]="mode" (changed)="report.set(null)" />
          <span class="hx-small hx-muted">{{ modeHelp() }}</span>
        </div>
        <div class="tree">
          @for (n of importNodes(); track n.module) {
            <div class="mod">
              <div class="row top">
                <input type="checkbox" class="hx-check" [checked]="modState(n) === 'all'" [indeterminate]="modState(n) === 'some'"
                       [disabled]="allMissing(n)" (change)="toggleModule(n, $any($event.target).checked)" [attr.aria-label]="n.title" />
                <span class="name static"><hx-icon [name]="n.icon" [size]="16" /><span>{{ n.title }}</span></span>
              </div>
              @for (s of n.sections; track s.uid) {
                <div class="row sec" [class.off]="s.missing">
                  <input type="checkbox" class="hx-check" [checked]="pick(s.uid).on" [disabled]="s.missing"
                         (change)="toggle(s.uid, $any($event.target).checked)" [attr.aria-label]="s.label" />
                  <hx-icon [name]="s.icon" [size]="15" class="si" />
                  <span class="label">{{ s.label }}</span>
                  @if (s.missing) { <hx-badge tone="warning">non presente qui</hx-badge> }
                  <span class="hx-grow"></span>
                  <span class="n">{{ s.count }}</span>
                  @if (!s.missing) {
                    <select class="hx-select mini" [value]="sectionMode(s.uid)" (change)="setSectionMode(s.uid, $any($event.target).value)"
                            title="Modo di questa sezione">
                      <option value="">come sopra</option>
                      @for (m of modes; track m.value) { <option [value]="m.value">{{ m.label }}</option> }
                    </select>
                  }
                </div>
                @if (sectionReport(s); as r) {
                  <div class="rep">
                    @for (o of outcomes; track o.key) {
                      @if (r[o.key]) {
                        <button class="chip" [attr.data-tone]="o.tone" (click)="toggleDetail(s.uid + ':' + o.key)">{{ r[o.key] }} {{ o.label }}</button>
                      }
                    }
                    @if (!r.added && !r.updated && !r.deleted && !r.skipped && !r.problems) { <span class="hx-small hx-muted">nessuna modifica</span> }
                    @if (r.partial && sectionModeOf(s.uid) === 'replace') { <span class="hx-small hx-muted">sezione parziale: niente eliminazioni</span> }
                  </div>
                  @for (o of outcomes; track o.key) {
                    @if (detail().has(s.uid + ':' + o.key)) {
                      <ul class="det">@for (t of r.items[o.key]; track $index) { <li>{{ t }}</li> }
                        @if (r[o.key] > r.items[o.key].length) { <li class="hx-muted">… e altri {{ r[o.key] - r.items[o.key].length }}</li> }</ul>
                    }
                  }
                }
              }
            </div>
          }
        </div>
        <div class="opts">
          @if (reportDone()) {
            <span class="ok"><hx-icon name="check-circle" [size]="16" /> Importazione completata</span>
          }
          <span class="hx-grow"></span>
          <button hx-btn variant="secondary" icon="eye" [disabled]="!selectedCount() || !!busy()" (click)="preview()">Anteprima</button>
          <button hx-btn variant="primary" icon="upload" [disabled]="!report() || reportDone() || !!busy()" (click)="doImport()">Importa</button>
        </div>
      }
    }

    @if (tab() === 'restore') {
      <p class="hx-small hx-muted intro">Prima di ogni importazione Hestia salva com'erano le sezioni coinvolte.
        Ripristina = le riapre nell'importazione con «Sostituisci». Ne tiene {{ keep() }} (impostazione «Punti di ripristino da tenere»).</p>
      @if (!points().length && !busy()) { <hx-empty icon="history" title="Nessun punto di ripristino" /> }
      @for (p of points(); track p.id) {
        <div class="row point">
          <hx-icon name="history" [size]="16" class="si" />
          <span class="label">{{ p.created_at | date:'d/M/yyyy HH:mm' }}</span>
          <span class="hx-small hx-muted hx-truncate">{{ p.label }} · {{ moduleNames(p.modules) }}</span>
          <span class="hx-grow"></span>
          <button hx-btn variant="secondary" size="sm" icon="undo" (click)="openRestore(p)">Ripristina</button>
          <button hx-btn variant="ghost" size="sm" icon="trash" iconOnly title="Elimina" (click)="deletePoint(p)"></button>
        </div>
      }
    }

    <hx-modal [open]="!!picker()" [title]="picker()?.title || ''" size="md" (closed)="picker.set(null)">
      @if (picker(); as p) {
        <input class="hx-input" type="search" placeholder="Cerca" [value]="p.q" (input)="searchPicker($any($event.target).value)" />
        <div class="plist">
          @for (it of p.items; track it.key) {
            <label class="pitem">
              <input type="checkbox" class="hx-check" [checked]="p.chosen.has(it.key)" (change)="pickItem(it.key, $any($event.target).checked)" />
              <span class="hx-grow"><span class="pt">{{ it.title }}</span>
                @if (it.subtitle) { <span class="hx-small hx-muted"> · {{ it.subtitle }}</span> }</span>
            </label>
          }
          @if (!p.items.length) { <span class="hx-small hx-muted">Nessun elemento</span> }
        </div>
      }
      <div footer>
        <button hx-btn variant="ghost" (click)="clearPicker()">Tutta la sezione</button>
        <button hx-btn variant="primary" (click)="applyPicker()">Usa {{ picker()?.chosen?.size || 0 }} scelti</button>
      </div>
    </hx-modal>
  `,
  styles: [`
    :host { display: flex; flex-direction: column; gap: 12px; max-width: 860px; }
    .head { display: flex; align-items: center; gap: 10px; }
    .intro { margin: 0; }
    .tree { display: flex; flex-direction: column; gap: 6px; }
    .mod { border: 1px solid var(--border); border-radius: var(--radius-md); padding: 4px 8px; background: var(--surface); }
    .row { display: flex; align-items: center; gap: 9px; min-height: 34px; }
    .row.sec { padding-left: 26px; }
    .row.off { opacity: .55; }
    .name { display: inline-flex; align-items: center; gap: 8px; font-weight: 500; color: var(--text); }
    .chev { color: var(--text-3); }
    .si { color: var(--text-3); }
    .label { font-size: 13.5px; }
    .n { font-size: 12px; color: var(--text-3); font-variant-numeric: tabular-nums; min-width: 24px; text-align: right; }
    .accent { color: var(--accent); }
    .opts { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
    .opt { display: inline-flex; align-items: center; gap: 8px; font-size: 13px; }
    .drop { display: flex; flex-direction: column; align-items: center; gap: 8px; padding: 36px; cursor: pointer;
            border: 1.5px dashed var(--border); border-radius: var(--radius-lg, 12px); color: var(--text-2); }
    .drop:hover { border-color: var(--accent); color: var(--accent); }
    .filebar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    .mini { height: 28px; font-size: 12px; width: auto; padding: 0 26px 0 8px; }
    .rep { display: flex; gap: 6px; flex-wrap: wrap; padding: 0 0 6px 50px; align-items: center; }
    .chip { font-size: 12px; padding: 2px 9px; border-radius: 999px; background: var(--surface-2); color: var(--text-2); }
    .chip[data-tone=success] { color: var(--success); background: color-mix(in srgb, var(--success) 12%, transparent); }
    .chip[data-tone=info] { color: var(--info, var(--accent)); background: color-mix(in srgb, var(--info, var(--accent)) 12%, transparent); }
    .chip[data-tone=danger] { color: var(--danger); background: color-mix(in srgb, var(--danger) 12%, transparent); }
    .chip[data-tone=warning] { color: var(--warning); background: color-mix(in srgb, var(--warning) 14%, transparent); }
    .det { margin: 0 0 8px 50px; padding-left: 16px; font-size: 12.5px; color: var(--text-2); max-height: 220px; overflow: auto; }
    .ok { display: inline-flex; align-items: center; gap: 6px; color: var(--success); font-size: 13px; }
    .point { border-bottom: 1px solid var(--border); padding: 4px 0; }
    .plist { display: flex; flex-direction: column; max-height: 50vh; overflow: auto; margin-top: 10px; }
    .pitem { display: flex; align-items: center; gap: 9px; padding: 6px 4px; border-radius: var(--radius-sm, 6px); cursor: pointer; }
    .pitem:hover { background: var(--surface-2); }
    .pt { font-size: 13.5px; }
    @media (max-width: 600px) { .row.sec { padding-left: 10px; } .rep, .det { padding-left: 10px; margin-left: 10px; } }
  `],
})
export class TransferSettingsComponent implements OnInit {
  private api = inject(TransferApi);
  private plugins = inject(PluginsService);
  private toast = inject(ToastService);
  private dialogs = inject(DialogService);

  readonly tabs = [
    { value: 'export', label: 'Esporta', icon: 'download' },
    { value: 'import', label: 'Importa', icon: 'upload' },
    { value: 'restore', label: 'Ripristino', icon: 'history' },
  ];
  readonly modes = MODES;
  readonly outcomes = OUTCOMES;
  readonly tab = signal<string | null>('export');
  readonly busy = signal('');

  // export
  readonly nodes = signal<Node[]>([]);
  readonly opened = signal(new Set<string>());
  readonly picks = signal<Record<string, Pick>>({});
  readonly since = signal('');
  readonly includeFiles = signal(false);
  readonly picker = signal<{ sec: Sec; title: string; q: string; items: TransferItem[]; chosen: Set<string> } | null>(null);

  // import
  readonly here = signal<Set<string>>(new Set());
  readonly file = signal<TransferFile | null>(null);
  readonly fileLabel = signal('');
  readonly mode = signal<TransferMode | null>('merge');
  readonly sectionModes = signal<Record<string, TransferMode>>({});
  readonly report = signal<Record<string, ImportReport> | null>(null);
  readonly reportDone = signal(false);
  readonly detail = signal(new Set<string>());

  // restore
  readonly points = signal<RestorePoint[]>([]);
  readonly keep = signal(5);

  readonly importNodes = computed(() => this.buildImportNodes(this.file(), this.here()));
  readonly currentNodes = computed(() => this.tab() === 'import' ? this.importNodes() : this.nodes());
  readonly selectedCount = computed(() =>
    this.currentNodes().flatMap(n => n.sections).filter(s => !s.missing && this.picks()[s.uid]?.on).length);
  readonly modeHelp = computed(() => MODES.find(m => m.value === this.mode())?.title ?? '');

  ngOnInit() { void this.loadExport(); }

  onTab(t: string) {
    this.picks.set({});
    if (t === 'export') void this.loadExport();
    if (t === 'import') { void this.loadHere(); this.selectAllImport(); }
    if (t === 'restore') void this.loadPoints();
  }

  // ── tree helpers (shared by export and import) ────────────────────────────
  private meta(module: string) {
    const m = this.plugins.modules().get(module);
    if (module === SETTINGS) return { title: 'Personali', icon: 'user', core: true };
    return { title: m?.title || moduleLabel(module), icon: m?.icon || 'puzzle', core: m?.kind === 'core' };
  }
  private sortNodes(nodes: Node[]): Node[] {
    return nodes.sort((a, b) => Number(a.core) - Number(b.core) || a.title.localeCompare(b.title));
  }
  pick(uid: string): Pick { return this.picks()[uid] ?? { on: false, keys: null }; }
  toggle(uid: string, on: boolean) {
    this.picks.update(p => ({ ...p, [uid]: { on, keys: on ? (p[uid]?.keys ?? null) : null } }));
    this.report.set(null);
  }
  toggleModule(n: Node, on: boolean) {
    this.picks.update(p => {
      const next = { ...p };
      for (const s of n.sections) if (!s.missing) next[s.uid] = { on, keys: null };
      return next;
    });
    this.report.set(null);
  }
  modState(n: Node): 'all' | 'some' | 'none' {
    const live = n.sections.filter(s => !s.missing);
    const on = live.filter(s => this.pick(s.uid).on);
    return !on.length ? 'none' : on.length === live.length && on.every(s => !this.pick(s.uid).keys) ? 'all' : 'some';
  }
  allMissing(n: Node) { return n.sections.every(s => s.missing); }
  moduleCount(n: Node) { return n.sections.reduce((a, s) => a + (s.count ?? 0), 0); }
  toggleOpen(module: string) {
    this.opened.update(o => { const n = new Set(o); n.has(module) ? n.delete(module) : n.add(module); return n; });
  }
  moduleNames(mods?: string[] | null) { return (mods ?? []).map(m => this.meta(m).title).join(', '); }

  // ── export ────────────────────────────────────────────────────────────────
  private async loadExport() {
    this.busy.set('Carico i moduli…');
    try {
      const { modules } = await this.api.modules();
      this.here.set(new Set(modules.map(m => m.module)));
      const described = await Promise.all(modules.map(m => this.api.describe(m.module).catch(() => null)));
      const byModule = new Map<string, Node>();
      const node = (module: string) => {
        if (!byModule.has(module)) byModule.set(module, { module, ...this.meta(module), sections: [] });
        return byModule.get(module)!;
      };
      for (const d of described) {
        if (!d) continue;
        for (const s of d.sections) {
          if (d.module === SETTINGS) {
            if (!s.count) continue;
            node(s.id).sections.push({ uid: `${SETTINGS}/${s.id}`, owner: SETTINGS, sid: s.id, label: s.label, icon: 'settings',
              count: s.count, hasFiles: false });
          } else {
            node(d.module).sections.unshift({ uid: `${d.module}/${s.id}`, owner: d.module, sid: s.id, label: s.label,
              icon: s.icon || 'list', count: s.count, hasFiles: s.has_files, help: s.help });
          }
        }
      }
      for (const n of byModule.values()) {   // settings last inside each module
        n.sections.sort((a, b) => Number(a.owner === SETTINGS && a.sid !== SETTINGS) - Number(b.owner === SETTINGS && b.sid !== SETTINGS));
      }
      this.nodes.set(this.sortNodes([...byModule.values()].filter(n => n.sections.length)));
    } catch (e) {
      this.toast.error(apiError(e, 'Moduli non raggiungibili'));
    } finally { this.busy.set(''); }
  }

  async openPicker(s: Sec) {
    const chosen = new Set(this.pick(s.uid).keys ?? []);
    const title = `${this.meta(s.owner === SETTINGS ? s.sid : s.owner).title} · ${s.label}`;
    this.picker.set({ sec: s, title, q: '', items: [], chosen });
    await this.searchPicker('');
  }
  async searchPicker(q: string) {
    const p = this.picker();
    if (!p) return;
    try {
      const r = await this.api.items(p.sec.owner, p.sec.sid, q);
      this.picker.set({ ...p, q, items: r.items });
    } catch (e) { this.toast.error(apiError(e)); }
  }
  pickItem(key: string, on: boolean) {
    const p = this.picker();
    if (!p) return;
    const chosen = new Set(p.chosen);
    on ? chosen.add(key) : chosen.delete(key);
    this.picker.set({ ...p, chosen });
  }
  applyPicker() {
    const p = this.picker();
    if (!p) return;
    this.picks.update(x => ({ ...x, [p.sec.uid]: p.chosen.size ? { on: true, keys: [...p.chosen] } : { on: false, keys: null } }));
    this.picker.set(null);
  }
  clearPicker() {
    const p = this.picker();
    if (!p) return;
    this.picks.update(x => ({ ...x, [p.sec.uid]: { on: true, keys: null } }));
    this.picker.set(null);
  }

  /** Per owner: `{sid: {keys?}}` of the ticked sections. */
  private grouped(nodes: Node[], withKeys = true): Map<string, Record<string, { keys?: string[] }>> {
    const out = new Map<string, Record<string, { keys?: string[] }>>();
    for (const s of nodes.flatMap(n => n.sections)) {
      const p = this.pick(s.uid);
      if (!p.on || s.missing) continue;
      const g = out.get(s.owner) ?? {};
      g[s.sid] = withKeys && p.keys ? { keys: p.keys } : {};
      out.set(s.owner, g);
    }
    return out;
  }

  private async buildFile(groups: Map<string, Record<string, { keys?: string[] }>>, since: string | null,
                          includeFiles: boolean): Promise<TransferFile> {
    const file: TransferFile = { hestia: 'transfer', format: FORMAT, exported_at: new Date().toISOString(), since,
      include_files: includeFiles, modules: {}, files: {} };
    for (const [owner, sections] of groups) {
      this.busy.set(`Esporto ${this.meta(owner).title}…`);
      const out = await this.api.export(owner, { sections, since, include_files: includeFiles });
      file.modules[owner] = out;
      for (const id of out.files ?? []) {
        const f = await this.api.file(owner, id);
        (file.files![owner] ??= {})[id] = { mime: f.mime, sha256: f.sha256, meta: f.meta, data_b64: f.data_b64 };
      }
    }
    return file;
  }

  async doExport() {
    try {
      const since = this.since() ? new Date(`${this.since()}T00:00:00`).toISOString() : null;
      const file = await this.buildFile(this.grouped(this.nodes()), since, this.includeFiles());
      const blob = await encodeFile(file);
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = fileName();
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 10_000);
      const pulled = Object.values(file.modules).reduce((n, m) => n + Object.values(m.pulled ?? {}).reduce((k, v) => k + v.length, 0), 0);
      this.toast.success(pulled ? `File pronto (aggiunti ${pulled} elementi collegati)` : 'File pronto');
    } catch (e) {
      this.toast.error(apiError(e, 'Esportazione non riuscita'));
    } finally { this.busy.set(''); }
  }

  // ── import ────────────────────────────────────────────────────────────────
  private async loadHere() {
    try { this.here.set(new Set((await this.api.modules()).modules.map(m => m.module))); } catch { /* keeps the last list */ }
  }

  private buildImportNodes(file: TransferFile | null, here: Set<string>): Node[] {
    if (!file) return [];
    const byModule = new Map<string, Node>();
    const node = (module: string) => {
      if (!byModule.has(module)) byModule.set(module, { module, ...this.meta(module), sections: [] });
      return byModule.get(module)!;
    };
    for (const [owner, payload] of Object.entries(file.modules ?? {})) {
      for (const [sid, block] of Object.entries(payload.sections ?? {})) {
        const settings = owner === SETTINGS;
        if (settings && !block.records?.length) continue;   // a module whose settings were never changed: nothing to show
        node(settings ? sid : owner).sections.push({
          uid: `${owner}/${sid}`, owner, sid, label: block.label || sid, icon: settings ? 'settings' : 'list',
          count: block.records?.length ?? 0, hasFiles: false,
          missing: !here.has(owner),     // a setting of a module missing here is reported by Themis in the preview
        });
      }
    }
    return this.sortNodes([...byModule.values()]);
  }

  private selectAllImport() {
    const p: Record<string, Pick> = {};
    for (const s of this.importNodes().flatMap(n => n.sections)) if (!s.missing) p[s.uid] = { on: true, keys: null };
    this.picks.set(p);
  }

  async onFile(f?: File | null) {
    if (!f) return;
    try {
      const file = await decodeFile(f);
      this.file.set(file);
      this.fileLabel.set(f.name);
      this.reset();
      await this.loadHere();
      this.selectAllImport();
    } catch (e) {
      this.toast.error(e instanceof Error ? e.message : 'File non leggibile');
    }
  }
  onDrop(ev: DragEvent) { ev.preventDefault(); void this.onFile(ev.dataTransfer?.files?.[0]); }
  clearFile() { this.file.set(null); this.reset(); }
  private reset() { this.report.set(null); this.reportDone.set(false); this.detail.set(new Set()); this.sectionModes.set({}); }

  sectionMode(uid: string) { return this.sectionModes()[uid] ?? ''; }
  sectionModeOf(uid: string): TransferMode { return this.sectionModes()[uid] ?? this.mode() ?? 'merge'; }
  setSectionMode(uid: string, value: string) {
    this.sectionModes.update(m => { const n = { ...m }; value ? n[uid] = value as TransferMode : delete n[uid]; return n; });
    this.report.set(null);
  }
  sectionReport(s: Sec): SectionReport | null { return this.report()?.[s.owner]?.sections?.[s.sid] ?? null; }
  toggleDetail(id: string) { this.detail.update(d => { const n = new Set(d); n.has(id) ? n.delete(id) : n.add(id); return n; }); }

  private body(owner: string, sections: Record<string, object>, dryRun: boolean, filesMap?: Record<string, string>) {
    const modes: Record<string, TransferMode> = {};
    for (const sid of Object.keys(sections)) {
      const m = this.sectionModes()[`${owner}/${sid}`];
      if (m) modes[sid] = m;
    }
    return { data: this.file()!.modules[owner], mode: this.mode() ?? 'merge' as TransferMode, modes, dry_run: dryRun,
      sections, files_map: filesMap };
  }

  async preview() {
    this.busy.set('Anteprima…');
    this.reportDone.set(false);
    try {
      const out: Record<string, ImportReport> = {};
      for (const [owner, sections] of this.grouped(this.importNodes(), false)) {
        out[owner] = await this.api.import(owner, this.body(owner, sections, true));
      }
      this.report.set(out);
    } catch (e) {
      this.toast.error(apiError(e, 'Anteprima non riuscita'));
    } finally { this.busy.set(''); }
  }

  async doImport() {
    const groups = this.grouped(this.importNodes(), false);
    const deletes = Object.values(this.report() ?? {}).reduce((n, r) => n + (r.totals?.['deleted'] ?? 0), 0);
    const ok = await this.dialogs.confirm('Importare?',
      deletes ? `Verranno eliminati ${deletes} elementi. Prima salvo un punto di ripristino.` : 'Prima salvo un punto di ripristino.',
      'Importa', deletes > 0);
    if (!ok) return;
    try {
      this.busy.set('Salvo il punto di ripristino…');
      const before = await this.buildFile(groups, null, false);
      await this.api.saveRestorePoint({ label: `Prima di importare ${this.fileLabel()}`, modules: [...groups.keys()], file: before });
      const out: Record<string, ImportReport> = {};
      for (const [owner, sections] of groups) {
        const map: Record<string, string> = {};
        const files = this.file()!.files?.[owner] ?? {};
        const ids = Object.keys(files);
        for (const [i, id] of ids.entries()) {
          this.busy.set(`Carico i file di ${this.meta(owner).title} (${i + 1}/${ids.length})…`);
          const r = await this.api.upload(owner, { id, ...files[id] });
          map[r.old_id] = r.new_id;
        }
        this.busy.set(`Importo ${this.meta(owner).title}…`);
        out[owner] = await this.api.import(owner, this.body(owner, sections, false, map));
      }
      this.report.set(out);
      this.reportDone.set(true);
      this.toast.success('Importazione completata');
    } catch (e) {
      this.toast.error(apiError(e, 'Importazione non riuscita: puoi tornare indietro da «Ripristino»'));
    } finally { this.busy.set(''); }
  }

  // ── restore points ────────────────────────────────────────────────────────
  private async loadPoints() {
    this.busy.set('Carico…');
    try {
      const r = await this.api.restorePoints();
      this.points.set(r.items);
      this.keep.set(r.keep);
    } catch (e) { this.toast.error(apiError(e)); } finally { this.busy.set(''); }
  }

  async openRestore(p: RestorePoint) {
    try {
      const file = await this.api.restorePoint(p.id);
      this.tab.set('import');
      this.file.set(file);
      this.fileLabel.set('Punto di ripristino');
      this.reset();
      this.mode.set('replace');
      await this.loadHere();
      this.selectAllImport();
    } catch (e) { this.toast.error(apiError(e)); }
  }

  async deletePoint(p: RestorePoint) {
    if (!await this.dialogs.confirm('Eliminare il punto di ripristino?', '', 'Elimina', true)) return;
    try { await this.api.deleteRestorePoint(p.id); this.points.update(l => l.filter(x => x.id !== p.id)); }
    catch (e) { this.toast.error(apiError(e)); }
  }
}
