import { ChangeDetectionStrategy, Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { RouterLink } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { UI, DialogService, ToastService } from '../../ui';
import { tr, TrPipe } from '../../core/i18n';

export interface DownloadRow {
  module: string; id: string; what: string; source: string; size: number; done: number;
  speed: number; eta_s: number | null; state: 'queued' | 'running' | 'paused' | 'done' | 'error'; error: string;
}

const STATE: Record<DownloadRow['state'], { label: string; icon: string; tone: string }> = {
  queued: { label: tr('Queued'), icon: 'clock', tone: 'muted' },
  running: { label: tr('In progress'), icon: 'download', tone: 'info' },
  paused: { label: tr('Paused'), icon: 'pause', tone: 'warning' },
  done: { label: tr('Done'), icon: 'check-circle', tone: 'success' },
  error: { label: tr('alt::Failed'), icon: 'alert', tone: 'danger' },
};
const SOURCE: Record<string, string> = { ollama: tr('Model'), whisper: tr('Listening'), http: tr('File'), docker: tr('Program') };
const ORDER: DownloadRow['state'][] = ['running', 'queued', 'paused', 'error', 'done'];

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
  imports: [TrPipe, ...UI, RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <hx-page-header  [title]="'alt::Download' | tr"  [subtitle]="'Models and voices Hestia downloads: progress, pause, retry, space' | tr">
      <a hx-btn size="sm" variant="ghost" icon="volume" routerLink="/p/echo/voice"  [title]="'Prepare the voice: it\\'s done from the Voice page' | tr"><span class="lbl">{{ "Voice" | tr }}</span></a>
      <a hx-btn size="sm" variant="ghost" icon="brain" routerLink="/setup"  [title]="'Choose the brain' | tr"><span class="lbl">{{ "Choose the brain" | tr }}</span></a>
    </hx-page-header>
    <div class="body">
      @if (error()) {
        <hx-empty icon="offline"  [title]="'I can\\'t read the downloads' | tr">{{ error() }}</hx-empty>
      } @else if (rows() === null) {
        <div class="center"><hx-spinner /></div>
      } @else if (!rows()!.length) {
        <hx-empty icon="download"  [title]="'No downloads' | tr">
          {{ "Here appear the brain models and the voices while they download, and they stay so you can delete them." | tr }}
        </hx-empty>
      } @else {
        <ul class="list">
          @for (d of sorted(); track d.module + d.id) {
            <li class="row hx-card">
              <hx-icon [name]="state(d).icon" [size]="20" [tone]="state(d).tone" />
              <div class="main">
                <div class="top"><b>{{ d.what }}</b><span class="tag">{{ source(d) }}</span></div>
                <div class="sub">{{ detail(d) }}</div>
                @if ((d.state === 'running' || d.state === 'paused') && d.size) {
                  <span class="bar" [class.paused]="d.state === 'paused'"><span [style.width.%]="pct(d)"></span></span>
                }
              </div>
              <div class="acts">
                @switch (d.state) {
                  @case ('running') { <button hx-btn size="sm" variant="ghost" icon="pause" (click)="op(d, 'pause')">{{ "Pause" | tr }}</button> }
                  @case ('queued') { <button hx-btn size="sm" variant="ghost" icon="pause" (click)="op(d, 'pause')">{{ "Pause" | tr }}</button> }
                  @case ('paused') { <button hx-btn size="sm" icon="play" (click)="op(d, 'resume')">{{ "Resume" | tr }}</button> }
                  @case ('error') { <button hx-btn size="sm" icon="refresh" (click)="op(d, 'retry')">{{ "Try again" | tr }}</button> }
                  @case ('done') { <button hx-btn size="sm" variant="ghost" icon="trash" (click)="remove(d)">{{ "Delete" | tr }}</button> }
                }
                @if (d.state !== 'done') {
                  <button hx-btn size="sm" variant="ghost" icon="x" iconOnly  [attr.aria-label]="'Cancel' | tr"  [title]="'Cancel' | tr" (click)="op(d, 'cancel')"></button>
                }
              </div>
            </li>
          }
        </ul>
      }
      @if (offline().length) {
        <p class="note"><hx-icon name="offline" [size]="14" tone="warning" /> {{ "A part of Hestia is not answering right now: its downloads come back when it returns." | tr }}</p>
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
      const moving = (this.rows() || []).some(d => d.state === 'running' || d.state === 'queued');
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
      if (this.rows() === null) this.error.set(e?.error?.detail || tr('Hestia doesn\'t answer: I\'ll retry shortly.'));
    }
  }

  state(d: DownloadRow) { return STATE[d.state] || STATE.queued; }
  source(d: DownloadRow) { return SOURCE[d.source] || d.source; }
  pct(d: DownloadRow) { return d.size ? Math.min(100, (100 * d.done) / d.size) : 0; }

  detail(d: DownloadRow): string {
    if (d.state === 'error') return d.error || tr('Failed.');
    if (d.state === 'done') return d.size ? bytes(d.size) : tr('Ready.');
    const parts = [d.size ? `${bytes(d.done)} di ${bytes(d.size)}` : this.state(d).label];
    if (d.state === 'running' && d.speed) parts.push(`${bytes(d.speed)}/s`);
    if (d.state === 'running' && d.eta_s) parts.push(d.eta_s < 60 ? tr('less than a minute') : tr("{0} min left", Math.round(d.eta_s / 60)));
    if (d.state === 'paused') parts.push(tr('paused'));
    return parts.join(' · ');
  }

  async op(d: DownloadRow, op: string) {
    try {
      await firstValueFrom(this.http.post(`/api/webui/downloads/${encodeURIComponent(d.module)}/${op}`, { id: d.id }));
    } catch (e: any) {
      this.toasts.error(e?.error?.detail || tr('It did not work, try again shortly.'));
    }
    await this.load();
  }

  async remove(d: DownloadRow) {
    if (!await this.dialogs.confirm(tr("Delete {0}?", d.what), tr('Frees space on the disk. If you need it again, it downloads again.'), tr('Delete'), true)) return;
    await this.op(d, 'remove');
  }

}
