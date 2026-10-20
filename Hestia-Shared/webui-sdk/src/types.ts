/**
 * Hestia WebUI plugin contract (SDK v1) — what the WebUI gives a plugin element.
 * Full contract: docs/work/2026-10-17-client-plugins/SPEC.md §4.
 *
 * The WebUI creates the plugin's custom element and sets two properties before connecting it:
 *   el.host = HestiaHost   (what the plugin can do)
 *   el.ctx  = PluginContext (where it is: route params, widget params, size, theme)
 */

export type Tone = 'neutral' | 'info' | 'success' | 'warning' | 'danger' | 'accent';
export type WidgetSize = 's' | 'm' | 'l' | 'xl';
export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

export interface ApiResult<T = any> {
  status: number;          // HTTP status from the module (0 = offline / unreachable)
  ok: boolean;
  data: T;
  error?: string;          // 'offline' | 'unreachable' | 'forbidden' | module detail
}

export interface Upload {
  name: string;
  mime: string;
  data_b64: string;        // ≤ 8 MB after on-device resize
  width?: number;
  height?: number;
}

export interface PluginContext {
  module: string;                    // 'scout'
  surface: 'page' | 'widget' | 'settings_panel';   // settings_panel: inside the module's own settings
  id: string;                        // local surface id ('case', 'nuove')
  params: Record<string, string>;    // route params (':id') for pages, configured params for widgets
  query: Record<string, string>;     // page query string
  size?: WidgetSize;                 // widgets only
  title?: string;                    // widget title override
  theme: 'light' | 'dark';
  client: 'webui';
  phone: boolean;                    // < 861 px
}

export interface AssistantOpen {
  label: string;                     // chip the user sees
  hints?: Record<string, string | number>;   // compact key/values for Oracle (ids, dates)
  prompt?: string;
  suggestions?: string[];
}

export interface KeyValueStore {
  get<T = any>(key: string): Promise<T | undefined>;
  set(key: string, value: unknown): Promise<void>;
  delete(key: string): Promise<void>;
  keys(): Promise<string[]>;
  all<T = any>(): Promise<Array<[string, T]>>;
}

export type HostEvent = 'refresh' | 'theme' | 'visible' | 'hidden' | 'online' | 'offline';

export interface HestiaHost {
  readonly sdk: '1';
  readonly module: string;
  /** Calls ITS OWN module through WebUI → Hub. Path must start with the manifest's api_prefix. */
  api<T = any>(method: HttpMethod, path: string, opts?: { query?: Record<string, any>; body?: unknown }): Promise<ApiResult<T>>;
  /** URL of an image served by its module (module answers {mime, data_b64}; the WebUI serves bytes). */
  image(path: string): string;
  /** Lets the user pick a photo/file, resizes images on the device (long side ≤ maxSide). */
  upload(opts?: { accept?: string; maxSide?: number; multiple?: boolean; capture?: boolean }): Promise<Upload[]>;
  /** Navigate inside the plugin ('case/123') or to another module's page ({module, page}). */
  navigate(page: string, params?: Record<string, string>, module?: string): void;
  link(page: string, params?: Record<string, string>, module?: string): string;
  toast(text: string, tone?: Tone, action?: { label: string; run: () => void }): void;
  confirm(title: string, text: string, opts?: { label?: string; danger?: boolean }): Promise<boolean>;
  assistant(open: AssistantOpen): void;
  /** Browser notification (asks permission once). Returns false when not allowed. */
  notify(title: string, body?: string, opts?: { tag?: string }): Promise<boolean>;
  /** Per-client preferences of this plugin (stored by the WebUI in its own settings). */
  readonly config: { get<T = any>(key: string, fallback?: T): T; set(key: string, value: unknown): Promise<void> };
  /** IndexedDB key/value store namespaced 'hestia.<module>.<name>' (offline data, sync queues). */
  store(name: string): KeyValueStore;
  readonly online: boolean;
  on(event: HostEvent, cb: () => void): () => void;
}

/** Quick action chip returned by a dynamic `source` (§4.2b). */
export interface QuickChip {
  id: string;
  label: string;
  icon?: string;
  state?: 'todo' | 'done' | 'late';
  hint?: string;            // "2/3 questa settimana"
  favorite?: boolean;
}
