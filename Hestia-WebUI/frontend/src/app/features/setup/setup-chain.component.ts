import { ChangeDetectionStrategy, Component, computed, effect, input, model, output, signal, untracked } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { UI } from '../../ui';
import { PickItem, SetupPickComponent } from './setup-pick.component';

/** A program to install when nothing is found (Ollama, LM Studio…). */
export interface HomeProgram { name: string; label: string; site: string; note: string; }
/** A cloud service of a step: a model service (Gemini, a key, the Claude subscription) or a speech service. */
export interface ServiceRow {
  name: string;
  label: string;
  tag?: string;
  /** One short line: what it is or what it costs. */
  note?: string;
  /** 'key': checked at once by reading the service's list; 'token': a code saved with the choice; 'none': nothing to type. */
  kind: 'key' | 'token' | 'none';
  keySet: boolean;
  keyLink?: string;
  tokenHint?: string;
  tokenLabel?: string;
  tokenPlaceholder?: string;
}
/** «Prova»: the key works or not, what the service has (models or voices) and the ones to choose by themselves. */
export interface ServiceCheck { ok: boolean; detail?: string; options: PickItem[]; recommended: string[]; }

interface ChosenRow { key: string; title: string; where: string; waiting: boolean; kind: 'home' | 'model' | 'service'; svc?: string; id?: string; }

/** The keys of «Scelti» in their natural order: 'h' (the local choice), 'm:<service>:<model>', 's:<service>' (a
 * service with nothing to pick, e.g. the Claude subscription). */
export function chosenKeys(home: string, order: string[], picks: Record<string, string[]>): string[] {
  const out = home ? ['h'] : [];
  for (const svc of order) {
    const ids = picks[svc] || [];
    if (ids.length) ids.forEach(id => out.push(`m:${svc}:${id}`)); else out.push(`s:${svc}`);
  }
  return out;
}
/** The same keys in the user's order (``rank``, set by ↑ ↓); keys it does not name keep their place after. */
export function ranked(keys: string[], rank: string[]): string[] {
  const pos = (k: string, i: number) => { const r = rank.indexOf(k); return r < 0 ? rank.length + i : r; };
  return keys.map((k, i) => ({ k, p: pos(k, i) })).sort((a, b) => a.p - b.p).map(x => x.k);
}
/** A «Scelti» key as a chain step: the local choice is «program|model». */
export function keyStep(key: string, home: string): { provider: string; model: string } {
  if (key === 'h') { const [provider, ...rest] = home.split('|'); return { provider, model: rest.join('|') }; }
  const [, svc, ...id] = key.split(':');
  return { provider: svc, model: id.join(':') };
}

/**
 * THE step of the guided setup (docs/work/2026-10-30-setup-un-click, round 7): Modelli, Memoria, Ascolto and Voce are
 * this same component, only the module behind it changes.
 *
 * On top «Scelti»: what Hestia will use, in order (the local one first, then the cloud ones), each with ↑ and ×.
 * Under it two tabs to add: «Locale» (one, from the programs found on this computer or another of the network: search,
 * filters, the programs to install when none is found) and «Cloud» (services: the key is typed once and tried at
 * once, a saved key is tried by itself; when it works its models are already chosen and can be changed right there).
 * ``single``: one choice in all (the memory).
 */
@Component({
  selector: 'app-setup-chain',
  imports: [...UI, FormsModule, SetupPickComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="chosen" aria-label="Scelti">
      <div class="head">
        <b>{{ single() ? 'Scelto' : 'Scelti' }}</b>
        @if (!single() && rows().length > 1) { <small>in quest'ordine: se uno non risponde, passa al successivo</small> }
      </div>
      @for (r of rows(); track r.key; let i = $index) {
        <div class="crow">
          <span class="num">{{ i + 1 }}</span>
          <span class="ct"><b>{{ r.title }}</b><small>{{ r.where }}@if (r.waiting) { · <span class="warn">manca la chiave</span> }</small>
            @if (trialState()?.key === r.key && trialState()!.text) { <small class="heard">{{ trialState()!.text }}</small> }</span>
          @if (trial() && !r.waiting) {
            @if (trialState()?.key === r.key && trialState()!.busy) { <span class="ib"><hx-spinner /></span> }
            @else {
              <button type="button" class="ib try" [class.rec]="trialState()?.key === r.key && trialState()!.recording"
                      [attr.aria-label]="trial() === 'voce' ? 'Ascolta' : (trialState()?.key === r.key && trialState()!.recording ? 'Ferma e prova' : 'Prova a parlare')"
                      (click)="emitTry(r.key)">
                <hx-icon [name]="trialState()?.key === r.key && (trialState()!.recording || trialState()!.playing) ? 'stop' : (trial() === 'voce' ? 'play' : 'mic')" [size]="16" />
              </button>
            }
          }
          @if (!single() && rows().length > 1) {
            <button type="button" class="ib" aria-label="Sposta prima" [disabled]="i === 0" (click)="move(i, -1)"><hx-icon name="chevron-up" [size]="16" /></button>
            <button type="button" class="ib" aria-label="Sposta dopo" [disabled]="i === rows().length - 1" (click)="move(i, 1)"><hx-icon name="chevron-down" [size]="16" /></button>
          }
          <button type="button" class="ib" aria-label="Togli" (click)="remove(r)"><hx-icon name="x" [size]="16" /></button>
        </div>
      } @empty { <p class="none">Niente ancora: scegli qui sotto.</p> }
    </section>

    <div class="tabs" role="tablist">
      <button type="button" role="tab" [attr.aria-selected]="tab() === 'locale'" [class.on]="tab() === 'locale'" (click)="tab.set('locale')">
        <span class="tl"><hx-icon name="host" [size]="16" /> Locale</span><small>gratis e privato</small></button>
      <button type="button" role="tab" [attr.aria-selected]="tab() === 'cloud'" [class.on]="tab() === 'cloud'" (click)="tab.set('cloud')">
        <span class="tl"><hx-icon name="cloud" [size]="16" /> Cloud</span><small>con una chiave</small></button>
    </div>

    @if (tab() === 'locale') {
      <section class="pane">
        @if (homeItems().length) {
          <app-setup-pick [items]="homeItems()" [selected]="home()" [limit]="5" placeholder="Cerca" (picked)="pickHome($event)"
                          [trial]="trial()" [trialState]="itemTrial('h|')" (tried)="tryItem('h|' + $event)" />
        } @else {
          <p class="none">{{ homeEmpty() }}</p>
        }
        @if (programs().length) {
          @if (homeItems().length) { <p class="more-head">Altri programmi gratis: installane uno, aprilo e premi «Cerca di nuovo».</p> }
          @for (r of programs(); track r.name; let first = $first) {
            <a class="prog" [href]="r.site" target="_blank" rel="noopener">
              <span class="ct"><b>{{ r.label }}</b><small>{{ r.note }}</small></span>
              @if (first && !homeItems().length) { <span class="tag">Consigliato</span> }
              <hx-icon name="external" [size]="15" tone="muted" />
            </a>
          }
        }
        <ng-content select="[home-extra]" />
        <div class="net">
          @if (hosts().length) {
            <span class="hosts">Cerco anche su: @for (h of hosts(); track h) { <span class="chip">{{ h }}<button type="button" aria-label="Togli" (click)="removeHost.emit(h)"><hx-icon name="x" [size]="12" /></button></span> }</span>
          }
          @if (netOpen()) {
            <div class="netrow">
              <input class="hx-input" autocomplete="off" spellcheck="false" aria-label="Indirizzo dell'altro computer"
                     [ngModel]="draft()" (ngModelChange)="draft.set($event)" (keydown.enter)="add()" placeholder="Indirizzo, per esempio 192.168.1.20" />
              <button hx-btn variant="secondary" [disabled]="!draft().trim()" [loading]="searching()" (click)="add()">Cerca lì</button>
            </div>
          }
          <div class="links">
            @if (!netOpen()) { <button type="button" class="link" (click)="netOpen.set(true)">È su un altro computer della rete?</button> }
            <button type="button" class="link" [disabled]="searching()" (click)="again.emit()">{{ searching() ? 'Cerco…' : 'Cerca di nuovo' }}</button>
          </div>
        </div>
      </section>
    } @else {
      <section class="pane">
        @for (p of services(); track p.name) {
          <div class="svc" [class.open]="open() === p.name">
            <button type="button" class="svc-head" [attr.aria-expanded]="open() === p.name" (click)="toggleOpen(p)">
              <span class="ct"><b>{{ p.label }}@if (p.tag) { <span class="tag">{{ p.tag }}</span> }</b><small>{{ status(p) }}</small></span>
              @if (testing() === p.name) { <hx-spinner /> }
              @else if (inUse(p.name)) { <hx-icon name="check-circle" [size]="18" tone="success" /> }
              <hx-icon [name]="open() === p.name ? 'chevron-up' : 'chevron-down'" [size]="16" tone="muted" />
            </button>
            @if (open() === p.name) {
              <div class="svc-body">
                @if (p.kind === 'token') {
                  @if (p.tokenHint) { <p class="hint">{{ p.tokenHint }}</p> }
                  <input class="hx-input mono" type="password" autocomplete="off" [attr.aria-label]="p.tokenLabel || 'Codice'"
                         [ngModel]="tokens()[p.name] || ''" (ngModelChange)="typeToken(p.name, $event)"
                         [placeholder]="p.keySet ? 'Già inserito: lascia vuoto per tenerlo' : (p.tokenPlaceholder || 'Incolla qui il codice')" />
                  <div class="row">
                    <button hx-btn [variant]="inUse(p.name) ? 'ghost' : 'primary'" [disabled]="!ready()[p.name]" (click)="useService(p.name)">{{ inUse(p.name) ? 'Togli' : 'Usa' }}</button>
                  </div>
                } @else if (p.kind === 'key' && (!ready()[p.name] || editKey().includes(p.name))) {
                  @if (testing() === p.name && !keys[p.name]) {
                    <p class="hint"><hx-spinner /> Provo la chiave salvata…</p>
                  } @else {
                    <input class="hx-input mono" type="password" autocomplete="off" [attr.aria-label]="'Chiave di ' + p.label"
                           [ngModel]="keys[p.name] || ''" (ngModelChange)="keys[p.name] = $event" (keydown.enter)="check(p.name)"
                           [placeholder]="p.keySet ? 'Chiave salvata: incollane un\\'altra per cambiarla' : 'Incolla qui la chiave'" />
                    @if (errors()[p.name]) { <p class="err"><hx-icon name="alert" [size]="14" tone="danger" /> {{ errors()[p.name] }}</p> }
                    <div class="row">
                      @if (p.keyLink) { <a hx-btn variant="ghost" icon="external" [href]="p.keyLink" target="_blank" rel="noopener">Prendi la chiave</a> }
                      <button hx-btn variant="primary" [loading]="testing() === p.name" [disabled]="!keys[p.name] && !p.keySet" (click)="check(p.name)">{{ keys[p.name] ? 'Salva e prova' : 'Prova' }}</button>
                    </div>
                  }
                } @else {
                  @if (p.kind === 'key') {
                    <p class="ok"><hx-icon name="check-circle" [size]="15" tone="success" /> {{ notes()[p.name] || 'La chiave funziona.' }}
                      <button type="button" class="link" (click)="openKey(p.name)">Cambia chiave</button></p>
                  }
                  @if ((lists()[p.name] || []).length) {
                    <app-setup-pick [items]="lists()[p.name]" [multi]="!single()" [chosen]="picks()[p.name] || []" [selected]="(picks()[p.name] || [])[0] || ''"
                                    [limit]="5" placeholder="Cerca" (picked)="pick(p.name, $event)"
                                    [trial]="trial()" [trialState]="itemTrial('m:' + p.name + ':')" (tried)="tryItem('m:' + p.name + ':' + $event)" />
                  } @else if (p.kind === 'none') {
                    <div class="row"><button hx-btn [variant]="inUse(p.name) ? 'ghost' : 'primary'" (click)="useService(p.name)">{{ inUse(p.name) ? 'Togli' : 'Usa' }}</button></div>
                  } @else {
                    @if (testing() === p.name || !listed(p.name)) { <p class="hint"><hx-spinner /> Leggo i modelli…</p> }
                    @else { <p class="none">{{ emptyList() }}</p> }
                  }
                }
              </div>
            }
          </div>
        } @empty { <p class="none">{{ cloudEmpty() }}</p> }
      </section>
    }
  `,
  styles: [`
    :host { display: flex; flex-direction: column; gap: 14px; }
    .chosen { display: flex; flex-direction: column; gap: 6px; padding: 12px; border-radius: var(--radius-md); background: var(--surface-2); }
    .head { display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; font-size: 13px; color: var(--text-2); }
    .head b { font-weight: 600; color: var(--text); }
    .head small { font-size: 12px; color: var(--text-3); }
    .crow { display: flex; gap: 10px; align-items: center; padding: 8px 10px; border-radius: var(--radius-sm); background: var(--surface); border: 1px solid var(--border); }
    .num { width: 22px; height: 22px; flex: none; display: grid; place-items: center; border-radius: var(--radius-full); background: var(--accent-soft); color: var(--accent); font-size: 12px; font-weight: 600; }
    .ct { display: flex; flex-direction: column; gap: 1px; flex: 1; min-width: 0; text-align: left; }
    .ct b { font-size: 14px; font-weight: 600; overflow-wrap: anywhere; display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
    .ct small { font-size: 12px; color: var(--text-3); line-height: 1.4; }
    .warn { color: var(--warning); }
    .more-head { margin: 6px 0 0; font-size: 13px; color: var(--text-2); }
    .ib { flex: none; display: grid; place-items: center; width: 30px; height: 30px; border-radius: var(--radius-sm); border: 0; background: none; color: var(--text-3); }
    .ib:hover:not(:disabled) { background: var(--surface-2); color: var(--text); }
    .ib:disabled { opacity: .3; cursor: default; }
    .ib.try { color: var(--accent); }
    .ib.try.rec { color: var(--danger); background: var(--surface-2); }
    .heard { color: var(--text-2) !important; font-style: italic; }
    .none { font-size: 13px; color: var(--text-3); }
    .tabs { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; padding: 4px; border-radius: var(--radius-md); background: var(--surface-2); }
    .tabs button { display: flex; flex-direction: column; gap: 1px; align-items: center; justify-content: center; padding: 8px; border: 0; border-radius: var(--radius-sm);
                   background: none; color: var(--text-2); font-size: 14px; font-weight: 600; }
    .tl { display: inline-flex; gap: 6px; align-items: center; }
    .tabs button small { font-weight: 400; font-size: 12px; color: var(--text-3); }
    .tabs button.on { background: var(--surface); color: var(--text); box-shadow: var(--shadow-sm, 0 1px 2px rgba(0,0,0,.08)); }
    .pane { display: flex; flex-direction: column; gap: 10px; }
    .prog { display: flex; gap: 10px; align-items: center; padding: 11px 12px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--surface); color: var(--text); text-decoration: none; }
    .tag { font-size: 11px; font-weight: 600; color: var(--accent); background: var(--accent-soft); padding: 1px 7px; border-radius: var(--radius-full); }
    .net { display: flex; flex-direction: column; gap: 8px; }
    .netrow { display: flex; gap: 8px; }
    .netrow input { flex: 1; min-width: 0; }
    .links { display: flex; gap: 16px; flex-wrap: wrap; }
    .link { background: none; border: 0; padding: 2px 0; color: var(--accent); font-size: 13px; }
    .link:disabled { color: var(--text-3); }
    .hosts { font-size: 13px; color: var(--text-2); display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
    .chip { display: inline-flex; gap: 2px; align-items: center; font-size: 12px; background: var(--surface-2); border-radius: var(--radius-full); padding: 1px 4px 1px 9px; }
    .chip button { background: none; border: 0; padding: 2px; color: var(--text-3); display: inline-flex; }
    .svc { border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--surface); overflow: hidden; }
    .svc.open { border-color: var(--border-strong); }
    .svc-head { display: flex; gap: 10px; align-items: center; width: 100%; padding: 12px; border: 0; background: none; color: var(--text); }
    .svc-body { display: flex; flex-direction: column; gap: 10px; padding: 0 12px 12px; }
    .hint, .ok, .err { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; font-size: 13px; color: var(--text-2); line-height: 1.45; }
    .err { color: var(--danger); }
    .ok .link { margin-left: auto; }
    .row { display: flex; gap: 8px; justify-content: flex-end; flex-wrap: wrap; }
  `],
})
export class SetupChainComponent {
  homeItems = input<PickItem[]>([]);
  homeEmpty = input<string>('Non ho trovato niente su questo computer né nella rete.');
  programs = input<HomeProgram[]>([]);
  hosts = input<string[]>([]);
  searching = input<boolean>(false);
  services = input<ServiceRow[]>([]);
  /** Reads the service's list with the key (a typed key is saved first). Throws when the answer is lost. */
  tester = input.required<(name: string, key: string) => Promise<ServiceCheck>>();
  cloudEmpty = input<string>('Nessun servizio cloud per questo passo.');
  emptyList = input<string>('La chiave funziona, ma il servizio non ha niente da scegliere qui.');
  single = input<boolean>(false);
  /** «Prova» on each chosen row: hear a voice ('voce') or speak and see what it understood ('ascolto'). */
  trial = input<'' | 'voce' | 'ascolto'>('');
  trialState = input<{ key: string; busy?: boolean; recording?: boolean; playing?: boolean; text?: string } | null>(null);
  tryRow = output<{ key: string; provider: string; model: string }>();

  /** The local choice («program|id»), '' = none. */
  home = model<string>('');
  /** The cloud services used, in order. */
  order = model<string[]>([]);
  /** Per service: the models (or voices) used, in order. */
  picks = model<Record<string, string[]>>({});
  /** Per service: usable (key works, or a code typed / saved). */
  ready = model<Record<string, boolean>>({});
  /** Codes typed for 'token' services (sent with the choice). */
  tokens = model<Record<string, string>>({});
  /** «Scelti» in the user's order (keys of ``chosenKeys``), set by ↑ ↓: local and cloud mixed freely. */
  rank = model<string[]>([]);

  addHost = output<string>();
  removeHost = output<string>();
  again = output<void>();

  tab = signal<'locale' | 'cloud'>('locale');
  open = signal('');
  netOpen = signal(false);
  draft = signal('');
  keys: Record<string, string> = {};
  lists = signal<Record<string, PickItem[]>>({});
  notes = signal<Record<string, string>>({});
  errors = signal<Record<string, string>>({});
  testing = signal('');
  editKey = signal<string[]>([]);
  private asked = new Set<string>();
  private tabSet = false;

  constructor() {
    // The tab to start on: Locale when something is there, Cloud otherwise (decided once, then the user's).
    effect(() => {
      const items = this.homeItems(), home = this.home(), order = this.order(), svcs = this.services();
      untracked(() => {
        if (this.tabSet) return;
        if (items.length || home) { this.tabSet = true; this.tab.set('locale'); }
        else if (order.length || svcs.length) { this.tabSet = true; this.tab.set('cloud'); }
      });
    });
    // A service in use whose key is saved is tried by itself (it costs nothing): its models come back already chosen.
    effect(() => {
      const rows = this.services(), order = this.order();
      untracked(() => {
        for (const p of rows) {
          if (!order.includes(p.name)) continue;
          if (p.kind === 'none') this.mark(p.name, true);
          else if (p.kind === 'token') this.mark(p.name, p.keySet || !!(this.tokens()[p.name] || '').trim());
          else if (p.keySet && !this.asked.has(p.name)) { this.asked.add(p.name); void this.check(p.name, false); }
        }
      });
    });
  }

  private row(name: string): ServiceRow | undefined { return this.services().find(s => s.name === name); }
  private mark(name: string, ok: boolean) { if (!!this.ready()[name] !== ok) this.ready.set({ ...this.ready(), [name]: ok }); }
  listed(name: string): boolean { return name in this.lists(); }
  inUse(name: string): boolean { return this.order().includes(name); }

  /** «Scelti»: every choice, in the user's order (by default the local one first, then each service's models). */
  rows = computed<ChosenRow[]>(() => {
    const home = this.home();
    return ranked(chosenKeys(home, this.order(), this.picks()), this.rank()).map(key => {
      if (key === 'h') {
        const it = this.homeItems().find(i => i.id === home);
        return { key, title: it?.title || home.split('|').slice(1).join('|'), where: 'Locale', waiting: false, kind: 'home' as const };
      }
      const { provider: svc, model: id } = keyStep(key, home);
      const label = this.row(svc)?.label || svc;
      const waiting = !this.ready()[svc];
      if (key.startsWith('s:')) return { key, title: label, where: 'Cloud', waiting, kind: 'service' as const, svc };
      const title = (this.lists()[svc] || []).find(i => i.id === id)?.title || id;
      return { key, title, where: `Cloud · ${label}`, waiting, kind: 'model' as const, svc, id };
    });
  });

  emitTry(key: string) { this.tryRow.emit({ key, ...keyStep(key, this.home()) }); }
  /** The try button of a card in the lists (before choosing it): key «h|program|id» (local) or «m:svc:id» (cloud). */
  tryItem(key: string) {
    this.tryRow.emit(key.startsWith('h|') ? { key, ...keyStep('h', key.slice(2)) } : { key, ...keyStep(key, '') });
  }
  /** The page's try state seen by one list (its cards' ids are the key without the prefix). */
  itemTrial(prefix: string) {
    const t = this.trialState();
    return t && t.key.startsWith(prefix) ? { ...t, id: t.key.slice(prefix.length) } : null;
  }

  /** ↑ ↓: swap with the neighbour; the whole order is kept from then on. */
  move(i: number, d: -1 | 1) {
    const keys = this.rows().map(r => r.key);
    const j = i + d;
    if (j < 0 || j >= keys.length) return;
    [keys[i], keys[j]] = [keys[j], keys[i]];
    this.rank.set(keys);
  }
  remove(r: ChosenRow) {
    if (r.kind === 'home') { this.home.set(''); return; }
    if (!r.svc) return;
    const ids = (this.picks()[r.svc] || []).filter(x => x !== r.id);
    if (r.kind === 'model' && ids.length) { this.picks.set({ ...this.picks(), [r.svc]: ids }); return; }
    this.order.set(this.order().filter(n => n !== r.svc));
  }

  pickHome(id: string) {
    const next = id === this.home() ? '' : id;
    this.home.set(next);
    if (next && this.single()) this.order.set([]);
  }
  /** A tap on a model (or voice) of a service: in use or not; the service follows its models. */
  pick(svc: string, id: string) {
    const cur = this.picks()[svc] || [];
    if (this.single()) {
      this.home.set('');
      this.picks.set({ [svc]: [id] });
      this.order.set([svc]);
      return;
    }
    const next = cur.includes(id) ? cur.filter(x => x !== id) : [...cur, id];
    this.picks.set({ ...this.picks(), [svc]: next });
    if (next.length && !this.inUse(svc)) this.order.set([...this.order(), svc]);
    if (!next.length) this.order.set(this.order().filter(n => n !== svc));
  }
  /** Services with nothing to choose (the Claude subscription, a service without a list). */
  useService(svc: string) {
    if (this.inUse(svc)) { this.order.set(this.order().filter(n => n !== svc)); return; }
    if (this.single()) { this.home.set(''); this.order.set([svc]); return; }
    this.order.set([...this.order(), svc]);
  }
  toggleOpen(p: ServiceRow) {
    const opening = this.open() !== p.name;
    this.open.set(opening ? p.name : '');
    // the list is read here when this step has not read it yet: the key can be ready from another step (each mode
    // of Modelli is its own step sharing the same keys), so «ready» alone does not mean the models are known
    if (opening && p.kind === 'key' && (p.keySet || this.ready()[p.name]) && !(p.name in this.lists()) && this.testing() !== p.name) void this.check(p.name, false);
  }
  typeToken(name: string, value: string) {
    this.tokens.set({ ...this.tokens(), [name]: value });
    this.mark(name, !!this.row(name)?.keySet || !!value.trim());
  }
  openKey(name: string) { this.editKey.set([...this.editKey().filter(n => n !== name), name]); }

  status(p: ServiceRow): string {
    if (this.inUse(p.name)) {
      const n = (this.picks()[p.name] || []).length;
      return n ? `In uso: ${n === 1 ? '1 scelto' : n + ' scelti'}` : 'In uso';
    }
    if (p.kind === 'none') return p.note || '';
    if (this.ready()[p.name]) return 'Pronto: scegli qui';
    if (p.kind === 'token') return p.keySet ? 'Codice inserito' : (p.note || 'Serve il codice');
    return p.keySet ? 'Chiave salvata' : (p.note || 'Serve una chiave');
  }

  add() {
    const h = this.draft().trim();
    if (!h) return;
    this.draft.set('');
    this.netOpen.set(false);
    this.addHost.emit(h);
  }

  /** «Salva e prova» / «Prova». When a typed key works the recommended ones are chosen by themselves (``adopt``); a
   * saved key tried by itself only refreshes the list of a service already in use. */
  async check(name: string, adopt = true): Promise<void> {
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
        const rec = (r.recommended?.length ? r.recommended : (r.options || []).slice(0, 1).map(o => o.id)).filter(id => !ids.size || ids.has(id));
        if (adopt || this.inUse(name)) {
          const chosen = kept.length ? kept : rec;
          const one = this.single() ? chosen.slice(0, 1) : chosen;
          if (one.length) {
            this.picks.set(this.single() ? { [name]: one } : { ...this.picks(), [name]: one });
            if (this.single()) { this.home.set(''); this.order.set([name]); }
            else if (!this.inUse(name)) this.order.set([...this.order(), name]);
          } else if (!(r.options || []).length && adopt && !this.inUse(name)) {
            this.order.set(this.single() ? [name] : [...this.order(), name]);
          }
        }
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
