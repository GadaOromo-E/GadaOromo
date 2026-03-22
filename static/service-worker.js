const CACHE_VERSION = "gada-v7";
const STATIC_CACHE = `${CACHE_VERSION}-static`;
const OFFLINE_URL = "/offline";

const STATIC_ASSETS = [
  "/manifest.webmanifest",
  "/static/style.css",
  "/static/pwa-ui.js",
  "/static/audio.js",
  "/static/speak.js",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
  "/static/icons/apple-touch-icon.png",
  "/static/icons/favicon-32x32.png",
  "/static/icons/favicon-16x16.png",
  OFFLINE_URL
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then((cache) => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.map((k) => (k !== STATIC_CACHE ? caches.delete(k) : null)));
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);

  if (req.method !== "GET") return;
  if (url.origin !== self.location.origin) return;

  // Never cache API responses.
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/recorder/api/")) {
    return;
  }

  // Navigation: network-first to avoid stale HTML/SEO markup.
  if (req.mode === "navigate") {
    event.respondWith((async () => {
      try {
        return await fetch(req, { cache: "no-store" });
      } catch (_e) {
        return (await caches.match(OFFLINE_URL)) || Response.error();
      }
    })());
    return;
  }

  // Static files: cache-first with background refresh.
  if (url.pathname.startsWith("/static/") || url.pathname === "/manifest.webmanifest") {
    event.respondWith((async () => {
      const cache = await caches.open(STATIC_CACHE);
      const cached = await cache.match(req);
      const networkPromise = fetch(req).then((res) => {
        if (res && res.status === 200) {
          cache.put(req, res.clone());
        }
        return res;
      }).catch(() => null);

      return cached || (await networkPromise) || Response.error();
    })());
    return;
  }

  // Everything else: network-first, no long-lived page cache.
  event.respondWith(fetch(req).catch(() => caches.match(req)));
});

self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "SKIP_WAITING") {
    self.skipWaiting();
  }
});
