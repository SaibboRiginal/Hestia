import { ChangeDetectionStrategy, Component, OnInit, effect, inject, input, output, signal } from '@angular/core';
import { ButtonComponent, IconComponent } from '../../ui';
import { CentralSettingsApi } from './central-settings.api';

export interface Place { id: string; name: string; address: string; kind: 'home' | 'work' | 'other'; lat?: number; lon?: number }

const KINDS: { value: Place['kind']; label: string; icon: string }[] = [
  { value: 'home', label: 'Casa', icon: 'home' }, { value: 'work', label: 'Lavoro', icon: 'briefcase' },
  { value: 'other', label: 'Altro', icon: 'map-pin' },
];

/**
 * <hx-places-editor [key] [value] (commit)> — personal setting `themis.personal.places` (editor "places").
 * One row per place (name, city or address, kind). Exactly one Casa: the default place for the weather.
 * After saving, each row shows what the weather service found for it (Themis → options_source on Hecate).
 */
@Component({
  selector: 'hx-places-editor',
  imports: [ButtonComponent, IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @for (p of rows(); track $index; let i = $index) {
      <div class="row">
        <select class="hx-select kind" [disabled]="disabled()" [attr.aria-label]="'Tipo di ' + (p.name || 'luogo')"
                (change)="set(i, 'kind', $any($event.target).value)">
          @for (k of kinds; track k.value) { <option [value]="k.value" [selected]="k.value === p.kind">{{ k.label }}</option> }
        </select>
        <input class="hx-input name" placeholder="Nome (es. Palestra)" [value]="p.name" [disabled]="disabled()"
               aria-label="Nome del luogo" (input)="set(i, 'name', $any($event.target).value)" />
        <input class="hx-input addr" placeholder="Città, o indirizzo con la città" [value]="p.address" [disabled]="disabled()"
               aria-label="Città o indirizzo" (input)="set(i, 'address', $any($event.target).value)" />
        <button hx-btn variant="ghost" size="sm" icon="trash" iconOnly aria-label="Togli luogo" [disabled]="disabled()"
                (click)="remove(i)"></button>
        @if (found()[p.id]; as f) {
          <div class="found" [class.bad]="!f.ok"><hx-icon [name]="f.ok ? 'map-pin' : 'alert'" [size]="13" [tone]="f.ok ? 'success' : 'warning'" /> {{ f.label }}</div>
        }
      </div>
    } @empty {
      <div class="hint">Nessun luogo. Aggiungi almeno Casa: è il luogo predefinito per il meteo.</div>
    }
    <div class="bar">
      <button hx-btn variant="secondary" size="sm" icon="plus" [disabled]="disabled()" (click)="add()">Aggiungi luogo</button>
      @if (dirty()) { <button hx-btn variant="primary" size="sm" icon="check" [disabled]="disabled()" (click)="save()">Salva luoghi</button> }
      @if (error()) { <span class="err">{{ error() }}</span> }
    </div>`,
  styles: [`
    :host { display: flex; flex-direction: column; gap: 8px; min-width: 0; }
    .row { display: grid; grid-template-columns: 110px minmax(110px, 1fr) minmax(140px, 2fr) auto; gap: 6px; align-items: center; }
    .found { grid-column: 2 / -1; font-size: 12px; color: var(--text-3); display: inline-flex; gap: 4px; align-items: center; }
    .found.bad { color: var(--warning); }
    .bar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
    .hint { font-size: 13px; color: var(--text-3); }
    .err { font-size: 12px; color: var(--danger); }
    @media (max-width: 640px) { .row { grid-template-columns: 1fr auto; } .row .kind, .row .addr { grid-column: 1 / -1; } .found { grid-column: 1 / -1; } }
  `],
})
export class PlacesEditorComponent implements OnInit {
  private api = inject(CentralSettingsApi);

  key = input.required<string>();
  value = input<unknown>([]);
  disabled = input(false);
  commit = output<Place[]>();

  readonly kinds = KINDS;
  readonly rows = signal<Place[]>([]);
  readonly dirty = signal(false);
  readonly error = signal('');
  readonly found = signal<Record<string, { ok: boolean; label: string }>>({});

  constructor() {
    effect(() => { const v = this.value(); if (!this.dirty()) this.rows.set(this.normalize(v)); });
  }

  ngOnInit() { void this.resolve(); }

  private normalize(v: unknown): Place[] {
    return (Array.isArray(v) ? v : []).filter(x => x && typeof x === 'object').map((x: any) => ({
      id: String(x.id || ''), name: String(x.name || ''), address: String(x.address || ''),
      kind: (['home', 'work', 'other'].includes(x.kind) ? x.kind : 'other') as Place['kind'],
      ...(typeof x.lat === 'number' && typeof x.lon === 'number' ? { lat: x.lat, lon: x.lon } : {}),
    }));
  }

  set(i: number, field: 'name' | 'address' | 'kind', v: string) {
    this.rows.update(rs => rs.map((r, j) => {
      if (j === i) {
        const next = { ...r, [field]: v } as Place;
        if (field === 'address') { delete next.lat; delete next.lon; }
        return next;
      }
      // one Casa only: choosing Casa elsewhere turns the old one into Altro
      return field === 'kind' && v === 'home' && r.kind === 'home' ? { ...r, kind: 'other' } : r;
    }));
    this.dirty.set(true);
  }

  add() {
    const hasHome = this.rows().some(r => r.kind === 'home');
    this.rows.update(rs => [...rs, { id: '', name: hasHome ? '' : 'Casa', address: '', kind: hasHome ? 'other' : 'home' }]);
    this.dirty.set(true);
  }

  remove(i: number) { this.rows.update(rs => rs.filter((_, j) => j !== i)); this.dirty.set(true); }

  save() {
    const rows = this.rows().map(r => ({ ...r, name: r.name.trim(), address: r.address.trim() }))
      .filter(r => r.name || r.address);
    const names = rows.map(r => r.name.toLowerCase());
    if (names.some((n, i) => n && names.indexOf(n) !== i)) { this.error.set('Due luoghi con lo stesso nome'); return; }
    const used = new Set<string>();
    for (const r of rows) {
      let id = r.id || slug(r.name || r.address) || 'luogo';
      while (used.has(id)) id += '-2';
      used.add(id); r.id = id;
    }
    this.error.set('');
    this.dirty.set(false);
    this.rows.set(rows);
    this.commit.emit(rows);
    setTimeout(() => void this.resolve(), 1200);
  }

  async resolve() {
    try {
      const opts = await this.api.options(this.key());
      const out: Record<string, { ok: boolean; label: string }> = {};
      for (const o of opts) {
        const label = String(o.label || '');
        out[String(o.value)] = { ok: (o as { ok?: boolean }).ok ?? true, label: label || 'non trovato' };
      }
      this.found.set(out);
    } catch { /* weather service away: rows stay without the check */ }
  }
}

function slug(s: string): string {
  return s.normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
}
