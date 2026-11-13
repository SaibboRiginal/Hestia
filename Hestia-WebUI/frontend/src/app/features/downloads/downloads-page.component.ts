import { ChangeDetectionStrategy, Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { RouterLink } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { UI, DialogService, ToastService } from '../../ui';

export interface DownloadRow {
  module: string; id: string; what: string; source: string; size: number; done: number;
  speed: number; eta_s: number | null; state: 'in_coda' | 'in_corso' | 'in_pausa' | 'fatto' | 'errore'; error: string;
}

const STATE: Record<DownloadRow['state'], { label: string; icon: string; tone: string }> = {
  in_coda: { label: 'In coda', icon: 'clock', tone: 'muted' },
  in_corso: { label: 'In corso', icon: 'download', tone: 'info' },
  in_pausa: { label: 'In pausa', icon: 'pause', tone: 'warning' },
  fatto: { label: 'Fatto', icon: 'check-circle', tone: 'success' },
  errore: { label: 'Non riuscito', icon: 'alert', tone: 'danger' },
};
const SOURCE: Record<string, string> = { ollama: 'Modello', whisper: 'Ascolto', http: 'File', docker: 'Programma' };
const ORDER: DownloadRow['state'][] = ['in_corso', 'in_coda', 'in_pausa', 'errore', 'fatto'];

/** Bytes in Italian: «3,1 GB», «420 MB». */
export function bytes(n: number): string {
  if (n >= 1e9) return (n / 1e9).toFixed(1).replace('.', ',') + ' GB';
  if (n >= 1e6) return Math.round(n / 1e6) + ' MB';
  return Math.max(1, Math.round(n / 1e3)) + ' kB';
}

/**
 * «Download» (docs/work/2026-10-30-setup-un-click §4.3): everything Hestia downloads — Oracle's models, Echo's voices —
 * with progress, speed and time left; pause, resume, retry, cancel, delete to free space. Each module owns its downloads
 * (hestia_common.downloads); this page only lists them through the WebUI backend and the Hub.
 */
@Component({
  selector: 'app-downloads-page',
  imports: [...UI, RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <hx-page-header title="Download" subtitle="Modelli e voci che Hestia scarica: avanzamento, pausa, riprova, spazio">
      <a hx-btn size="sm" variant="ghost" icon="volume" routerLink="/p/echo/voce" title="Prepara la voce: si fa dalla pagina Voce"><span class="lbl">Voce</span></a>
      <a hx-btn size="sm" variant="ghost" icon="brain" routerLink="/setup" title="Scegli il cervello"><span class="lbl">Scegli il cervello</span></a>
    </hx-page-header>
    <div class="body">
      @if (error()) {
        <hx-empty icon="offline" title="Non riesco a leggere i download">{{ error() }}</hx-empty>
      } @else if (rows() === null) {
        <div class="center"><hx-spinner /></div>
      } @else if (!rows()!.length) {
        <hx-empty icon="download" title="Nessun download">
          Qui compaiono i modelli del cervello e le voci mentre si scaricano, e restano per poterli eliminare.
        </hx-empty>
      } @else {
        <ul class="list">
          @for (d of sorted(); track d.module + d.id) {
            <li class="row hx-card">
              <hx-icon [name]="state(d).icon" [size]="20" [tone]="state(d).tone" />
              <div class="main">
                <div class="top"><b>{{ d.what }}</b><span class="tag">{{ source(d) }}</span></div>
                <div class="sub">{{ detail(d) }}</div>
                @if ((d.state === 'in_corso' || d.state === 'in_pausa') && d.size) {
                  <span class="bar" [class.paused]="d.state === 'in_pausa'"><span [style.width.%]="pct(d)"></span></span>
                }
              </div>
              <div class="acts">
                @switch (d.state) {
                  @case ('in_corso') { <button hx-btn size="sm" variant="ghost" icon="pause" (click)="op(d, 'pause')">Pausa</button> }
                  @case ('in_coda') { <button hx-btn size="sm" variant="ghost" icon="pause" (click)="op(d, 'pause')">Pausa</button> }
                  @case ('in_pausa') { <button hx-btn size="sm" icon="play" (click)="op(d, 'resume')">Riprendi</button> }
                  @case ('errore') { <button hx-btn size="sm" icon="refresh" (click)="op(d, 'retry')">Riprova</button> }
                  @case ('fatto') { <button hx-btn size="sm" variant="ghost" icon="trash" (click)="remove(d)">Elimina</button> }
                }
                @if (d.state !== 'fatto') {
                  <button hx-btn size="sm" variant="ghost" icon="x" iconOnly aria-label="Annulla" title="Annulla" (click)="op(d, 'cancel')"></button>
                }
              </div>
            </li>
          }
        </ul>
      }
      @if (offline().length) {
        <p class="note"><hx-icon name="offline" [size]="14" tone="warning" /> Una parte di Hestia non risponde ora: i suoi download ricompaiono quando torna.</p>
      }
    </div>`,
  styles: [`
    :host { display: flex; flex-direction: column; flex: 1; min-height: 0; }
    .body { flex: 1; overflow: auto; padding: 18px 24px 32px; display: flex; flex-direction: column; gap: 12px; }
    .center { display: grid; place-items: center; padding: 40px; }
    .list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; max-width: 860px; }
    .row { display: flex; align-items: center; gap: 12px; padding: 12px 14px; }
    .main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
    .top { display: flex; align-items: baseline; gap: 8px; min-width: 0; }
    .top b { font-weight: 600; font-size: 14px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .tag { font-size: 11.5px; color: var(--text-3); flex-shrink: 0; }
    .sub { font-size: 12.5px; color: var(--text-3); }
    .bar { display: block; height: 4px; border-radius: var(--radius-full); background: var(--surface-3); overflow: hidden; margin-top: 3px; }
    .bar span { display: block; height: 100%; background: var(--accent); transition: width var(--dur) var(--ease); }
    .bar.paused span { background: var(--warning); }
    .acts { display: flex; gap: 4px; flex-shrink: 0; }
    .note { display: flex; gap: 6px; align-items: center; font-size: 12.5px; color: var(--text-3); }
    @media (max-width: 720px) { .body { padding: 14px 12px 28px; } .row { flex-wrap: wrap; } .acts { width: 100%; justify-content: flex-end; } }
    @media (max-width: 860px) { hx-page-header { padding-left: 56px; } }
    @media (max-width: 520px) { .lbl { display: none; } }
  `],
})
export class DownloadsPageComponent {
  private http = inject(HttpClient);
  private dialogs = inject(DialogService);
  private toasts = inject(ToastService);
  rows = signal<DownloadRow[] | null>(null);
  offline = signal<string[]>([]);
  error = signal('');
  busy = signal('');
  sorted = computed(() => [...(this.rows() || [])].sort((a, b) => ORDER.indexOf(a.state) - ORDER.indexOf(b.state)));

  constructor() {
    void this.load();
    // Faster while something moves, calm otherwise.
    let tick = 0;
    const timer = setInterval(() => {
      tick++;
      const moving = (this.rows() || []).some(d => d.state === 'in_corso' || d.state === 'in_coda');
      if (moving || tick % 5 === 0) void this.load();
    }, 2000);
    inject(DestroyRef).onDestroy(() => clearInterval(timer));
  }

  async load() {
    try {
      const r = await firstValueFrom(this.http.get<{ downloads: DownloadRow[]; offline: string[] }>('/api/webui/downloads'));
      this.rows.set(r.downloads || []);
      this.offline.set(r.offline || []);
      this.error.set('');
    } catch (e: any) {
      if (this.rows() === null) this.error.set(e?.error?.detail || 'Hestia non risponde: riprovo tra poco.');
    }
  }

  state(d: DownloadRow) { return STATE[d.state] || STATE.in_coda; }
  source(d: DownloadRow) { return SOURCE[d.source] || d.source; }
  pct(d: DownloadRow) { return d.size ? Math.min(100, (100 * d.done) / d.size) : 0; }

  detail(d: DownloadRow): string {
    if (d.state === 'errore') return d.error || 'Non riuscito.';
    if (d.state === 'fatto') return d.size ? bytes(d.size) : 'Pronto.';
    const parts = [d.size ? `${bytes(d.done)} di ${bytes(d.size)}` : this.state(d).label];
    if (d.state === 'in_corso' && d.speed) parts.push(`${bytes(d.speed)}/s`);
    if (d.state === 'in_corso' && d.eta_s) parts.push(d.eta_s < 60 ? 'meno di un minuto' : `ancora ${Math.round(d.eta_s / 60)} min`);
    if (d.state === 'in_pausa') parts.push('in pausa');
    return parts.join(' · ');
  }

  async op(d: DownloadRow, op: string) {
    try {
      await firstValueFrom(this.http.post(`/api/webui/downloads/${encodeURIComponent(d.module)}/${op}`, { id: d.id }));
    } catch (e: any) {
      this.toasts.error(e?.error?.detail || 'Non è riuscito, riprova tra poco.');
    }
    await this.load();
  }

  async remove(d: DownloadRow) {
    if (!await this.dialogs.confirm(`Eliminare ${d.what}?`, 'Libera spazio sul disco. Se ti serve di nuovo, si riscarica.', 'Elimina', true)) return;
    await this.op(d, 'remove');
  }

}
