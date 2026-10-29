import { Injectable, inject, signal } from '@angular/core';
import { NavigationEnd, Router } from '@angular/router';
import { filter } from 'rxjs';
import { PluginsService } from '../features/plugins/plugins.service';

/** One suggestion of the «Adesso» row (GET /api/metis/adesso). */
export interface AdessoItem { tool: string; title: string; module: string; args: Record<string, unknown>; reason: string; source: string; }
/** One feature of «Scopri» (GET /api/metis/scopri). */
export interface ScopriItem { tool: string; title: string; description: string; module: string; uses: number; reason: string;
  area?: string; area_label?: string; area_icon?: string; area_order?: number; }

type TapKind = 'tool' | 'page' | 'action';
interface Tap { client: 'webui'; kind: TapKind; ref: string; label?: string; at: string; }

const FLUSH_MS = 20_000;
const MAX_BATCH = 40;

/**
 * Usage taps and suggestions of the WebUI (dossier 2026-10-24-tutto-brainstorm-cindy C11 + C14, W7): every page
 * opened and every action run becomes a tap, sent in batches to Metis (`POST /api/metis/usage`) so «Adesso» learns
 * from this client too; reads «Adesso» and «Scopri». Everything goes through the Metis plugin door (api_prefix
 * /api/metis/), never a new URL.
 */
@Injectable({ providedIn: 'root' })
export class MetisService {
  private plugins = inject(PluginsService);
  private router = inject(Router);
  private queue: Tap[] = [];
  private timer: ReturnType<typeof setTimeout> | null = null;
  private started = false;
  private lastPage = '';

  readonly adesso = signal<AdessoItem[]>([]);
  readonly adessoLoaded = signal(false);

  start(): void {
    if (this.started) return;
    this.started = true;
    this.router.events.pipe(filter((e): e is NavigationEnd => e instanceof NavigationEnd)).subscribe(e => this.pageTap(e.urlAfterRedirects));
    document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') void this.flush(); });
  }

  /** A page opened: `/p/<module>/<page>` (module pages) or the WebUI's own page; detail ids are dropped. */
  private pageTap(url: string): void {
    const path = url.split('?')[0].split('#')[0];
    let ref = '';
    const m = /^\/p\/([^/]+)\/([^/]+)/.exec(path);
    if (m) ref = `${decodeURIComponent(m[1])}.${decodeURIComponent(m[2])}`;
    else if (/^\/d\//.test(path)) ref = 'webui.dashboard';
    else if (path.length > 1) ref = `webui.${path.slice(1).split('/')[0]}`;
    if (!ref || ref === this.lastPage) return;
    this.lastPage = ref;
    this.tap('page', ref);
  }

  tap(kind: TapKind, ref: string, label?: string): void {
    if (!ref) return;
    this.queue.push({ client: 'webui', kind, ref: ref.slice(0, 120), label: label?.slice(0, 120), at: new Date().toISOString() });
    if (this.queue.length >= MAX_BATCH) { void this.flush(); return; }
    this.timer ??= setTimeout(() => void this.flush(), FLUSH_MS);
  }

  private async flush(): Promise<void> {
    if (this.timer) { clearTimeout(this.timer); this.timer = null; }
    if (!this.queue.length || !this.plugins.modules().has('metis')) return;
    const taps = this.queue.splice(0, MAX_BATCH);
    const r = await this.plugins.call('metis', 'POST', '/api/metis/usage', { body: { taps } });
    if (!r.ok && r.status === 0) this.queue.unshift(...taps.slice(-MAX_BATCH));   // offline: retry on the next tap
  }

  async loadAdesso(): Promise<void> {
    if (!this.plugins.modules().has('metis')) { this.adesso.set([]); this.adessoLoaded.set(true); return; }
    const r = await this.plugins.call<{ items?: AdessoItem[] }>('metis', 'GET', '/api/metis/adesso', { query: { client: 'webui' } });
    if (r.ok) this.adesso.set((r.data?.items ?? []).slice(0, 6));
    this.adessoLoaded.set(true);
  }

  async scopri(): Promise<{ ok: boolean; items: ScopriItem[]; total: number; tools: number }> {
    const r = await this.plugins.call<{ items?: ScopriItem[]; total?: number; tools?: number }>('metis', 'GET', '/api/metis/scopri', { query: { client: 'webui', limit: 50 } });
    return { ok: r.ok, items: r.data?.items ?? [], total: r.data?.total ?? 0, tools: r.data?.tools ?? 0 };
  }

  /** Opens a tool on the «Comandi» page with its arguments filled (and run at once when it needs nothing more). */
  open(tool: string, args: Record<string, unknown> = {}, label?: string): void {
    this.tap('tool', tool, label);
    const params: Record<string, string> = { command: tool, run: '1' };
    if (Object.keys(args).length) params['args'] = JSON.stringify(args);
    void this.router.navigateByUrl(this.plugins.link('mcp', 'comandi', params));
  }
}
