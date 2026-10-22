import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { BadgeComponent, ButtonComponent, EmptyStateComponent, IconComponent, SegmentedComponent, SegmentOption, SpinnerComponent, Tone, ToggleComponent } from '../../ui';
import { ModuleInfo, PresetGroup, Proposal, SettingItem } from './central-settings.api';
import { CentralSettingsStore, isModified, moduleLabel } from './central-settings.store';
import { SettingControlComponent } from './setting-control.component';
import { SettingRowComponent, showValue } from './setting-row.component';
import { PluginOutletComponent } from '../plugins/plugin-outlet.component';
import { PluginsService } from '../plugins/plugins.service';

export const HEALTH: Record<string, { tone: Tone; label: string }> = {
  healthy: { tone: 'success', label: 'attivo' },
  degraded: { tone: 'warning', label: 'con problemi' },
  unavailable: { tone: 'danger', label: 'non risponde' },
  unregistered: { tone: 'neutral', label: 'non registrato' },
  unknown: { tone: 'neutral', label: 'stato sconosciuto' },
};

interface Grid { rows: string[]; columns: string[]; cell: Map<string, SettingItem>; }

/**
 * Impostazioni → Sistema content: every module's settings (Themis). Overview = module status cards
 * ("mezza dashboard"); a module = its groups, presets, settings; a search shows every match.
 * The sidebar and the search box live in the page (shared with Personali).
 */
@Component({
  selector: 'app-system-settings',
  imports: [BadgeComponent, ButtonComponent, EmptyStateComponent, IconComponent, SegmentedComponent, SpinnerComponent,
            ToggleComponent, SettingRowComponent, SettingControlComponent, PluginOutletComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="main">
      @if (store.offline()) {
        <div class="hx-notices"><div class="hx-notice" data-level="error"><hx-icon name="alert" [size]="15" />
          <span class="nt">Impostazioni non raggiungibili</span><span class="nd">Themis non risponde: riprovo da solo.</span></div></div>
      }

      @if (!store.query()) { @for (p of store.proposals(); track p.proposal_id) {
        <div class="proposal">
          <hx-icon name="sparkle" [size]="16" />
          <div class="hx-grow">
            <div class="pt">{{ proposer(p) }} propone: <b>{{ labelOf(p) }}</b> → <b>{{ proposedValue(p) }}</b></div>
            @if (p.reason) { <div class="pd">{{ p.reason }}</div> }
          </div>
          <button hx-btn size="sm" variant="primary" icon="check" (click)="store.decide(p, true)">Approva</button>
          <button hx-btn size="sm" variant="ghost" (click)="store.decide(p, false)">Rifiuta</button>
        </div>
      } }

      @if (!store.selected() && !store.query()) {
        <div class="cards">
          @for (m of store.modules(); track m.module) {
            <button class="card" (click)="store.select(m.module)">
              <div class="ch"><span class="cn">{{ name(m.module) }}</span>
                <hx-badge [tone]="health(m).tone" dot>{{ health(m).label }}</hx-badge></div>
              <div class="cm">{{ m.definitions }} impostazioni@if (m.groups?.length) { · {{ m.groups!.join(', ') }} }</div>
              <div class="cf">
                @if (m.version) { <span>v{{ m.version }}</span> }
                @if (m.pending_proposals) { <hx-badge tone="accent">{{ m.pending_proposals === 1 ? '1 proposta' : m.pending_proposals + ' proposte' }}</hx-badge> }
              </div>
            </button>
          }
        </div>
        @if (store.others().length) {
          <h4 class="sub">Altri servizi (ancora senza impostazioni)</h4>
          <div class="others">
            @for (m of store.others(); track m.module) {
              <hx-badge [tone]="health(m).tone" dot [title]="health(m).label">{{ name(m.module) }}</hx-badge>
            }
          </div>
        }
        @if (!store.modules().length && !store.offline()) {
          <hx-empty icon="settings" title="Nessun modulo ha ancora dichiarato impostazioni">
            I moduli si registrano da soli all'avvio.
          </hx-empty>
        }
      } @else {
        <div class="bar">
          <div class="hx-grow">
            @if (store.query()) { <h3>Sistema</h3> }
            @else { @if (current(); as m) {
              <h3>{{ name(m.module) }} <hx-badge [tone]="health(m).tone" dot>{{ health(m).label }}</hx-badge></h3>
            } }
          </div>
          <hx-toggle label="Solo modificate" [checked]="store.onlyModified()" (changed)="store.onlyModified.set($event)" />
          <hx-toggle [label]="advancedLabel()" [checked]="store.showAdvanced()" (changed)="store.showAdvanced.set($event)" />
        </div>

        @if (store.restartNeeded().length) {
          <div class="hx-notices"><div class="hx-notice" data-level="warning"><hx-icon name="refresh" [size]="15" />
            <span class="nt">Riavvio necessario</span>
            <span class="nd">{{ store.restartNeeded().length === 1 ? '1 valore salvato vale' : store.restartNeeded().length + ' valori salvati valgono' }} dal prossimo riavvio del modulo.</span></div></div>
        }

        @if (store.loading() && !store.items().length) { <div class="center"><hx-spinner /></div> }
        @else if (!store.sections().length) {
          <hx-empty icon="search" title="Niente da mostrare">
            @if (store.onlyModified()) { Nessuna impostazione modificata qui. }
            @else if (store.hiddenAdvanced()) { Ci sono {{ store.hiddenAdvanced() }} impostazioni avanzate: attiva «Avanzate». }
            @else { Nessuna impostazione di sistema trovata. }
          </hx-empty>
        }

        @for (s of store.sections(); track s.module) {
          @if (store.query()) {
            <button class="modhead" (click)="store.select(s.module)">{{ name(s.module) }} <hx-icon name="chevron-right" [size]="14" /></button>
          }
          @for (g of s.groups; track g.group) {
            <div class="group">
              <div class="gh">
                <h4>{{ g.group }}</h4>
                @if (g.presets; as pg) {
                  <hx-segmented [options]="presetOptions(pg)" [value]="pg.active" (changed)="pickPreset(pg, $event)" />
                }
              </div>
              @if (g.presets; as pg) { @if (presetHelp(pg); as h) { <p class="ph">{{ h }}</p> } }

              @if (grid(g.items); as t) {
                <div class="grid-wrap">
                  <table class="grid">
                    <thead><tr><th></th>@for (c of t.columns; track c) { <th>{{ c }}</th> }</tr></thead>
                    <tbody>
                      @for (r of t.rows; track r) {
                        <tr>
                          <th scope="row">{{ r }}</th>
                          @for (c of t.columns; track c) {
                            <td>
                              @if (t.cell.get(r + '|' + c); as it) {
                                <div class="cell" [title]="it.help || it.label">
                                  <hx-setting-control [item]="it" [compact]="true" [disabled]="!store.enabled(it) || store.saving() === it.key"
                                                      (commit)="store.set(it, $event)" />
                                  @if (modified(it)) {
                                    <button class="rst" (click)="store.reset(it)" [title]="'Ripristina predefinito: ' + show(it, it.default)">
                                      <hx-icon name="undo" [size]="13" /></button>
                                  }
                                </div>
                              }
                            </td>
                          }
                        </tr>
                      }
                    </tbody>
                  </table>
                </div>
                @for (it of rest(g.items); track it.key) { <hx-setting [item]="it" /> }
              } @else {
                @for (it of g.items; track it.key) { <hx-setting [item]="it" /> }
              }
            </div>
          }
        }

        <!-- Panels a module adds to its own settings (plugin contribution settings_panel), e.g. Backup. -->
        @if (!store.query()) { @for (p of panels(); track p.id) {
          <div class="group panel">
            <div class="gh"><h4><hx-icon [name]="p.icon || 'puzzle'" [size]="15" /> {{ p.label }}</h4></div>
            @if (p.help) { <p class="ph">{{ p.help }}</p> }
            <hx-plugin-outlet [module]="p.module" [element]="p.element" [ctx]="panelCtx(p)" />
          </div>
        } }
      }
    </section>`,
  styles: [`
    :host { display: block; }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--text-3); flex-shrink: 0; }
    .main { display: flex; flex-direction: column; gap: 14px; }
    .proposal { display: flex; align-items: center; gap: 10px; padding: 10px 12px; border-radius: var(--radius-lg);
                background: var(--accent-soft); color: var(--text); flex-wrap: wrap; }
    .proposal hx-icon { color: var(--accent); }
    .pt { font-size: 13.5px; } .pd { font-size: 12.5px; color: var(--text-2); margin-top: 2px; }
    .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; }
    .card { text-align: left; display: flex; flex-direction: column; gap: 6px; padding: 14px; border-radius: var(--radius-lg);
            border: 1px solid var(--border); background: var(--surface); transition: background var(--dur-fast); }
    .card:hover { background: var(--surface-2); }
    .ch { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
    .cn { font-family: var(--font-serif); font-size: 17px; color: var(--text); }
    .cm { font-size: 12.5px; color: var(--text-3); }
    .cf { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--text-3); min-height: 21px; }
    .sub { font-size: 13px; font-weight: 600; color: var(--text-2); margin-top: 6px; }
    .others { display: flex; flex-wrap: wrap; gap: 6px; }
    .bar { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
    @media (max-width: 760px) { .bar > .hx-grow { flex-basis: 100%; } }
    .bar h3 { font-size: 17px; font-family: var(--font-serif); font-weight: 500; display: flex; align-items: center; gap: 8px; }
    .center { display: flex; justify-content: center; padding: 30px; }
    .modhead { align-self: flex-start; display: inline-flex; align-items: center; gap: 4px; font-family: var(--font-serif);
               font-size: 16px; color: var(--text); margin-top: 6px; }
    .modhead:hover { color: var(--accent); }
    .group { border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 6px 14px 4px; background: var(--surface); }
    .gh { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; padding: 8px 0 6px; }
    .gh h4 { font-size: 14px; font-weight: 600; }
    .gh hx-segmented { max-width: 100%; overflow-x: auto; }
    .ph { font-size: 12.5px; color: var(--text-3); margin: -2px 0 6px; }
    .grid-wrap { overflow-x: auto; margin: 4px 0 8px; }
    .grid { border-collapse: collapse; width: 100%; min-width: 520px; }
    .grid th { font-size: 12px; font-weight: 500; color: var(--text-3); text-align: left; padding: 6px 8px; white-space: nowrap; }
    .grid tbody th { color: var(--text); font-size: 13.5px; font-weight: 500; }
    .grid td { padding: 6px 8px; vertical-align: top; border-top: 1px solid var(--border); }
    .grid tbody th { border-top: 1px solid var(--border); }
    .cell { display: flex; align-items: flex-start; gap: 4px; min-width: 150px; }
    .cell hx-setting-control { flex: 1; }
    .rst { color: var(--accent); padding: 8px 2px; }
    .panel { padding-bottom: 12px; }
    .panel h4 { display: flex; align-items: center; gap: 6px; }
  `],
})
export class SystemSettingsComponent {
  readonly store = inject(CentralSettingsStore);
  private plugins = inject(PluginsService);

  /** settings_panel contributions of the selected module, in manifest order. */
  readonly panels = computed(() => {
    const m = this.store.selected();
    return m ? this.plugins.settingsPanels().filter(p => p.module === m).sort((a, b) => a.order - b.order) : [];
  });
  private ctxCache = new Map<string, object>();
  panelCtx(p: { id: string; module: string; local_id: string }) {
    let ctx = this.ctxCache.get(p.id);
    if (!ctx) { ctx = this.plugins.context(p.module, 'settings_panel', p.local_id); this.ctxCache.set(p.id, ctx); }
    return ctx;
  }

  readonly current = computed(() => this.store.modulesById().get(this.store.selected() ?? '') ?? null);
  readonly advancedLabel = computed(() => this.store.hiddenAdvanced() ? `Avanzate (${this.store.hiddenAdvanced()})` : 'Avanzate');

  name = moduleLabel;
  modified = isModified;
  show = showValue;
  health(m: ModuleInfo) { return HEALTH[m.health ?? 'unknown'] ?? HEALTH['unknown']; }

  proposer(p: Proposal) { return p.proposer === 'athena' ? 'Athena' : p.proposer === 'oracle' ? 'Hestia' : p.proposer; }
  private itemOf(p: Proposal) { return this.store.items().find(i => i.key === p.key); }
  labelOf(p: Proposal) { return this.itemOf(p)?.label ?? p.label ?? p.key; }
  proposedValue(p: Proposal) { const it = this.itemOf(p); return it ? showValue(it, p.value) : String(p.value); }

  presetOptions(pg: PresetGroup): SegmentOption[] {
    return [...pg.presets.map(p => ({ value: p.id, label: p.label, title: p.help })),
            { value: 'custom', label: 'Personalizzato', title: 'Valori scelti a mano' }];
  }
  presetHelp(pg: PresetGroup) {
    return pg.active === 'custom' ? 'Personalizzato: i valori non corrispondono a nessun preset.'
      : pg.presets.find(p => p.id === pg.active)?.help ?? '';
  }
  pickPreset(pg: PresetGroup, id: string) {
    if (id !== 'custom') void this.store.applyPreset(pg, id);
  }

  /** Settings declaring row+column become a table (e.g. Oracle use cases × fornitore/modello). */
  grid(items: SettingItem[]): Grid | null {
    const cells = items.filter(i => i.row && i.column);
    if (cells.length < 2) return null;
    const rows: string[] = [], columns: string[] = [], cell = new Map<string, SettingItem>();
    for (const i of cells) {
      if (!rows.includes(i.row!)) rows.push(i.row!);
      if (!columns.includes(i.column!)) columns.push(i.column!);
      cell.set(`${i.row}|${i.column}`, i);
    }
    return rows.length > 1 ? { rows, columns, cell } : null;
  }
  rest(items: SettingItem[]) { return items.filter(i => !(i.row && i.column)); }
}
