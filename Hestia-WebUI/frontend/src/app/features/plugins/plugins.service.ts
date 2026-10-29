import { Injectable, computed, effect, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Router } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { AuthService } from '../../services/auth.service';
import { AssistantService } from '../../services/assistant.service';
import { DialogService, ToastService } from '../../ui';
import { ThemeService } from '../../core/theme/theme.service';
import { CentralSettingsApi, apiError } from '../settings/central-settings.api';
import {
  Dashboard, DashboardItem, PluginBundle, PluginCatalog, PluginModule, PluginPage, PluginWidget, QuickActionDef, WidgetSize,
} from './plugins.types';

/** WebUI settings that hold this client's plugin configuration (Themis, user scope, client layer "webui"). */
export const CFG = {
  hidden: 'webui.plugins.hidden',
  order: 'webui.plugins.order',
  quick: 'webui.home.quick',
  dashboards: 'webui.dashboards',
  prefs: 'webui.plugins.prefs',
  pinned: 'webui.sidebar.pinned',
  collapsed: 'webui.sidebar.collapsed',
} as const;

export const SIZE_SPAN: Record<WidgetSize, { c: number; r: number }> = { s: { c: 1, r: 1 }, m: { c: 2, r: 1 }, l: { c: 2, r: 2 }, xl: { c: 4, r: 2 } };

type HostEvent = 'refresh' | 'theme' | 'visible' | 'hidden' | 'online' | 'offline';
const BASE = '/api/webui/plugins';
/** Ready-made dashboard of the core modules' `auto` widgets (SPEC docs/work/2026-10-18-moduli-core-e-mcp-esterno §A6). */
/** Titled «Stato del sistema» (2026-10-29): «Sistema» is the sidebar page of the system modules, only one of each name. */
const SYSTEM_DASHBOARD: Dashboard = { id: 'sistema', title: 'Stato del sistema', icon: 'pulse', auto: true, kind: 'core', created_by: 'user', items: [] };

/**
 * Client plugins runtime (SPEC docs/work/2026-10-17-client-plugins §4): Hub catalog for client=webui, this client's
 * configuration (visibility, order, pinned quick actions, dashboards, plugin prefs), bundle loading and the host
 * API given to every plugin element. Module bundles are fetched with the access token and imported as blob
 * modules; their bare imports (`@hestia/webui-sdk`, `lit`) resolve to /plugins/_sdk/sdk.js via the import map.
 */
@Injectable({ providedIn: 'root' })
export class PluginsService {
  private http = inject(HttpClient);
  private auth = inject(AuthService);
  private router = inject(Router);
  private toasts = inject(ToastService);
  private dialogs = inject(DialogService);
  private assistant = inject(AssistantService);
  private theme = inject(ThemeService);
  private settingsApi = inject(CentralSettingsApi);

  readonly catalog = signal<PluginCatalog | null>(null);
  readonly catalogError = signal(false);
  readonly configLoaded = signal(false);
  readonly hidden = signal<string[]>([]);
  readonly order = signal<string[]>([]);
  readonly quickPins = signal<string[]>([]);
  readonly dashboardsCfg = signal<Dashboard[] | null>(null);   // null = never saved (Home is automatic)
  readonly prefs = signal<Record<string, Record<string, unknown>>>({});
  /** Sidebar arranged by the user: pinned entry ids (in order) and collapsed section keys. */
  readonly navPinned = signal<string[]>([]);
  readonly navCollapsed = signal<string[]>([]);
  /** Counters next to plugin pages that declare a `badge` (page id → number). */
  readonly badges = signal<Record<string, number>>({});
  readonly online = signal(typeof navigator === 'undefined' ? true : navigator.onLine);

  readonly modules = computed(() => new Map((this.catalog()?.modules ?? []).map(m => [m.module, m] as [string, PluginModule])));
  private readonly webui = computed(() => this.catalog()?.contributions?.webui ?? {});
  readonly allPages = computed(() => this.webui().page ?? []);
  readonly allWidgets = computed(() => this.webui().widget ?? []);
  readonly allQuick = computed(() => this.webui().quick_action ?? []);
  readonly settingsPanels = computed(() => this.webui().settings_panel ?? []);
  readonly bundles = computed(() => new Map((this.webui().bundle ?? []).map(b => [b.module, b] as [string, PluginBundle])));

  /** Sidebar pages: visible, top-level or children, in the user's order then the manifest order. */
  readonly navPages = computed(() => {
    const order = this.order();
    const rank = (p: PluginPage) => { const i = order.indexOf(p.id); return i < 0 ? 1000 + p.order : i; };
    return this.allPages().filter(p => !p.detail && !this.isHidden(p.id)).sort((a, b) => rank(a) - rank(b) || a.label.localeCompare(b.label));
  });
  readonly widgets = computed(() => this.allWidgets().filter(w => !this.isHidden(w.id)));
  readonly quickActions = computed(() => this.allQuick().filter(q => !this.isHidden(q.id)));

  /** Dashboards: the saved ones (or the automatic Home built from the domain modules' visible `auto` widgets), plus
   *  the ready-made «Sistema» built from the core modules' `auto` widgets until the user deletes it. */
  readonly dashboards = computed<Dashboard[]>(() => {
    const saved = this.dashboardsCfg() ?? [];
    const list: Dashboard[] = saved.length ? saved : [{ id: 'home', title: 'Home', icon: 'home', auto: true, created_by: 'user', items: [] }];
    const savedSystem = list.some(d => d.id === SYSTEM_DASHBOARD.id);
    return [...list, ...(savedSystem ? [] : [SYSTEM_DASHBOARD])]
      .filter(d => !d.removed)
      .map(d => d.id === SYSTEM_DASHBOARD.id && d.title === 'Sistema' ? { ...d, title: SYSTEM_DASHBOARD.title } : d)
      .map(d => d.auto ? { ...d, items: this.autoItems(d.items, d.dismissed, d.kind ?? 'domain') } : d)
      .filter(d => savedSystem || d.id !== SYSTEM_DASHBOARD.id || d.items.length > 0);   // no core widget yet: no empty tab
  });

  private started = false;
  private bundleLoads = new Map<string, Promise<boolean>>();
  private listeners = new Map<string, Set<{ ev: HostEvent; cb: () => void }>>();

  constructor() {
    effect(() => { this.theme.active(); this.emitAll('theme'); });
  }

  // ── lifecycle ────────────────────────────────────────────────────────
  start(): void {
    if (this.started) return;
    this.started = true;
    void this.refreshCatalog();
    void this.loadConfig();
    // Config too: a dashboard approved from a chat or from another device shows up without a reload.
    setInterval(() => { if (document.visibilityState === 'visible') { void this.refreshCatalog(); void this.loadConfig(); } }, 60_000);
    document.addEventListener('visibilitychange', () => {
      const visible = document.visibilityState === 'visible';
      this.emitAll(visible ? 'visible' : 'hidden');
      if (visible) void this.refreshCatalog();
    });
    window.addEventListener('online', () => { this.online.set(true); this.emitAll('online'); void this.refreshCatalog(); });
    window.addEventListener('offline', () => { this.online.set(false); this.emitAll('offline'); });
  }

  async refreshCatalog(fresh = false): Promise<void> {
    try {
      const cat = await firstValueFrom(this.http.get<PluginCatalog>(`${BASE}/catalog`, { params: fresh ? { fresh: 'true' } : {} }));
      const prev = this.catalog();
      this.catalog.set(cat);
      this.catalogError.set(false);
      void this.refreshBadges();
      // A bundle whose version changed is reloaded on next use (elements already defined stay: definePlugin is idempotent).
      for (const b of cat.contributions?.webui?.bundle ?? []) {
        const old = prev?.contributions?.webui?.bundle?.find(x => x.module === b.module);
        if (old && old.version !== b.version) this.bundleLoads.delete(b.module);
      }
    } catch {
      this.catalogError.set(true);
    }
  }

  async loadConfig(): Promise<void> {
    try {
      const page = await this.settingsApi.items('webui');
      const val = (k: string) => page.items.find(i => i.key === k)?.value;
      this.hidden.set(asList(val(CFG.hidden)));
      this.order.set(asList(val(CFG.order)));
      this.quickPins.set(asList(val(CFG.quick)));
      const dash = val(CFG.dashboards) as { dashboards?: Dashboard[] } | undefined;
      this.dashboardsCfg.set(Array.isArray(dash?.dashboards) && dash!.dashboards.length ? dash!.dashboards : null);
      const prefs = val(CFG.prefs);
      this.prefs.set(prefs && typeof prefs === 'object' ? prefs as Record<string, Record<string, unknown>> : {});
      this.navPinned.set(asList(val(CFG.pinned)));
      this.navCollapsed.set(asList(val(CFG.collapsed)));
    } catch {
      /* Themis down: defaults (everything visible, automatic Home) */
    } finally {
      this.configLoaded.set(true);
    }
  }

  /** Saves one configuration key on this client's layer (Themis keeps history/undo). */
  async saveConfig(key: string, value: unknown): Promise<boolean> {
    try {
      await this.settingsApi.set(key, value, 'client');
      return true;
    } catch (e) {
      this.toasts.error(apiError(e, 'Impostazione non salvata'));
      return false;
    }
  }

  // ── visibility / ordering / pins ─────────────────────────────────────
  isHidden(id: string): boolean {
    const h = this.hidden();
    return h.includes(id) || h.includes(`${id.split('.')[0]}.*`);
  }

  async setHidden(id: string, hide: boolean): Promise<void> {
    const next = hide ? [...new Set([...this.hidden(), id])] : this.hidden().filter(x => x !== id);
    const prev = this.hidden();
    this.hidden.set(next);
    if (!(await this.saveConfig(CFG.hidden, next))) this.hidden.set(prev);
  }

  async setOrder(ids: string[]): Promise<void> {
    this.order.set(ids);
    await this.saveConfig(CFG.order, ids);
  }

  /** Pins/unpins a sidebar entry; a pinned entry leaves its own section (never shown twice). */
  async toggleNavPin(id: string): Promise<void> {
    const prev = this.navPinned();
    const next = prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id];
    this.navPinned.set(next);
    if (!(await this.saveConfig(CFG.pinned, next))) this.navPinned.set(prev);
  }

  async setNavPinned(ids: string[]): Promise<void> {
    const prev = this.navPinned();
    this.navPinned.set(ids);
    if (!(await this.saveConfig(CFG.pinned, ids))) this.navPinned.set(prev);
  }

  async toggleNavSection(key: string): Promise<void> {
    const prev = this.navCollapsed();
    const next = prev.includes(key) ? prev.filter(x => x !== key) : [...prev, key];
    this.navCollapsed.set(next);
    if (!(await this.saveConfig(CFG.collapsed, next))) this.navCollapsed.set(prev);
  }

  /** Reads every visible page badge through the page's own module (same api_prefix guard as plugin calls). */
  async refreshBadges(): Promise<void> {
    const pages = this.navPages().filter(p => p.badge?.source && p.online);
    if (!pages.length) { if (Object.keys(this.badges()).length) this.badges.set({}); return; }
    const out: Record<string, number> = {};
    await Promise.all(pages.map(async p => {
      try {
        const r = await this.call<Record<string, unknown> | null>(p.module, 'GET', p.badge!.source);
        const n = r.ok ? Number(r.data?.[p.badge!.field]) : NaN;
        if (Number.isFinite(n) && n > 0) out[p.id] = n;
      } catch { /* module unreachable: no badge */ }
    }));
    this.badges.set(out);
  }

  async togglePin(key: string): Promise<void> {
    const pins = this.quickPins();
    const next = pins.includes(key) ? pins.filter(k => k !== key) : [...pins, key];
    this.quickPins.set(next);
    if (!(await this.saveConfig(CFG.quick, next))) this.quickPins.set(pins);
  }

  async saveDashboards(list: Dashboard[]): Promise<boolean> {
    const prev = this.dashboardsCfg();
    // Deleting the ready-made «Sistema» leaves a marker (kept on later saves), otherwise it would be offered again at once.
    const sys = SYSTEM_DASHBOARD.id;
    const wasRemoved = (prev ?? []).some(d => d.id === sys && d.removed) || this.dashboards().some(d => d.id === sys);
    if (!list.some(d => d.id === sys) && wasRemoved) list = [...list, { ...SYSTEM_DASHBOARD, items: [], removed: true }];
    this.dashboardsCfg.set(list);
    const ok = await this.saveConfig(CFG.dashboards, { dashboards: list });
    if (!ok) this.dashboardsCfg.set(prev);
    return ok;
  }

  private autoItems(existing: DashboardItem[], dismissed: string[] = [], kind: 'domain' | 'core' = 'domain'): DashboardItem[] {
    const have = new Set([...existing.map(i => i.widget), ...dismissed]);
    const ofKind = (w: PluginWidget) => (this.modules().get(w.module)?.kind ?? 'domain') === kind;
    const extra = this.widgets().filter(w => w.auto && ofKind(w) && !have.has(w.id)).map(w => ({ widget: w.id, size: w.size }));
    return [...existing, ...extra];
  }

  widget(id: string): PluginWidget | undefined { return this.allWidgets().find(w => w.id === id); }

  /** Page of a module matching a path ('case/123' → page 'case/:id' with {id: '123'}). */
  matchPage(module: string, path: string): { page: PluginPage; params: Record<string, string> } | null {
    const parts = path.split('/').filter(Boolean);
    const pages = this.allPages().filter(p => p.module === module);
    if (!parts.length) {
      const first = pages.filter(p => !p.detail && !p.parent).sort((a, b) => a.order - b.order)[0];
      return first ? { page: first, params: {} } : null;
    }
    for (const page of pages) {
      const pat = page.local_id.split('/');
      if (pat.length !== parts.length) continue;
      const params: Record<string, string> = {};
      if (pat.every((seg, i) => seg.startsWith(':') ? (params[seg.slice(1)] = decodeURIComponent(parts[i]), true) : seg === parts[i]))
        return { page, params };
    }
    return null;
  }

  // ── bundles ──────────────────────────────────────────────────────────
  /** Loads (once per version) the module's WebUI bundle: fetched with the token, imported as a blob module. */
  loadBundle(module: string): Promise<boolean> {
    const existing = this.bundleLoads.get(module);
    if (existing) return existing;
    const bundle = this.bundles().get(module);
    if (!bundle?.entry) return Promise.resolve(false);
    const file = bundle.entry.replace(/^\/ui\/webui\//, '');
    const p = (async () => {
      try {
        const code = await firstValueFrom(this.http.get(`${BASE}/${encodeURIComponent(module)}/bundle/${file}?v=${encodeURIComponent(bundle.version)}`, { responseType: 'text' }));
        const url = URL.createObjectURL(new Blob([code], { type: 'text/javascript' }));
        try { await dynamicImport(url); } finally { URL.revokeObjectURL(url); }
        return true;
      } catch (e) {
        console.warn(`event=plugin_bundle_failed module=${module}`, e);
        this.bundleLoads.delete(module);
        return false;
      }
    })();
    this.bundleLoads.set(module, p);
    return p;
  }

  // ── host API (SDK HestiaHost) ────────────────────────────────────────
  emit(module: string, ev: HostEvent): void {
    for (const l of this.listeners.get(module) ?? []) if (l.ev === ev) { try { l.cb(); } catch { /* plugin error */ } }
  }

  private emitAll(ev: HostEvent): void { for (const m of this.listeners.keys()) this.emit(m, ev); }

  /** Calls a plugin's own module through the WebUI proxy (path must be under its api_prefix, else 403). */
  async call<T = unknown>(module: string, method: string, path: string, opts: { query?: Record<string, unknown>; body?: unknown } = {}):
      Promise<{ status: number; ok: boolean; data: T; error?: string }> {
    if (!navigator.onLine) return { status: 0, ok: false, data: null as T, error: 'offline' };
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(opts.query ?? {})) if (v !== undefined && v !== null && v !== '') qs.set(k, String(v));
    const url = `${BASE}/${encodeURIComponent(module)}/call/${path.replace(/^\//, '')}${qs.toString() ? '?' + qs : ''}`;
    const headers: Record<string, string> = {};
    const token = this.auth.getToken();
    if (token) headers['X-Access-Token'] = token;
    if (opts.body !== undefined) headers['Content-Type'] = 'application/json';
    try {
      const resp = await fetch(url, { method: method.toUpperCase(), headers, body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined });
      const text = await resp.text();
      let data: any = null;
      try { data = text ? JSON.parse(text) : null; } catch { data = text; }
      const error = resp.ok ? undefined
        : resp.status === 403 ? 'forbidden'
        : resp.status === 502 || resp.status === 503 ? 'unreachable'
        : (typeof data?.detail === 'string' ? data.detail : `HTTP ${resp.status}`);
      return { status: resp.status, ok: resp.ok, data, error };
    } catch {
      return { status: 0, ok: false, data: null as T, error: 'offline' };
    }
  }

  host(module: string): object {
    const svc = this;
    const tone = (t?: string) => (t === 'success' || t === 'danger' || t === 'warning' ? t : 'info') as 'info' | 'success' | 'danger' | 'warning';
    return {
      sdk: '1',
      module,
      api: (method: string, path: string, opts?: { query?: Record<string, unknown>; body?: unknown }) => svc.call(module, method, path, opts),
      image: (path: string) => {
        const token = svc.auth.getToken();
        return `${BASE}/${encodeURIComponent(module)}/image?path=${encodeURIComponent(path)}${token ? `&token=${encodeURIComponent(token)}` : ''}`;
      },
      upload: (opts?: { accept?: string; maxSide?: number; multiple?: boolean; capture?: boolean }) => pickFiles(opts),
      navigate: (page: string, params?: Record<string, string>, other?: string) =>
        void svc.router.navigateByUrl(svc.link(other || module, page, params)),
      link: (page: string, params?: Record<string, string>, other?: string) => svc.link(other || module, page, params),
      toast: (text: string, t?: string, action?: { label: string; run: () => void }) => svc.toasts.show(text, tone(t), action, action ? 6000 : 4500),
      confirm: (title: string, text: string, o?: { label?: string; danger?: boolean }) => svc.dialogs.confirm(title, text, o?.label ?? 'Conferma', !!o?.danger),
      assistant: (o: { label: string; hints?: Record<string, string | number>; prompt?: string; suggestions?: string[] }) =>
        svc.assistant.open({ page: `plugin:${module}`, intent: 'ask', label: o.label, hints: { module, ...(o.hints ?? {}) }, prompt: o.prompt, suggestions: o.suggestions }),
      notify: (title: string, body?: string, o?: { tag?: string }) => notify(title, body, o?.tag),
      config: {
        get: (key: string, fallback?: unknown) => (svc.prefs()[module] ?? {})[key] ?? fallback,
        set: async (key: string, value: unknown) => {
          const next = { ...svc.prefs(), [module]: { ...(svc.prefs()[module] ?? {}), [key]: value } };
          svc.prefs.set(next);
          await svc.saveConfig(CFG.prefs, next);
        },
      },
      store: (name: string) => kvStore(`hestia.${module}.${name}`),
      get online() { return svc.online(); },
      on: (ev: HostEvent, cb: () => void) => {
        const set = svc.listeners.get(module) ?? new Set();
        const entry = { ev, cb };
        set.add(entry);
        svc.listeners.set(module, set);
        return () => set.delete(entry);
      },
    };
  }

  link(module: string, page: string, params?: Record<string, string>): string {
    const qs = params && Object.keys(params).length ? '?' + new URLSearchParams(params).toString() : '';
    return `/p/${encodeURIComponent(module)}/${page.replace(/^\//, '')}${qs}`;
  }

  context(module: string, surface: 'page' | 'widget' | 'settings_panel', id: string, extra: { params?: Record<string, unknown>; query?: Record<string, string>; size?: WidgetSize; title?: string } = {}) {
    return {
      module, surface, id,
      params: Object.fromEntries(Object.entries(extra.params ?? {}).map(([k, v]) => [k, v == null ? '' : String(v)])),
      query: extra.query ?? {},
      size: extra.size, title: extra.title,
      theme: this.theme.active().mode,
      client: 'webui',
      phone: window.innerWidth < 861,
    };
  }
}

// ── helpers ────────────────────────────────────────────────────────────

function asList(v: unknown): string[] { return Array.isArray(v) ? v.map(String) : []; }

/** `import()` of a runtime URL (blob: module). Not `new Function` (CSP has no unsafe-eval); the bundler leaves a
 *  non-literal import untouched. CSP allows `script-src blob:` for this (Program.cs). */
const dynamicImport = (u: string): Promise<unknown> => import(/* @vite-ignore */ /* webpackIgnore: true */ u);

async function notify(title: string, body?: string, tag?: string): Promise<boolean> {
  if (!('Notification' in window)) return false;
  let perm = Notification.permission;
  if (perm === 'default') perm = await Notification.requestPermission();
  if (perm !== 'granted') return false;
  try {
    const reg = await navigator.serviceWorker?.getRegistration();
    if (reg) await reg.showNotification(title, { body, tag });
    else new Notification(title, { body, tag });
    return true;
  } catch { return false; }
}

/** File picker; images are resized on the device (long side ≤ maxSide, JPEG) and returned as base64. */
function pickFiles(opts: { accept?: string; maxSide?: number; multiple?: boolean; capture?: boolean } = {}) {
  return new Promise<Array<{ name: string; mime: string; data_b64: string; width?: number; height?: number }>>(resolve => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = opts.accept ?? 'image/*';
    input.multiple = !!opts.multiple;
    if (opts.capture) input.setAttribute('capture', 'environment');
    input.onchange = async () => {
      const files = Array.from(input.files ?? []);
      const out = [];
      for (const f of files) {
        try { out.push(f.type.startsWith('image/') && f.type !== 'image/svg+xml' ? await resizeImage(f, opts.maxSide ?? 2048) : await rawFile(f)); }
        catch { /* unreadable file: skipped */ }
      }
      resolve(out.filter(u => u.data_b64.length * 0.75 <= 8 * 1024 * 1024));
    };
    input.oncancel = () => resolve([]);
    input.click();
  });
}

async function rawFile(f: File) {
  const buf = new Uint8Array(await f.arrayBuffer());
  let bin = '';
  for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode(...buf.subarray(i, i + 0x8000));
  return { name: f.name, mime: f.type || 'application/octet-stream', data_b64: btoa(bin) };
}

async function resizeImage(f: File, maxSide: number) {
  const bmp = await createImageBitmap(f);
  const scale = Math.min(1, maxSide / Math.max(bmp.width, bmp.height));
  const w = Math.round(bmp.width * scale), h = Math.round(bmp.height * scale);
  const canvas = document.createElement('canvas');
  canvas.width = w; canvas.height = h;
  canvas.getContext('2d')!.drawImage(bmp, 0, 0, w, h);
  bmp.close();
  const dataUrl = canvas.toDataURL('image/jpeg', 0.86);
  return { name: f.name.replace(/\.[^.]+$/, '') + '.jpg', mime: 'image/jpeg', data_b64: dataUrl.split(',')[1], width: w, height: h };
}

/** Tiny IndexedDB key/value store (one database per plugin store). */
function kvStore(dbName: string) {
  let dbp: Promise<IDBDatabase> | null = null;
  const db = () => dbp ??= new Promise<IDBDatabase>((res, rej) => {
    const req = indexedDB.open(dbName, 1);
    req.onupgradeneeded = () => req.result.createObjectStore('kv');
    req.onsuccess = () => res(req.result);
    req.onerror = () => rej(req.error);
  });
  const run = async <T>(mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest<T>) => {
    const d = await db();
    return new Promise<T>((res, rej) => {
      const r = fn(d.transaction('kv', mode).objectStore('kv'));
      r.onsuccess = () => res(r.result);
      r.onerror = () => rej(r.error);
    });
  };
  return {
    get: (key: string) => run('readonly', s => s.get(key)),
    set: async (key: string, value: unknown) => { await run('readwrite', s => s.put(value, key)); },
    delete: async (key: string) => { await run('readwrite', s => s.delete(key)); },
    keys: async () => (await run('readonly', s => s.getAllKeys())).map(String),
    all: async () => {
      const [keys, values] = await Promise.all([run('readonly', s => s.getAllKeys()), run('readonly', s => s.getAll())]);
      return keys.map((k, i) => [String(k), values[i]] as [string, unknown]);
    },
  };
}
