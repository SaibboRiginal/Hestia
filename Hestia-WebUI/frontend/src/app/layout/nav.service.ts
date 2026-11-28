import { Injectable, computed, inject, signal } from '@angular/core';
import { NavigationEnd, Router } from '@angular/router';
import { filter } from 'rxjs';
import { PluginsService } from '../features/plugins/plugins.service';
import { PluginPage } from '../features/plugins/plugins.types';
import { assistantName, tr } from '../core/i18n';

/** Where a page lives (hestia_common.plugin_client.PLACES; '' = from the module kind). */
export type Place = 'space' | 'agenda' | 'assistant' | 'notifications' | 'system';
/** One button of the rail = one group; the context panel lists what the group holds. */
export type NavGroup = 'today' | 'chat' | 'agenda' | 'spaces' | 'assistant' | 'notifications' | 'settings';

export interface NavLink { id: string; label: string; icon: string; link: string; online: boolean; badge: number; color: string; }

/** The module colours the manifests declare (PluginClient color=…) as theme-friendly tones. */
const TONES: Record<string, string> = {
  red: '#e5533d', orange: '#e8862a', amber: '#d9971e', yellow: '#d4a514', green: '#22a06b', teal: '#159f8f',
  blue: '#3b6fe0', indigo: '#5b5fd6', purple: '#8b5cf6', pink: '#e2558f', gray: '#6b7480',
};
export const toneOf = (color: string) => TONES[color] ?? 'var(--accent)';

/** The app's own pages of Settings → System (next to the system modules' pages). */
export const SYSTEM_APP_PAGES: NavLink[] = [
  { id: 'app.system', label: tr('Overview'), icon: 'grid', link: '/system', online: true, badge: 0, color: '' },
  { id: 'app.connections', label: tr('Connections'), icon: 'link', link: '/connections', online: true, badge: 0, color: '' },
  { id: 'app.updates', label: tr('Updates'), icon: 'refresh', link: '/updates', online: true, badge: 0, color: '' },
  { id: 'app.machines', label: tr('Machines'), icon: 'host', link: '/machines', online: true, badge: 0, color: '' },
  { id: 'app.download', label: tr('alt::Download'), icon: 'download', link: '/download', online: true, badge: 0, color: '' },
];
const SETTINGS_ROUTES = ['/settings', '/system', '/updates', '/connections', '/machines', '/download', '/d/system'];

/**
 * The navigation model (docs/work/2026-11-27-webui-rethink §3, piece 1), read by the rail, the context panel, the
 * phone bar, the Spaces page and the tabs of a module page. One rule: each page declares its `place`; a sub-page is a
 * tab of its parent and never a list entry of its own.
 */
@Injectable({ providedIn: 'root' })
export class NavService {
  private plugins = inject(PluginsService);
  private router = inject(Router);
  readonly url = signal(this.router.url);
  readonly assistant = assistantName();

  constructor() {
    this.router.events.pipe(filter(e => e instanceof NavigationEnd)).subscribe(() => this.url.set(this.router.url));
  }

  /** Top page of a family: the page itself or its top ancestor in the same module. */
  private topOf(p: PluginPage, pages: PluginPage[]): PluginPage {
    let cur = p;
    for (let i = 0; i < 5 && cur.parent; i++) {
      const up = pages.find(x => x.module === cur.module && x.local_id === cur.parent);
      if (!up) break;
      cur = up;
    }
    return cur;
  }

  placeOf(p: PluginPage): Place {
    const pages = this.plugins.allPages();
    const top = this.topOf(p, pages);
    const declared = (top.place || '') as Place | '';
    if (declared) return declared;
    return this.plugins.modules().get(top.module)?.kind === 'core' ? 'system' : 'space';
  }

  private toLink(p: PluginPage): NavLink {
    const badges = this.plugins.badges();
    const kids = this.plugins.navPages().filter(c => c.module === p.module && c.parent === p.local_id);
    return { id: p.id, label: p.label, icon: p.icon || 'puzzle', link: this.plugins.link(p.module, p.local_id), online: p.online,
             badge: (badges[p.id] ?? 0) + kids.reduce((n, c) => n + (badges[c.id] ?? 0), 0),
             color: toneOf(this.plugins.modules().get(p.module)?.color ?? '') };
  }

  /** Top-level pages (no parent in the same module), visible, per place, in the user's then the manifest order. */
  readonly byPlace = computed(() => {
    const pages = this.plugins.navPages();
    const out: Record<Place, NavLink[]> = { space: [], agenda: [], assistant: [], notifications: [], system: [] };
    for (const p of pages) {
      if (p.parent && pages.some(x => x.module === p.module && x.local_id === p.parent)) continue;
      out[this.placeOf(p)].push(this.toLink(p));
    }
    return out;
  });

  readonly spaces = computed(() => this.byPlace().space);
  /** Settings → System: the app's pages plus the system modules' pages. */
  readonly systemLinks = computed(() => [SYSTEM_APP_PAGES[0], ...this.byPlace().system, ...SYSTEM_APP_PAGES.slice(1)]);
  /** Pages pinned on the rail (only pages that still exist). */
  readonly pins = computed(() => {
    const all = new Map(Object.values(this.byPlace()).flat().map(l => [l.id, l] as [string, NavLink]));
    return this.plugins.navPinned().filter(id => all.has(id)).map(id => all.get(id)!);
  });

  /** The family of the module page on screen: its top page and the sub-pages shown as tabs. */
  readonly family = computed<{ top: NavLink; tabs: NavLink[]; active: string } | null>(() => {
    const m = /^\/p\/([^/?#]+)\/([^?#]*)/.exec(this.url());
    if (!m) return null;
    const module = decodeURIComponent(m[1]);
    const match = this.plugins.matchPage(module, m[2]);
    if (!match) return null;
    const pages = this.plugins.allPages();
    const visible = this.plugins.navPages();
    const top = this.topOf(match.page, pages);
    const tabs = [top, ...visible.filter(c => c.module === module && c.parent === top.local_id && !c.detail)];
    const active = tabs.find(t => t.local_id === match.page.local_id)?.id
      ?? tabs.find(t => t.local_id === match.page.parent)?.id ?? top.id;
    return { top: this.toLink(top), tabs: tabs.length > 1 ? tabs.map(t => this.toLink(t)) : [], active };
  });

  /** The group of the page on screen (which rail button is lit, what the panel lists). */
  readonly group = computed<NavGroup>(() => {
    const path = this.url().split(/[?#]/)[0];
    if (path.startsWith('/chat')) return 'chat';
    if (SETTINGS_ROUTES.some(r => path === r || path.startsWith(r + '/'))) return 'settings';
    if (path.startsWith('/spaces')) return 'spaces';
    const m = /^\/p\/([^/]+)\/(.*)$/.exec(path);
    if (m) {
      const match = this.plugins.matchPage(decodeURIComponent(m[1]), m[2]);
      if (match) {
        const place = this.placeOf(match.page);
        return place === 'space' ? 'spaces' : place === 'system' ? 'settings' : place;
      }
      return 'spaces';
    }
    return 'today';
  });

  /** Where a rail button goes. */
  linkOf(g: NavGroup): string {
    switch (g) {
      case 'today': return '/home';
      case 'chat': return '/chat';
      case 'spaces': return '/spaces';
      case 'settings': return '/settings';
      default: return this.byPlace()[g][0]?.link ?? '/home';
    }
  }
}
