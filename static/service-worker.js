/* Gadaa PWA service worker — cache version is injected at /service-worker.js serve time. */
const CACHE_VERSION = "__GADAA_CACHE_VERSION__";
const STATIC_CACHE = `${CACHE_VERSION}-static`;
const PAGE_CACHE = `${CACHE_VERSION}-pages`;
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
  OFFLINE_URL,
];

function isCurrentCacheName(name) {
  return name === STATIC_CACHE || name === PAGE_CACHE;
}

async function purgeLegacyCaches() {
  const keys = await caches.keys();
  await Promise.all(
    keys.map((key) => (isCurrentCacheName(key) ? null : caches.delete(key)))
  );
}

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    await purgeLegacyCaches();
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
    await purgeLegacyCaches();
    await self.clients.claim();
    const clients = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    clients.forEach((client) => {
      try {
        client.postMessage({ type: "SW_ACTIVATED", version: CACHE_VERSION });
      } catch (_) {}
    });
  })());
});

async function navigationNetworkFirst(req) {
  const pageCache = await caches.open(PAGE_CACHE);

  try {
    const res = await fetch(req, { cache: "no-store" });
    if (res && res.status === 200) {
      await pageCache.put(req, res.clone());
    }
    return res;
  } catch (err) {
    const cached = await pageCache.match(req);
    if (cached) return cached;
    const offline = await caches.match(OFFLINE_URL);
    return offline || Response.error();
  }
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);

  if (req.method !== "GET") return;
  if (url.origin !== self.location.origin) return;

  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/recorder/api/")) {
    return;
  }

  if (req.mode === "navigate") {
    event.respondWith(navigationNetworkFirst(req));
    return;
  }

  if (url.pathname.startsWith("/static/") || url.pathname === "/manifest.webmanifest") {
    event.respondWith((async () => {
      const cache = await caches.open(STATIC_CACHE);
      const cached = await cache.match(req);
      const networkPromise = fetch(req, { cache: "no-cache" })
        .then((res) => {
          if (res && res.status === 200) {
            cache.put(req, res.clone());
          }
          return res;
        })
        .catch(() => null);

      return cached || (await networkPromise) || Response.error();
    })());
    return;
  }

  event.respondWith(
    fetch(req, { cache: "no-store" }).catch(() => caches.match(req))
  );
});

self.addEventListener("message", (event) => {
  if (!event || !event.data) return;
  if (event.data.type === "SKIP_WAITING") {
    self.skipWaiting();
    return;
  }
  if (event.data.type === "GET_VERSION") {
    try {
      if (event.ports && event.ports[0]) {
        event.ports[0].postMessage({
          type: "SW_VERSION",
          version: CACHE_VERSION,
          build: CACHE_VERSION.replace(/^gada-/, ""),
        });
      }
    } catch (_) {}
    return;
  }
  if (event.data.type === "CLEAR_PAGE_CACHE") {
    event.waitUntil(caches.delete(PAGE_CACHE));
  }
});
