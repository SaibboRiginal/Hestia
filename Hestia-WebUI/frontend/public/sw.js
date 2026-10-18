/* Hestia WebUI service worker (SPEC docs/work/2026-10-17-client-plugins §4.5b).
 * Offline = last seen app shell, plugin catalog, client settings and every plugin bundle.
 * - navigations: network first, cached shell when offline
 * - app assets (hashed js/css), SDK runtime, plugin bundles: stale-while-revalidate
 * - catalog + settings reads: network first, last copy when offline
 * Everything else (/api/* writes, chat, images) goes straight to the network: no silent queue. */
const SHELL = 'hestia-shell-v1';
const DATA = 'hestia-data-v1';

self.addEventListener('install', e => {
  e.waitUntil(caches.open(SHELL).then(c => c.addAll(['/', '/manifest.webmanifest', '/icon.svg'])).catch(() => {}));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil((async () => {
    for (const k of await caches.keys()) if (![SHELL, DATA].includes(k)) await caches.delete(k);
    await self.clients.claim();
  })());
});

self.addEventListener('message', e => {
  if (e.data === 'logout') e.waitUntil(caches.delete(DATA));
});

// The access token travels in a header; cache keys must not depend on it.
const key = req => new Request(req.url, { method: 'GET' });

async function networkFirst(req, cacheName) {
  const cache = await caches.open(cacheName);
  try {
    const res = await fetch(req);
    if (res.ok) await cache.put(key(req), res.clone());
    return res;
  } catch {
    const hit = await cache.match(key(req));
    if (hit) return hit;
    throw new Error('offline');
  }
}

async function staleWhileRevalidate(req, cacheName, e) {
  const cache = await caches.open(cacheName);
  const hit = await cache.match(key(req));
  const fresh = fetch(req).then(res => { if (res.ok) return cache.put(key(req), res.clone()).then(() => res); return res; });
  if (hit) { e.waitUntil(fresh.catch(() => {})); return hit; }
  return fresh;
}

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  const p = url.pathname;

  if (req.mode === 'navigate') {
    e.respondWith(fetch(req).then(res => {
      if (res.ok) { const copy = res.clone(); caches.open(SHELL).then(c => c.put('/', copy)); }
      return res;
    }).catch(async () => (await caches.match('/')) || Response.error()));
    return;
  }
  // Plugin bundles are versioned by the module (?v=<ui_version>), the SDK by the WebUI build.
  if (/^\/api\/webui\/plugins\/[^/]+\/bundle\//.test(p) || p.startsWith('/plugins/_sdk/')) {
    e.respondWith(staleWhileRevalidate(req, DATA, e));
    return;
  }
  if (p === '/api/webui/plugins/catalog' || p === '/api/webui/central-settings/items') {
    e.respondWith(networkFirst(req, DATA));
    return;
  }
  if (!p.startsWith('/api/') && /\.(js|css|woff2?|svg|png|ico|webmanifest)$/.test(p)) {
    e.respondWith(staleWhileRevalidate(req, SHELL, e));
  }
});
