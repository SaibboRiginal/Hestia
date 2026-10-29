import { ChangeDetectionStrategy, Component, ElementRef, HostListener, computed, effect, inject, signal, viewChild } from '@angular/core';
import { Router } from '@angular/router';
import { IconComponent } from '../../ui';
import { APP_MODULES } from '../../app.modules';
import { PluginsService } from './plugins.service';
import { QuickActionsService } from './quick-actions.service';
import { MetisService } from '../../services/metis.service';

interface Entry { id: string; label: string; hint: string; icon: string; group: string; run: () => void; }

/**
 * Ctrl/⌘+K palette: «Adesso» (what makes sense now, from Metis), every quick action (one tap, same as the Home
 * strip), module pages, dashboards and the WebUI's own pages. Type to filter, ↑/↓ + Enter to run. Also opened by
 * the sidebar «Cerca» (`open()`).
 */
@Component({
  selector: 'hx-command-palette',
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (open()) {
      <div class="backdrop" (mousedown)="close()">
        <div class="pal hx-fade-in" role="dialog" aria-label="Azioni rapide" (mousedown)="$event.stopPropagation()">
          <div class="in"><hx-icon name="search" [size]="17" />
            <input #q placeholder="Cosa vuoi fare? (azioni, pagine, dashboard)" [value]="query()" (input)="query.set($any($event.target).value); sel.set(0)"
                   (keydown)="onKeys($event)" aria-label="Cerca"></div>
          <div class="list">
            @for (e of results(); track e.id; let i = $index) {
              @if (i === 0 || results()[i - 1].group !== e.group) { <div class="g">{{ e.group }}</div> }
              <button class="it" [class.on]="i === sel()" (mouseenter)="sel.set(i)" (click)="exec(e)">
                <hx-icon [name]="e.icon" [size]="16" /><span class="l">{{ e.label }}</span><span class="h">{{ e.hint }}</span>
              </button>
            } @empty { <div class="none">Niente trovato</div> }
          </div>
        </div>
      </div>
    }`,
  styles: [`
    .backdrop { position: fixed; inset: 0; z-index: 1050; background: var(--overlay); display: flex; justify-content: center; padding: 12vh 16px 16px; }
    .pal { width: min(620px, 100%); max-height: 70vh; display: flex; flex-direction: column; background: var(--surface); border: 1px solid var(--border);
           border-radius: var(--radius-xl); box-shadow: var(--shadow-3); overflow: hidden; }
    .in { display: flex; align-items: center; gap: 10px; padding: 12px 16px; border-bottom: 1px solid var(--border); color: var(--text-3); }
    .in input { flex: 1; border: 0; background: transparent; outline: none; font: inherit; font-size: 15px; color: var(--text); }
    .list { overflow: auto; padding: 6px; }
    .g { font-size: 11.5px; color: var(--text-3); font-weight: 600; padding: 8px 10px 4px; text-transform: uppercase; letter-spacing: .03em; }
    .it { width: 100%; display: flex; align-items: center; gap: 10px; padding: 8px 10px; border-radius: var(--radius-md); text-align: left; color: var(--text-2); }
    .it.on { background: var(--accent-soft); color: var(--text); } .it.on hx-icon { color: var(--accent); }
    .l { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .h { font-size: 12px; color: var(--text-3); white-space: nowrap; }
    .none { padding: 18px; text-align: center; color: var(--text-3); }
  `],
})
export class CommandPaletteComponent {
  private plugins = inject(PluginsService);
  private qa = inject(QuickActionsService);
  private router = inject(Router);
  private metis = inject(MetisService);
  readonly open = signal(false);
  readonly query = signal('');
  readonly sel = signal(0);
  private input = viewChild<ElementRef<HTMLInputElement>>('q');

  private readonly entries = computed<Entry[]>(() => {
    const mod = (m: string) => this.plugins.modules().get(m)?.title ?? m;
    return [
      ...this.metis.adesso().map(a => ({ id: 'now:' + a.tool + a.title, label: a.title, hint: a.reason || mod(a.module), icon: 'zap',
        group: 'Adesso', run: () => this.metis.open(a.tool, a.args ?? {}, a.title) })),
      ...this.qa.sorted().map(c => ({ id: 'qa:' + c.key, label: c.label, hint: [c.hint, mod(c.action.module)].filter(Boolean).join(' · '),
        icon: c.state === 'done' ? 'check' : c.icon || 'zap', group: 'Azioni rapide', run: () => void this.qa.run(c) })),
      ...this.plugins.navPages().map(p => ({ id: 'pg:' + p.id, label: p.label, hint: mod(p.module), icon: p.icon || 'puzzle', group: 'Moduli',
        run: () => void this.router.navigateByUrl(this.plugins.link(p.module, p.local_id)) })),
      ...this.plugins.dashboards().map(d => ({ id: 'db:' + d.id, label: d.title, hint: 'Dashboard', icon: d.icon || 'grid', group: 'Dashboard',
        run: () => void this.router.navigateByUrl(d.id === 'home' ? '/home' : '/d/' + d.id) })),
      ...APP_MODULES.filter(m => m.path !== 'home').map(m => ({ id: 'app:' + m.path, label: m.label, hint: 'Hestia', icon: m.icon, group: 'Pagine',
        run: () => void this.router.navigateByUrl('/' + m.path) })),
    ];
  });
  readonly results = computed(() => {
    const q = this.query().trim().toLowerCase();
    const list = q ? this.entries().filter(e => `${e.label} ${e.hint}`.toLowerCase().includes(q)) : this.entries();
    return list.slice(0, 60);
  });

  constructor() {
    effect(() => { if (this.open()) queueMicrotask(() => this.input()?.nativeElement.focus()); });
  }

  /** The sidebar «Cerca» button. */
  @HostListener('window:hestia:palette')
  fromSidebar() { if (!this.open()) this.show(); }

  @HostListener('document:keydown', ['$event'])
  onGlobal(e: KeyboardEvent) {
    if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      if (this.open()) { this.close(); return; }
      this.show();
    } else if (e.key === 'Escape' && this.open()) this.close();
  }

  onKeys(e: KeyboardEvent) {
    const n = this.results().length;
    if (e.key === 'ArrowDown') { e.preventDefault(); this.sel.set(n ? (this.sel() + 1) % n : 0); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); this.sel.set(n ? (this.sel() - 1 + n) % n : 0); }
    else if (e.key === 'Enter') { const it = this.results()[this.sel()]; if (it) this.exec(it); }
  }

  show() {
    this.query.set(''); this.sel.set(0); this.open.set(true);
    void this.qa.reload();
    void this.metis.loadAdesso();
  }

  exec(e: Entry) { this.close(); e.run(); }
  close() { this.open.set(false); }
}
