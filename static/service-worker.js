const CACHE_VERSION = "gada-v8";
const STATIC_CACHE = `${CACHE_VERSION}-static`;
const PAGE_CACHE = `${CACHE_VERSION}-pages`;
const OFFLINE_URL = "/offline";
const NAV_TIMEOUT_MS = 1800;

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
  event.waitUntil((async () => {
    const cache = await caches.open(STATIC_CACHE);

    for (const assetPath of STATIC_ASSETS) {
      try {
        const req = new Request(assetPath, { cache: "no-cache" });
        const res = await fetch(req);
        if (res && res.ok) {
          await cache.put(req, res.clone());
        } else {
          console.warn("[SW install] Skipped asset (non-OK):", assetPath, res && res.status);
        }
      } catch (err) {
        console.warn("[SW install] Skipped asset (fetch failed):", assetPath, err);
      }
    }
  })());
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(
      keys.map((k) => (k !== STATIC_CACHE && k !== PAGE_CACHE ? caches.delete(k) : null))
    );
    await self.clients.claim();
  })());
});

async function navigationNetworkFirstWithTimeout(req) {
  const pageCache = await caches.open(PAGE_CACHE);
  const cached = await pageCache.match(req);

  // Start network request immediately; keep cache fresh whenever network succeeds.
  const networkPromise = fetch(req)
    .then((res) => {
      if (res && res.status === 200) {
        pageCache.put(req, res.clone());
      }
      return res;
    })
    .catch(() => null);

  const timeoutPromise = new Promise((resolve) => {
    setTimeout(() => resolve(null), NAV_TIMEOUT_MS);
  });

  const first = await Promise.race([networkPromise, timeoutPromise]);
  if (first) return first;
  if (cached) return cached;

  const lateNetwork = await networkPromise;
  if (lateNetwork) return lateNetwork;

  return (await caches.match(OFFLINE_URL)) || Response.error();
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);

  if (req.method !== "GET") return;
  if (url.origin !== self.location.origin) return;

  // Never cache API responses.
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/recorder/api/")) {
    return;
  }

  // Navigation: network-first with short timeout fallback to cache.
  // Keeps HTML fresh when network is healthy, but avoids long navigation stalls.
  if (req.mode === "navigate") {
    event.respondWith(navigationNetworkFirstWithTimeout(req));
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
