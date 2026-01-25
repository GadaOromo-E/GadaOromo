/* static/service-worker.js */
const CACHE_NAME = "gada-v5"; // bump version so SW updates

/**
 * Core pages + assets to cache.
 * Keep this list small to avoid caching DB-driven pages too aggressively.
 */
const CORE_ASSETS = [
  "/",                 // Home
  "/translate",
  "/learn",
  "/support",
  "/offline",

  // CSS / JS
  "/static/style.css",
  "/static/pwa-ui.js",

  // ✅ Use the correct recorder script here
  // If you still need audio.js on other pages, keep it too.
  "/static/recorder.js",
  // "/static/audio.js",

  // Manifest + icons
  "/manifest.webmanifest",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
  "/static/icons/apple-touch-icon.png",
  "/static/icons/favicon-32x32.png",
  "/static/icons/favicon-16x16.png",
];

/* Install: cache core assets */
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(async (cache) => {
      await cache.addAll(CORE_ASSETS);
      // notify clients that offline is ready
      const clients = await self.clients.matchAll({ type: "window" });
      clients.forEach((c) => c.postMessage({ type: "OFFLINE_READY" }));
    })
  );
  self.skipWaiting();
});

/* Activate: clean old caches */
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.map((k) => (k !== CACHE_NAME ? caches.delete(k) : null)))
    )
  );
  self.clients.claim();
});

/**
 * Fetch strategy:
 * - ✅ Never cache non-GET (POST/PUT/DELETE) -> fixes your error
 * - ✅ Never cache /recorder/api/* (always network)
 * - HTML navigation: network-first, fallback to cache, then offline page
 * - Static files: cache-first
 * - Other: network-first fallback to cache
 */
self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);

  // Only same-origin
  if (url.origin !== self.location.origin) return;

  // ✅ 1) IMPORTANT: do not touch POST/PUT/DELETE (uploads, forms, APIs)
  if (req.method !== "GET") {
    event.respondWith(fetch(req));
    return;
  }

  // ✅ 2) IMPORTANT: do not cache your recorder API calls
  if (url.pathname.startsWith("/recorder/api/")) {
    event.respondWith(fetch(req, { cache: "no-store" }));
    return;
  }

  // HTML pages (navigate)
  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req)
        .then((res) => {
          // ✅ Only cache successful GET HTML responses
          if (res && res.ok) {
            const copy = res.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(req, copy));
          }
          return res;
        })
        .catch(async () => {
          const cached = await caches.match(req);
          return cached || caches.match("/offline");
        })
    );
    return;
  }

  // Static assets (cache-first)
  if (url.pathname.startsWith("/static/") || url.pathname === "/manifest.webmanifest") {
    event.respondWith(
      caches.match(req).then((cached) => {
        if (cached) return cached;
        return fetch(req).then((res) => {
          // ✅ Only cache ok responses
          if (res && res.ok) {
            const copy = res.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(req, copy));
          }
          return res;
        });
      })
    );
    return;
  }

  // Default: network-first
  event.respondWith(fetch(req).catch(() => caches.match(req)));
});

/* Allow page to trigger update immediately */
self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "SKIP_WAITING") {
    self.skipWaiting();
  }
});


