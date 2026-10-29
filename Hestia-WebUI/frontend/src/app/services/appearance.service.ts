import { Injectable, computed, effect, inject, signal, untracked } from '@angular/core';
import { ThemeService } from '../core/theme/theme.service';
import { PluginsService } from '../features/plugins/plugins.service';

export interface AppearanceNow {
  auto: boolean;
  profile: { key: string; name: string; palette: Record<string, string>; effect: string; background?: string | null };
  why: string;
  pet: { id: string; name: string; images: Record<string, string> } | null;
}

const REFRESH_MS = 30 * 60_000;

/**
 * What the site looks like now (dossier 2026-10-24-tutto-brainstorm-cindy A2 Aphrodite, W7): one call,
 * `GET /api/appearance/now?client=webui` through the Aphrodite plugin door; the profile's accents go over the
 * user's own light/dark theme, the light effect and the pet are drawn by `<hx-appearance-layer>`. Read again when
 * the tab comes back after a while (a new day can bring a new profile). No Aphrodite = the standard look.
 */
@Injectable({ providedIn: 'root' })
export class AppearanceService {
  private plugins = inject(PluginsService);
  private theme = inject(ThemeService);
  readonly now = signal<AppearanceNow | null>(null);
  private at = 0;
  private started = false;

  readonly lightEffect = computed(() => this.now()?.profile.effect || 'none');
  readonly pet = computed(() => this.now()?.pet ?? null);
  private readonly hasModule = computed(() => this.plugins.modules().has('aphrodite'));

  constructor() {
    // The catalog arrives after the first paint, and the module can come and go.
    effect(() => { this.hasModule(); if (this.started) untracked(() => void this.load()); });
  }

  start(): void {
    if (this.started) return;
    this.started = true;
    void this.load();
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible' && Date.now() - this.at > REFRESH_MS) void this.load();
    });
  }

  async load(): Promise<void> {
    this.at = Date.now();
    if (!this.plugins.modules().has('aphrodite')) { this.apply(null); return; }
    const r = await this.plugins.call<AppearanceNow>('aphrodite', 'GET', '/api/appearance/now', { query: { client: 'webui' } });
    if (r.ok && r.data?.profile) this.apply(r.data);
  }

  private apply(now: AppearanceNow | null): void {
    this.now.set(now);
    this.theme.setPalette(now?.profile.palette ?? {});
  }

  /** URL of a pet pose (blob served by Aphrodite through the plugin image door), '' when the pose has no picture. */
  petImage(pose: string): string {
    const p = this.pet();
    const blob = p?.images[pose] || p?.images['idle'];
    if (!blob) return '';
    const host = this.plugins.host('aphrodite') as { image: (path: string) => string };
    return host.image(`/api/appearance/image/${encodeURIComponent(blob)}`);
  }
}
