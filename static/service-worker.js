/* static/service-worker.js */
const CACHE_NAME = "gada-v6";

const CORE_ASSETS = [
  "/",
  "/translate",
  "/learn",
  "/support",
  "/offline",

  "/static/style.css",
  "/static/pwa-ui.js",
  "/static/audio.js",
  "/static/recorder.js",

  "/manifest.webmanifest",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
  "/static/icons/apple-touch-icon.png",
  "/static/icons/favicon-32x32.png",
  "/static/icons/favicon-16x16.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(async (cache) => {
      await cache.addAll(CORE_ASSETS);

      // Notify pages that offline cache is ready
      const clients = await self.clients.matchAll({ type: "window" });
      clients.forEach((c) => c.postMessage({ type: "OFFLINE_READY" }));
    })
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.map((k) => (k !== CACHE_NAME ? caches.delete(k) : null)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const req = event.request;

  // ✅ CRITICAL: never intercept POST/PUT/DELETE (fixes upload stuck)
  if (req.method !== "GET") return;

  const url = new URL(req.url);

  // Only same-origin
  if (url.origin !== self.location.origin) return;

  // ✅ Never cache / intercept any API routes (public + recorder)
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/recorder/api/")) {
    return;
  }

  // HTML navigation: network-first
  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(req, copy));
          return res;
        })
        .catch(async () => {
          const cached = await caches.match(req);
          return cached || caches.match("/offline");
        })
    );
    return;
  }

  // Static assets: cache-first
  if (url.pathname.startsWith("/static/") || url.pathname === "/manifest.webmanifest") {
    event.respondWith(
      caches.match(req).then((cached) => {
        if (cached) return cached;
        return fetch(req).then((res) => {
          const copy = res.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(req, copy));
          return res;
        });
      })
    );
    return;
  }

  // Default: network-first fallback cache
  event.respondWith(fetch(req).catch(() => caches.match(req)));
});

self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "SKIP_WAITING") {
    self.skipWaiting();
  }
});


