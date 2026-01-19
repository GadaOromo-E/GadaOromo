/* static/sw.js - gada-v3
   - Offline fallback page
   - Better caching
   - Update handling (SKIP_WAITING)
   - Avoid caching admin pages
   - Don't touch POST requests
*/

const CACHE_VERSION = "gada-v3";
const STATIC_CACHE = `${CACHE_VERSION}-static`;
const PAGE_CACHE = `${CACHE_VERSION}-pages`;
const OFFLINE_URL = "/offline";

const CORE_ASSETS = [
  "/",
  "/translate",
  "/learn",
  "/support",
  OFFLINE_URL,

  "/static/style.css",
  "/static/pwa-ui.js",
  "/static/manifest.webmanifest",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png"
];

self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "SKIP_WAITING") {
    self.skipWaiting();
  }
});

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then((cache) => cache.addAll(CORE_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.map((k) => {
      if (!k.startsWith(CACHE_VERSION)) return caches.delete(k);
    }));
    await self.clients.claim();
  })());
});

async function cacheFirst(req) {
  const cached = await caches.match(req);
  if (cached) return cached;

  const res = await fetch(req);
  const cache = await caches.open(STATIC_CACHE);
  cache.put(req, res.clone());
  return res;
}

async function staleWhileRevalidate(req) {
  const cache = await caches.open(PAGE_CACHE);
  const cached = await cache.match(req);

  const fetchPromise = fetch(req).then((res) => {
    if (res && res.status === 200) cache.put(req, res.clone());
    return res;
  }).catch(() => null);

  return cached || (await fetchPromise) || (await caches.match(OFFLINE_URL));
}

async function networkFirst(req) {
  const cache = await caches.open(PAGE_CACHE);
  try {
    const res = await fetch(req);
    if (res && res.status === 200) cache.put(req, res.clone());
    return res;
  } catch (e) {
    const cached = await cache.match(req);
    return cached || (await caches.match(OFFLINE_URL));
  }
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);

  if (url.origin !== self.location.origin) return;
  if (req.method !== "GET") return;

  // never cache admin
  if (url.pathname.startsWith("/admin") || url.pathname.startsWith("/dashboard")) {
    event.respondWith(networkFirst(req));
    return;
  }

  if (url.pathname === OFFLINE_URL) {
    event.respondWith(cacheFirst(req));
    return;
  }

  if (url.pathname.startsWith("/static/")) {
    event.respondWith(cacheFirst(req));
    return;
  }

  // allow offline playback after first load
  if (url.pathname.startsWith("/uploads/")) {
    event.respondWith(cacheFirst(req));
    return;
  }

  // HTML navigation: fast + update
  if (req.mode === "navigate") {
    event.respondWith(staleWhileRevalidate(req));
    return;
  }

  event.respondWith(networkFirst(req));
});
