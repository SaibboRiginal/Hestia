import { ChangeDetectionStrategy, Component, OnInit, computed, inject } from '@angular/core';
import { RouterLink } from '@angular/router';
import { UI } from '../../ui';
import { PluginsService } from './plugins.service';

/**
 * Impostazioni → Personali → Moduli e Home: what each module contributes to THIS WebUI (pages, widgets, quick
 * actions) with show/hide switches. Saved as this client's setting `webui.plugins.hidden` (other clients unaffected).
 */
@Component({
  selector: 'app-plugin-settings',
  imports: [...UI, RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <p class="intro">Ogni modulo con un'interfaccia porta qui le sue pagine, i widget per le dashboard e le azioni rapide della Home.
      Quello che nascondi sparisce solo da questa WebUI; gli altri client restano come sono.</p>
    @if (!plugins.catalog()) {
      @if (plugins.catalogError()) { <hx-empty icon="offline" title="Catalogo non raggiungibile">Hub non risponde: riprova tra poco.</hx-empty> }
      @else { <hx-spinner /> }
    } @else {
      @for (g of groups(); track g.module) {
        <section class="mod">
          <header>
            <hx-icon [name]="g.icon || 'puzzle'" [size]="17" />
            <span class="mt">{{ g.title }}</span>
            <hx-badge [tone]="g.online ? 'success' : 'warning'" dot>{{ g.online ? 'attivo' : 'offline' }}</hx-badge>
            <span class="hx-grow"></span>
            <hx-toggle [checked]="!plugins.isHidden(g.module + '.*')" (changed)="plugins.setHidden(g.module + '.*', !$event)" [attr.title]="'Mostra ' + g.title" />
          </header>
          @if (g.description) { <p class="md">{{ g.description }}</p> }
          @if (!plugins.isHidden(g.module + '.*')) {
            @for (row of g.rows; track row.id) {
              <div class="row">
                <hx-icon [name]="row.icon" [size]="15" />
                <span class="rk">{{ row.kind }}</span>
                <span class="rl">{{ row.label }}</span>
                <span class="hx-grow"></span>
                @if (row.link) { <a [routerLink]="row.link" class="open">Apri</a> }
                <hx-toggle [checked]="!plugins.hidden().includes(row.id)" (changed)="plugins.setHidden(row.id, !$event)" [attr.title]="'Mostra ' + row.label" />
              </div>
            }
          }
        </section>
      } @empty {
        <hx-empty icon="puzzle" title="Nessun modulo con interfaccia">Quando un modulo ne ha una, compare qui da solo.</hx-empty>
      }
    }`,
  styles: [`
    :host { display: flex; flex-direction: column; gap: 14px; max-width: 820px; }
    .intro { color: var(--text-2); font-size: 13.5px; line-height: 1.5; }
    .mod { border: 1px solid var(--border); border-radius: var(--radius-lg); background: var(--surface); padding: 12px 14px; display: flex; flex-direction: column; gap: 4px; }
    header { display: flex; align-items: center; gap: 9px; }
    header hx-icon { color: var(--accent); }
    .mt { font-weight: 600; font-size: 15px; }
    .md { color: var(--text-3); font-size: 12.5px; margin: 0 0 4px 26px; }
    .row { display: flex; align-items: center; gap: 9px; padding: 6px 0 6px 26px; border-top: 1px solid var(--border); font-size: 13.5px; }
    .row hx-icon { color: var(--text-3); }
    .rk { font-size: 11.5px; color: var(--text-3); width: 82px; flex-shrink: 0; }
    .rl { color: var(--text); }
    .open { font-size: 12.5px; }
    @media (max-width: 600px) { .rk { display: none; } .row { padding-left: 4px; } }
  `],
})
export class PluginSettingsComponent implements OnInit {
  plugins = inject(PluginsService);

  readonly groups = computed(() => [...this.plugins.modules().values()].map(m => {
    const pages = this.plugins.allPages().filter(p => p.module === m.module && !p.detail)
      .map(p => ({ id: p.id, kind: 'Pagina', label: p.parent ? `↳ ${p.label}` : p.label, icon: p.icon || 'file', link: this.plugins.link(p.module, p.local_id) }));
    const widgets = this.plugins.allWidgets().filter(w => w.module === m.module)
      .map(w => ({ id: w.id, kind: 'Widget', label: w.label, icon: 'grid', link: '' }));
    const quick = this.plugins.allQuick().filter(q => q.module === m.module)
      .map(q => ({ id: q.id, kind: 'Azione rapida', label: q.label, icon: q.icon || 'zap', link: '' }));
    return { ...m, rows: [...pages, ...widgets, ...quick] };
  }).filter(g => g.rows.length));

  ngOnInit(): void { void this.plugins.refreshCatalog(); void this.plugins.loadConfig(); }
}
