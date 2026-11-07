import { ChangeDetectionStrategy, Component, computed, effect, input, model, signal, untracked } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { UI } from '../../ui';
import { PickItem, SetupPickComponent } from './setup-pick.component';

/** A service the user can add: a cloud brain (Gemini, a key, the Claude subscription) or a cloud voice service. */
export interface ServiceRow {
  name: string;
  label: string;
  icon?: string;
  tag?: string;
  /** One short line under the name (what it is, what it costs). */
  note?: string;
  /** 'key': a key, checked at once by reading the service's list; 'token': a code saved with the choice; 'none'. */
  kind: 'key' | 'token' | 'none';
  keySet: boolean;
  keyLink?: string;
  tokenHint?: string;
  tokenLabel?: string;
  tokenPlaceholder?: string;
}
/** «Prova»: the key works or not, and what the service has (models or voices) with the ones to preselect, in order. */
export interface ServiceCheck { ok: boolean; detail?: string; options: PickItem[]; recommended: string[]; }

/**
 * The one way the guided setup adds cloud services (docs/work/2026-10-30-setup-un-click): models of the brain and
 * services of the voice use this same component. One or more services, in the order they are tried; for each one
 * one or more models (or voices), in order: the next takes over when the first fails or its quota ends.
 *
 * A key is typed once: «Salva e prova» saves it and reads the service's list (nothing spent); when it works the card
 * closes on «La chiave funziona» and the models are already chosen (Hestia's defaults the service still has). The
 * user changes them only if he wants («Cambia»). A key already saved is checked by itself when the card opens.
 */
@Component({
  selector: 'app-setup-services',
  imports: [...UI, FormsModule, SetupPickComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="choices">
      @for (p of services(); track p.name) {
        <div class="opt" [class.sel]="isOn(p.name)">
          <button type="button" class="choice" role="checkbox" [attr.aria-checked]="isOn(p.name)" (click)="toggle(p)">
            <hx-icon [name]="isOn(p.name) ? 'check-circle' : (p.icon || 'zap')" [size]="20" [tone]="isOn(p.name) ? 'accent' : 'muted'" />
            <span class="ct"><b>@if (place(p.name)) { {{ place(p.name) }}. }{{ p.label }}</b>
              @if (p.tag) { <span class="rec">{{ p.tag }}</span> }
              <small>{{ summary(p) }}</small></span>
            @if (isOn(p.name)) {
              @if (testing() === p.name) { <hx-spinner /> }
              @else { <hx-icon [name]="ready()[p.name] ? 'check-circle' : 'clock'" [size]="16" [tone]="ready()[p.name] ? 'success' : 'warning'" /> }
            }
          </button>
          @if (isOn(p.name)) {
            <div class="cfg">
              @if (p.kind === 'token') {
                @if (p.tokenHint) { <p class="hint">{{ p.tokenHint }}</p> }
                <hx-field [label]="p.tokenLabel || 'Codice'" [hint]="p.keySet ? 'Già inserito: lascia vuoto per tenerlo.' : ''">
                  <input class="hx-input mono" type="password" autocomplete="off" [ngModel]="tokens()[p.name] || ''" (ngModelChange)="typeToken(p.name, $event)" [placeholder]="p.tokenPlaceholder || ''" />
                </hx-field>
              } @else if (p.kind === 'key') {
                @if (ready()[p.name] && !editKey().includes(p.name)) {
                  <div class="line"><hx-icon name="check-circle" [size]="15" tone="success" /><span>{{ notes()[p.name] || 'La chiave funziona.' }}</span>
                    <button type="button" class="link" (click)="openKey(p.name)">Cambia chiave</button></div>
                } @else if (testing() === p.name && !keys[p.name]) {
                  <div class="line"><hx-spinner /><span>Provo la chiave salvata…</span></div>
                } @else {
                  <hx-field [label]="'Chiave di ' + p.label" [error]="errors()[p.name] || ''">
                    <input class="hx-input mono" type="password" autocomplete="off" [ngModel]="keys[p.name] || ''" (ngModelChange)="keys[p.name] = $event"
                           [placeholder]="p.keySet ? 'chiave salvata: incollane un\\'altra per cambiarla' : 'incolla qui la chiave'" (keydown.enter)="check(p.name)" />
                  </hx-field>
                  <div class="row">
                    @if (p.keyLink) { <a hx-btn variant="ghost" icon="external" [href]="p.keyLink" target="_blank" rel="noopener">Prendi la chiave</a> }
                    <button hx-btn variant="secondary" icon="play" [loading]="testing() === p.name" [disabled]="!keys[p.name] && !p.keySet" (click)="check(p.name)">{{ keys[p.name] ? 'Salva e prova' : 'Prova' }}</button>
                  </div>
                }
                @if (ready()[p.name] && (lists()[p.name] || []).length) {
                  @if (editPicks().includes(p.name)) {
                    <div class="sub">{{ optionsLabel() }} <small>{{ max() === 1 ? 'uno solo: tocca quello che vuoi.' : 'in ordine: il primo risponde, gli altri se non va. Tocca per aggiungere o togliere.' }}</small></div>
                    <app-setup-pick [items]="lists()[p.name]" [multi]="max() !== 1" [selected]="(picks()[p.name] || [])[0] || ''" [chosen]="picks()[p.name] || []" [limit]="4" placeholder="Cerca"
                                    (picked)="togglePick(p.name, $event)" />
                    <div class="row"><button hx-btn variant="ghost" size="sm" icon="check" (click)="closePicks(p.name)">Fatto</button></div>
                  } @else {
                    <div class="line"><hx-icon name="list" [size]="15" tone="muted" /><span>{{ optionsLabel() }}: {{ pickText(p.name) }}</span>
                      <button type="button" class="link" (click)="openPicks(p.name)">Cambia</button></div>
                  }
                }
              }
              @if (place(p.name) > 1) {
                <div class="row"><button hx-btn variant="ghost" size="sm" icon="chevron-up" (click)="moveUp(p.name)">Prima di {{ before(p.name) }}</button></div>
              }
            </div>
          }
        </div>
      } @empty { <p class="hint">{{ empty() }}</p> }
    </div>
  `,
  styles: [`
    :host { display: block; }
    .choices { display: flex; flex-direction: column; gap: 8px; }
    .opt { border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--surface); overflow: hidden;
           transition: border-color var(--dur-fast) var(--ease); }
    .opt.sel { border-color: var(--accent); }
    .choice { display: flex; gap: 12px; align-items: flex-start; text-align: left; padding: 14px; border: 0; background: none;
              color: var(--text); width: 100%; min-height: var(--tap, 0px); }
    .opt.sel > .choice { background: var(--accent-soft); }
    .ct { display: flex; flex-direction: column; gap: 3px; flex: 1; min-width: 0; }
    .ct b { font-weight: 600; font-size: 15px; overflow-wrap: anywhere; }
    .ct small { color: var(--text-3); font-size: 13px; line-height: 1.4; }
    .rec { align-self: flex-start; font-size: 11px; font-weight: 600; color: var(--accent); background: var(--accent-soft); padding: 1px 7px; border-radius: var(--radius-full); }
    .cfg { display: flex; flex-direction: column; gap: 10px; padding: 12px 14px 14px; border-top: 1px solid var(--border); }
    .line { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; font-size: 14px; color: var(--text-2); }
    .line span { overflow-wrap: anywhere; min-width: 0; }
    .link { background: none; border: 0; color: var(--accent); font-size: 13px; padding: 2px 0; margin-left: auto; }
    .sub { font-size: 13px; font-weight: 600; color: var(--text-2); }
    .sub small { font-weight: 400; color: var(--text-3); }
    .hint { font-size: 14px; color: var(--text-2); }
    .row { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
  `],
})
export class SetupServicesComponent {
  services = input<ServiceRow[]>([]);
  /** «Modelli» or «Voci». */
  optionsLabel = input<string>('Modelli');
  empty = input<string>('Nessun servizio cloud configurato.');
  /** At most this many models per service (0 = no limit): the memory uses one model only. */
  max = input<number>(0);
  /** Reads the service's list with the key (a typed key is saved first). Throws when the answer is lost. */
  tester = input.required<(name: string, key: string) => Promise<ServiceCheck>>();

  /** The chosen services, in the order they are tried. */
  order = model<string[]>([]);
  /** Per service: the chosen models (or voices), in order. */
  picks = model<Record<string, string[]>>({});
  /** Per service: usable (key works, or a code typed / saved). */
  ready = model<Record<string, boolean>>({});
  /** Codes typed for 'token' services (sent with the choice). */
  tokens = model<Record<string, string>>({});

  keys: Record<string, string> = {};
  lists = signal<Record<string, PickItem[]>>({});
  notes = signal<Record<string, string>>({});
  errors = signal<Record<string, string>>({});
  testing = signal('');
  editKey = signal<string[]>([]);
  editPicks = signal<string[]>([]);
  private asked = new Set<string>();

  constructor() {
    // A chosen service whose key is already saved is checked by itself (it costs nothing): no button to press.
    effect(() => {
      const rows = this.services();
      const order = this.order();
      untracked(() => {
        for (const p of rows) {
          if (!order.includes(p.name)) continue;
          if (p.kind === 'none') this.mark(p.name, true);
          else if (p.kind === 'token') this.mark(p.name, p.keySet || !!(this.tokens()[p.name] || '').trim());
          else if (p.keySet && !this.asked.has(p.name)) { this.asked.add(p.name); void this.check(p.name); }
        }
      });
    });
  }

  private row(name: string): ServiceRow | undefined { return this.services().find(s => s.name === name); }
  isOn(name: string): boolean { return this.order().includes(name); }
  place(name: string): number { return this.order().length > 1 ? this.order().indexOf(name) + 1 : 0; }
  before(name: string): string { const l = this.order(); return this.row(l[l.indexOf(name) - 1])?.label || ''; }
  private mark(name: string, ok: boolean) { if (!!this.ready()[name] !== ok) this.ready.set({ ...this.ready(), [name]: ok }); }

  toggle(p: ServiceRow) {
    const list = this.order();
    this.order.set(list.includes(p.name) ? list.filter(n => n !== p.name) : [...list, p.name]);
  }
  moveUp(name: string) {
    const l = [...this.order()];
    const i = l.indexOf(name);
    if (i > 0) { [l[i - 1], l[i]] = [l[i], l[i - 1]]; this.order.set(l); }
  }
  typeToken(name: string, value: string) {
    this.tokens.set({ ...this.tokens(), [name]: value });
    this.mark(name, !!this.row(name)?.keySet || !!value.trim());
  }
  openKey(name: string) { this.editKey.set([...this.editKey().filter(n => n !== name), name]); }

  summary(p: ServiceRow): string {
    if (!this.isOn(p.name)) return p.note || '';
    if (p.kind === 'token') return this.ready()[p.name] ? 'Collegato.' : (p.note || '');
    if (p.kind === 'key' && this.ready()[p.name]) return p.note || 'Pronto.';
    return p.keySet ? 'Chiave salvata.' : 'Serve una chiave.';
  }
  pickText(name: string): string {
    const items = this.lists()[name] || [];
    return (this.picks()[name] || []).map(id => items.find(i => i.id === id)?.title || id).join(', poi ');
  }
  togglePick(name: string, id: string) {
    const cur = this.picks()[name] || [];
    const next = this.max() === 1 ? [id] : cur.includes(id) ? cur.filter(x => x !== id) : [...cur, id].slice(-(this.max() || 99));
    if (next.length) this.picks.set({ ...this.picks(), [name]: next });   // at least one stays chosen
  }
  openPicks(name: string) { this.editPicks.set([...this.editPicks().filter(n => n !== name), name]); }
  closePicks(name: string) { this.editPicks.set(this.editPicks().filter(n => n !== name)); }

  /** «Salva e prova» / «Prova»: when it works the card closes on «La chiave funziona» with the models already chosen. */
  async check(name: string): Promise<void> {
    const typed = (this.keys[name] || '').trim();
    if (!typed && !this.row(name)?.keySet) return;
    this.testing.set(name);
    this.errors.set({ ...this.errors(), [name]: '' });
    try {
      const r = await this.tester()(name, typed);
      this.keys[name] = '';
      this.lists.set({ ...this.lists(), [name]: r.options || [] });
      if (r.ok) {
        const ids = new Set((r.options || []).map(o => o.id));
        const kept = (this.picks()[name] || []).filter(id => !ids.size || ids.has(id));
        const rec = r.recommended?.length ? r.recommended : (r.options || []).slice(0, 1).map(o => o.id);
        // what was chosen stays first; the recommended ones follow as fallbacks (more than one, as the chains want)
        const chosen = [...kept, ...rec.filter(id => !kept.includes(id))].slice(0, this.max() || Math.max(kept.length, rec.length));
        this.picks.set({ ...this.picks(), [name]: chosen });
        this.notes.set({ ...this.notes(), [name]: r.detail || 'La chiave funziona.' });
        this.editKey.set(this.editKey().filter(n => n !== name));
        this.mark(name, true);
      } else {
        this.errors.set({ ...this.errors(), [name]: r.detail || 'Non funziona.' });
        this.openKey(name);
        this.mark(name, false);
      }
    } catch (e: any) {
      this.errors.set({ ...this.errors(), [name]: e?.message || 'Qualcosa non ha funzionato, riprova tra poco.' });
      this.openKey(name);
      this.mark(name, false);
    } finally {
      this.testing.set('');
    }
  }
}
