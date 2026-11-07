import { ChangeDetectionStrategy, Component, effect, input, model, output, signal, untracked } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { UI } from '../../ui';
import { PickItem, SetupPickComponent } from './setup-pick.component';
import { ServiceCheck, ServiceRow, SetupServicesComponent } from './setup-services.component';

/** A program to install when nothing is found at home (Ollama, LM Studio…). */
export interface HomeProgram { name: string; label: string; site: string; note: string; }

/**
 * ONE step of the guided setup, the same for Modelli, Memoria, Ascolto and Voce (docs/work/2026-10-30-setup-un-click,
 * round 6): only the module behind it changes.
 *
 * «Locale»: one choice (tap again to leave it out), with search, filters, the programs to install when none is found
 * and the field to look on another computer of the house. «Cloud»: the shared services cards (key typed once,
 * checked by itself when saved; nothing preselected without a key), one or more in order. Hestia uses the home choice
 * first, then the cloud ones in order. ``single``: one choice in all (the memory: a local model OR one in the cloud).
 */
@Component({
  selector: 'app-setup-chain',
  imports: [...UI, FormsModule, SetupPickComponent, SetupServicesComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="part">
      <div class="sub"><hx-icon name="host" [size]="15" tone="muted" /> Locale
        <small>uno, gratis e privato: su questo computer o su un altro della tua rete. Tocca di nuovo per toglierlo.</small></div>
      @if (homeItems().length) {
        <app-setup-pick [items]="homeItems()" [selected]="home()" [limit]="4" placeholder="Cerca" (picked)="pickHome($event)" />
      } @else if (programs().length) {
        <p class="hint">{{ homeEmpty() }}</p>
        <div class="choices">
          @for (r of programs(); track r.name; let first = $first) {
            <a class="choice" [href]="r.site" target="_blank" rel="noopener">
              <hx-icon name="external" [size]="18" tone="muted" />
              <span class="ct"><b>{{ r.label }}</b>@if (first) { <span class="rec">Consigliato</span> }<small>{{ r.note }}</small></span>
            </a>
          }
        </div>
      } @else {
        <p class="hint">{{ homeEmpty() }}</p>
      }
      <ng-content select="[home-extra]" />
      <div class="hostrow">
        <input class="hx-input mono" autocomplete="off" spellcheck="false" aria-label="Indirizzo di un altro computer della tua rete"
               [ngModel]="draft()" (ngModelChange)="draft.set($event)" (keydown.enter)="add()" placeholder="Altro computer: 192.168.1.20" />
        <button hx-btn variant="secondary" icon="search" [disabled]="!draft().trim()" [loading]="searching()" (click)="add()">Cerca lì</button>
        <button hx-btn variant="ghost" icon="refresh" [loading]="searching()" (click)="again.emit()">Cerca di nuovo</button>
      </div>
      @if (hosts().length) {
        <p class="hint">Cerco anche su: @for (h of hosts(); track h) { <span class="chip">{{ h }} <button type="button" aria-label="Togli" (click)="removeHost.emit(h)"><hx-icon name="x" [size]="12" /></button></span> }</p>
      }
    </section>
    <section class="part">
      <div class="sub"><hx-icon name="zap" [size]="15" tone="muted" /> Cloud
        <small>{{ single() ? 'oppure un modello di un servizio cloud' : 'facoltativo: uno o più, in ordine, se il locale non c\\'è o non ce la fa' }}</small></div>
      <app-setup-services [services]="services()" [tester]="tester()" [optionsLabel]="optionsLabel()" [max]="single() ? 1 : 0" [empty]="cloudEmpty()"
                          [order]="order()" (orderChange)="setOrder($event)" [(picks)]="picks" [(ready)]="ready" [(tokens)]="tokens" />
    </section>
  `,
  styles: [`
    :host { display: flex; flex-direction: column; gap: 18px; }
    .part { display: flex; flex-direction: column; gap: 10px; }
    .sub { display: flex; gap: 6px; align-items: baseline; flex-wrap: wrap; font-size: 14px; font-weight: 600; color: var(--text); }
    .sub small { font-weight: 400; font-size: 13px; color: var(--text-3); }
    .hint { display: flex; gap: 8px; align-items: center; font-size: 14px; color: var(--text-2); flex-wrap: wrap; }
    .choices { display: flex; flex-direction: column; gap: 6px; }
    .choice { display: flex; gap: 10px; align-items: flex-start; text-align: left; padding: 11px 12px; border: 1px solid var(--border);
              border-radius: var(--radius-md); background: var(--surface); color: var(--text); text-decoration: none; }
    .ct { display: flex; flex-direction: column; gap: 2px; flex: 1; min-width: 0; }
    .ct b { font-weight: 600; font-size: 14px; }
    .ct small { color: var(--text-3); font-size: 12px; line-height: 1.4; }
    .rec { align-self: flex-start; font-size: 11px; font-weight: 600; color: var(--accent); background: var(--accent-soft); padding: 1px 7px; border-radius: var(--radius-full); }
    .hostrow { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
    .hostrow input { flex: 1 1 220px; min-width: 0; }
    .chip { display: inline-flex; gap: 4px; align-items: center; font-size: 12px; background: var(--surface-2); border-radius: var(--radius-full); padding: 1px 4px 1px 9px; }
    .chip button { background: none; border: 0; padding: 2px; color: var(--text-3); display: inline-flex; }
  `],
})
export class SetupChainComponent {
  homeItems = input<PickItem[]>([]);
  homeEmpty = input<string>('Non ho trovato niente su questo computer né nella tua rete.');
  programs = input<HomeProgram[]>([]);
  hosts = input<string[]>([]);
  searching = input<boolean>(false);
  services = input<ServiceRow[]>([]);
  tester = input.required<(name: string, key: string) => Promise<ServiceCheck>>();
  optionsLabel = input<string>('Modelli');
  cloudEmpty = input<string>('Nessun servizio cloud per questo passo.');
  single = input<boolean>(false);

  /** The home choice («provider|id»), '' = none. */
  home = model<string>('');
  order = model<string[]>([]);
  picks = model<Record<string, string[]>>({});
  ready = model<Record<string, boolean>>({});
  tokens = model<Record<string, string>>({});

  addHost = output<string>();
  removeHost = output<string>();
  again = output<void>();
  draft = signal('');

  constructor() {
    // single: a cloud model chosen while one at home is chosen (or the other way round) → only the newest stays.
    effect(() => {
      const single = this.single(), order = this.order();
      untracked(() => { if (single && order.length > 1) this.order.set(order.slice(-1)); });
    });
  }

  pickHome(id: string) {
    const next = id === this.home() ? '' : id;
    this.home.set(next);
    if (next && this.single()) this.order.set([]);
  }
  setOrder(list: string[]) {
    const fresh = list.filter(n => !this.order().includes(n));
    const next = this.single() ? (fresh.length ? fresh.slice(-1) : list.slice(-1)) : list;
    this.order.set(next);
    if (this.single() && next.length) this.home.set('');
  }
  add() {
    const h = this.draft().trim();
    if (!h) return;
    this.draft.set('');
    this.addHost.emit(h);
  }
}
