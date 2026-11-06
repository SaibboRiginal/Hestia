import { ChangeDetectionStrategy, Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { RouterLink } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { UI, DialogService, ToastService } from '../../ui';
import { setupError } from '../setup/setup.api';

interface Version { version: string; tag: string; commit: string; label: string; }
interface Available { ref: string; label: string; notes?: string[]; major?: boolean; commits?: number; }
interface Job { state: 'idle' | 'in_corso' | 'fatto' | 'errore'; step?: string; detail?: string; target?: string; }
interface HistoryRow { at: number; from: string; to: string; ok: boolean; back: boolean; detail: string; }
export interface UpdateStatus {
  installed: Version; channel: 'stabile' | 'novita'; available: Available | null; checked_at: number | null;
  check_error: string; job: Job; history: HistoryRow[]; previous: string; blocked: string;
}

/**
 * «Aggiornamenti» (docs/work/2026-10-30-setup-un-click §4.4): the installed version, the new one with what it brings,
 * «Installa» (Hestia moves to it and comes back by itself if something does not answer), «Torna alla versione di
 * prima», the history. Browser → WebUI → Hub → Hephaestus /api/setup/update*.
 */
@Component({
  selector: 'app-updates-page',
  imports: [...UI, RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <hx-page-header title="Aggiornamenti" subtitle="La versione di Hestia, le novità e il ritorno indietro">
      <button hx-btn size="sm" variant="ghost" icon="refresh" [loading]="busy() === 'check'" (click)="check()" title="Controlla adesso"><span class="lbl">Controlla adesso</span></button>
    </hx-page-header>
    <div class="body">
      @if (error()) {
        <hx-empty icon="offline" title="Non riesco a leggere gli aggiornamenti">{{ error() }}</hx-empty>
      } @else if (!st()) {
        <div class="center"><hx-spinner /></div>
      } @else {
        <section class="card hx-card">
          <div class="now">
            <hx-icon name="check-circle" [size]="22" tone="success" />
            <div><b>Hestia {{ st()!.installed.label }}</b>
              <small>{{ st()!.channel === 'novita' ? 'Ricevi ogni novità appena è pronta' : 'Ricevi le versioni pubblicate' }} ·
                <a routerLink="/settings" [queryParams]="{ module: 'hephaestus' }">cambia</a>
                @if (st()!.checked_at) { · controllato {{ ago(st()!.checked_at!) }} }</small></div>
          </div>
        </section>

        @if (job().state === 'in_corso') {
          <section class="card hx-card">
            <div class="now"><hx-spinner /><div><b>Sto aggiornando…</b><small>{{ job().step || 'Preparo' }}. Non serve fare niente: se qualcosa non risponde torno da solo alla versione di prima.</small></div></div>
          </section>
        } @else if (avail()) {
          <section class="card hx-card new">
            <div class="now">
              <hx-icon name="sparkle" [size]="22" tone="accent" />
              <div><b>{{ avail()!.ref === 'origin/main' ? (avail()!.commits + ' novità di sviluppo') : ('È uscita Hestia ' + avail()!.label) }}</b>
                @if (avail()!.major) { <small>Versione grande: se dopo serve qualcosa sul computer, te lo dico io.</small> }</div>
            </div>
            @if (avail()!.notes?.length) {
              <ul class="notes">@for (n of avail()!.notes; track $index) { <li>{{ n }}</li> }</ul>
            }
            @if (st()!.blocked) {
              <p class="warn"><hx-icon name="alert" [size]="14" tone="warning" /> {{ st()!.blocked }}</p>
            }
            <div class="row">
              <button hx-btn variant="primary" icon="download" [disabled]="!!st()!.blocked" [loading]="busy() === 'apply'" (click)="apply()">Installa</button>
            </div>
          </section>
        } @else {
          <p class="note">{{ st()!.check_error || 'Hai già l\\'ultima versione.' }}</p>
        }

        @if (job().state === 'errore' || job().state === 'fatto') {
          @if (job().detail) {
            <p class="note"><hx-icon [name]="job().state === 'errore' ? 'alert' : 'info'" [size]="14" [tone]="job().state === 'errore' ? 'warning' : 'info'" /> {{ job().detail }}</p>
          }
        }

        @if (st()!.history.length) {
          <h2>Storico</h2>
          <ul class="list">
            @for (h of history(); track h.at) {
              <li class="row hx-card">
                <hx-icon [name]="h.ok ? (h.back ? 'undo' : 'check-circle') : 'x-circle'" [size]="18" [tone]="h.ok ? 'success' : 'warning'" />
                <div class="main"><b>{{ h.ok ? (h.back ? 'Tornato a ' + h.to : 'Aggiornato a ' + h.to) : 'Non riuscito, rimasto a ' + h.from }}</b>
                  <small>{{ date(h.at) }}{{ h.detail ? ' · ' + h.detail : '' }}</small></div>
              </li>
            }
          </ul>
          @if (st()!.previous && job().state !== 'in_corso') {
            <div class="row"><button hx-btn size="sm" variant="ghost" icon="undo" [loading]="busy() === 'back'" (click)="back()">Torna alla versione di prima</button></div>
          }
        }
        <p class="hint">Le parti sul computer (Docker, Ollama) si aggiornano rilanciando l'installer. I satelliti si aggiornano rilanciando l'installer anche su di loro.</p>
      }
    </div>`,
  styles: [`
    :host { display: flex; flex-direction: column; flex: 1; min-height: 0; }
    .body { flex: 1; overflow: auto; padding: 18px 24px 32px; display: flex; flex-direction: column; gap: 12px; max-width: 860px; }
    .center { display: grid; place-items: center; padding: 40px; }
    .card { padding: 14px 16px; display: flex; flex-direction: column; gap: 10px; }
    .now { display: flex; gap: 12px; align-items: center; }
    .now b { display: block; font-size: 15px; font-weight: 600; }
    .now small, .main small { display: block; font-size: 12.5px; color: var(--text-3); }
    .now a { color: var(--accent); }
    .notes { margin: 0; padding-left: 20px; display: flex; flex-direction: column; gap: 4px; font-size: 13.5px; color: var(--text-2); }
    .row { display: flex; gap: 8px; align-items: center; }
    h2 { font-size: 13px; font-weight: 600; color: var(--text-3); margin: 8px 0 0; text-transform: uppercase; letter-spacing: .04em; }
    .list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
    .list .row { padding: 10px 12px; gap: 10px; }
    .main { flex: 1; min-width: 0; }
    .main b { font-size: 13.5px; font-weight: 600; }
    .warn, .note, .hint { display: flex; gap: 6px; align-items: flex-start; font-size: 12.5px; color: var(--text-3); margin: 0; }
    @media (max-width: 720px) { .body { padding: 14px 12px 28px; } }
    @media (max-width: 860px) { hx-page-header { padding-left: 56px; } }
    @media (max-width: 520px) { .lbl { display: none; } }
  `],
})
export class UpdatesPageComponent {
  private http = inject(HttpClient);
  private dialogs = inject(DialogService);
  private toasts = inject(ToastService);
  st = signal<UpdateStatus | null>(null);
  error = signal('');
  busy = signal('');
  avail = computed(() => this.st()?.available ?? null);
  job = computed<Job>(() => this.st()?.job || { state: 'idle' });
  history = computed(() => [...(this.st()?.history || [])].reverse());

  constructor() {
    void this.load();
    // Every 3 s while an update runs, calm otherwise.
    let tick = 0;
    const timer = setInterval(() => {
      tick++;
      if (this.job().state === 'in_corso' || tick % 10 === 0) void this.load();
    }, 3000);
    inject(DestroyRef).onDestroy(() => clearInterval(timer));
  }

  async load() {
    try {
      this.st.set(await firstValueFrom(this.http.get<UpdateStatus>('/api/webui/setup/update')));
      this.error.set('');
    } catch (e: any) {
      // While Hestia restarts its own parts the page may not answer for a moment: keep the last state.
      if (!this.st()) this.error.set(setupError(e));
    }
  }

  private async post(op: string, label: string) {
    this.busy.set(label);
    try {
      this.st.set(await firstValueFrom(this.http.post<UpdateStatus>(`/api/webui/setup/update/${op}`, {})));
    } catch (e: any) {
      this.toasts.error(setupError(e));
    } finally {
      this.busy.set('');
    }
  }

  async check() {
    await this.post('check', 'check');
    if (this.st() && !this.st()!.available && !this.st()!.check_error) this.toasts.success('Hai già l\'ultima versione.');
  }

  async apply() {
    const a = this.st()?.available;
    if (!a || !await this.dialogs.confirm(`Installare ${a.ref === 'origin/main' ? 'le novità' : 'Hestia ' + a.label}?`,
      'Qualche parte si riavvia per pochi secondi. Se qualcosa non risponde, torno da solo alla versione di prima.', 'Installa')) return;
    await this.post('apply', 'apply');
  }

  async back() {
    if (!await this.dialogs.confirm('Tornare alla versione di prima?', 'Rimetto il codice e le parti come prima dell\'ultimo aggiornamento.', 'Torna indietro')) return;
    await this.post('back', 'back');
  }

  ago(t: number): string {
    const min = Math.round((Date.now() / 1000 - t) / 60);
    if (min < 1) return 'adesso';
    if (min < 60) return `${min} min fa`;
    const h = Math.round(min / 60);
    return h < 24 ? `${h} h fa` : `${Math.round(h / 24)} giorni fa`;
  }

  date(t: number): string {
    return new Date(t * 1000).toLocaleString('it-IT', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
  }
}
