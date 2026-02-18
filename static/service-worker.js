/* static/service-worker.js */
const CACHE_NAME = "gada-v7"; // bump on deploy

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

      // tell open pages offline is ready
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

  // ✅ don't touch non-GET (uploads, forms, login)
  if (req.method !== "GET") return;

  const url = new URL(req.url);

  // ✅ only same origin
  if (url.origin !== self.location.origin) return;

  // ✅ never intercept API calls
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/recorder/api/")) {
    return;
  }

  // ✅ navigation pages: network-first (prevents old layouts), fallback cache/offline
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

  // ✅ static assets: cache-first, then network, store in SAME cache
  const isStatic =
    url.pathname.startsWith("/static/") ||
    url.pathname === "/manifest.webmanifest" ||
    url.pathname.startsWith("/static/icons/");

  if (isStatic) {
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

  // ✅ everything else GET: cache-first, then network (your original “fast feel”)
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
});

self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "SKIP_WAITING") {
    self.skipWaiting();
  }
});
