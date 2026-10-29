import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { UI } from '../../ui';
import { MetisService, ScopriItem } from '../../services/metis.service';

/**
 * «Scopri» (dossier 2026-10-24-tutto-brainstorm-cindy C14, W7): the things Hestia can do that you never or rarely
 * use, what each does and «Prova» to open it (GET /api/metis/scopri — usage stats against the tool catalog).
 */
@Component({
  selector: 'app-scopri-page',
  imports: [...UI],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <hx-page-header title="Scopri" [subtitle]="subtitle()">
      <button hx-btn variant="ghost" size="sm" icon="refresh" [loading]="loading()" (click)="load()">Aggiorna</button>
    </hx-page-header>
    <div class="body">
      <div class="search"><hx-icon name="search" [size]="15" />
        <input class="hx-input" placeholder="Cerca tra le funzioni" [value]="query()" (input)="query.set($any($event.target).value)" aria-label="Cerca"></div>
      @if (loading() && !items().length) {
        <div class="center"><hx-spinner /></div>
      } @else if (error()) {
        <hx-empty icon="offline" title="Non disponibile">Riprova tra poco.
          <button hx-btn size="sm" icon="refresh" (click)="load()">Riprova</button></hx-empty>
      } @else if (!shown().length) {
        <hx-empty icon="check-circle" title="Hai già provato tutto">{{ query() ? 'Niente con queste parole.' : 'Quando arrivano funzioni nuove le trovi qui.' }}</hx-empty>
      } @else {
        @for (g of groups(); track g.key) {
          <section>
            <h2><hx-icon [name]="g.icon" [size]="15" />{{ g.title }}</h2>
            <div class="grid">
              @for (it of g.items; track it.tool) {
                <article class="card">
                  <div class="t">{{ it.title }}</div>
                  @if (it.description) { <div class="d">{{ it.description }}</div> }
                  <div class="f">
                    <span class="r">{{ it.reason || (it.uses ? 'Usata ' + it.uses + (it.uses === 1 ? ' volta' : ' volte') : 'Mai usata') }}</span>
                    <button hx-btn size="sm" variant="primary" icon="play" (click)="metis.open(it.tool, {}, it.title)">Prova</button>
                  </div>
                </article>
              }
            </div>
          </section>
        }
      }
    </div>`,
  styles: [`
    :host { display: flex; flex-direction: column; flex: 1; min-height: 0; }
    .body { flex: 1; overflow: auto; padding: 18px 24px 32px; display: flex; flex-direction: column; gap: 20px; }
    .search { position: relative; max-width: 520px; }
    .search hx-icon { position: absolute; left: 11px; top: 50%; transform: translateY(-50%); color: var(--text-3); }
    .search input { width: 100%; padding-left: 34px; }
    .center { display: grid; place-items: center; padding: 40px; }
    h2 { display: flex; align-items: center; gap: 8px; font-size: 14px; font-weight: 600; color: var(--text-2); margin-bottom: 10px; }
    h2 hx-icon { color: var(--accent); }
    .grid { display: grid; gap: 10px; grid-template-columns: repeat(auto-fill, minmax(min(100%, 260px), 1fr)); }
    .card { display: flex; flex-direction: column; gap: 6px; padding: 12px 14px; border: 1px solid var(--border); border-radius: var(--radius-lg); background: var(--surface); }
    .t { font-weight: 600; overflow-wrap: anywhere; }
    .d { font-size: 13px; color: var(--text-2); overflow-wrap: anywhere; flex: 1; }
    .f { display: flex; align-items: center; gap: 8px; margin-top: 4px; }
    .r { flex: 1; font-size: 12px; color: var(--text-3); }
    @media (max-width: 720px) { .body { padding: 14px 12px 28px; } }
    @media (max-width: 860px) { hx-page-header { padding-left: 56px; } }   /* room for the shell's menu button */
  `],
})
export class ScopriPageComponent implements OnInit {
  metis = inject(MetisService);
  readonly items = signal<ScopriItem[]>([]);
  readonly total = signal(0);
  readonly loading = signal(false);
  readonly error = signal(false);
  readonly query = signal('');

  readonly shown = computed(() => {
    const q = this.query().trim().toLowerCase();
    return q ? this.items().filter(i => `${i.title} ${i.description}`.toLowerCase().includes(q)) : this.items();
  });
  /** Grouped by area as people know them (Allenamento, Casa…), never by module. */
  readonly groups = computed(() => {
    const by = new Map<string, ScopriItem[]>();
    for (const it of this.shown()) { const k = it.area || 'altro'; by.set(k, [...(by.get(k) ?? []), it]); }
    return [...by.entries()].map(([key, items]) => ({ key, items, title: items[0].area_label || 'Altro',
      icon: items[0].area_icon || 'puzzle', order: items[0].area_order ?? 999 }))
      .sort((a, b) => a.order - b.order || a.title.localeCompare(b.title));
  });
  readonly subtitle = computed(() => this.total() ? `${this.total()} cose da provare` : 'Quello che sai fare con Hestia e non hai ancora provato');

  ngOnInit(): void { void this.load(); }

  async load(): Promise<void> {
    this.loading.set(true);
    const r = await this.metis.scopri();
    this.loading.set(false);
    this.error.set(!r.ok);
    if (r.ok) { this.items.set(r.items); this.total.set(r.total || r.items.length); }
  }
}
