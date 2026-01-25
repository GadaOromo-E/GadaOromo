/* static/service-worker.js */
const CACHE_NAME = "gada-v5";

/**
 * Core pages + assets to cache.
 * Keep this list small to avoid caching DB-driven pages too aggressively.
 * NOTE: We intentionally DO NOT pre-cache audio.js / recorder.js,
 * so recording/upload fixes are always up-to-date.
 */
const CORE_ASSETS = [
  "/",                 // Home
  "/translate",
  "/learn",
  "/support",
  "/offline",

  // CSS / base JS (safe)
  "/static/style.css",
  "/static/pwa-ui.js",

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
 * Helpers
 */
async function networkFirst(req) {
  try {
    const res = await fetch(req);
    const copy = res.clone();
    caches.open(CACHE_NAME).then((cache) => cache.put(req, copy));
    return res;
  } catch (e) {
    const cached = await caches.match(req);
    return cached || caches.match("/offline");
  }
}

async function cacheFirst(req) {
  const cached = await caches.match(req);
  if (cached) return cached;

  const res = await fetch(req);
  const copy = res.clone();
  caches.open(CACHE_NAME).then((cache) => cache.put(req, copy));
  return res;
}

/**
 * Fetch strategy:
 * - HTML navigation: network-first, fallback to cache, then offline page
 * - JS files: network-first (prevents stale audio/recorder scripts)
 * - Other static files (css/icons/manifest): cache-first
 * - Other: network-first fallback to cache
 */
self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);

  // Only same-origin
  if (url.origin !== self.location.origin) return;

  // HTML pages (navigate)
  if (req.mode === "navigate") {
    event.respondWith(networkFirst(req));
    return;
  }

  // Always get fresh JS (prevents "record/submit not updated" issues)
  if (url.pathname.startsWith("/static/") && url.pathname.endsWith(".js")) {
    event.respondWith(networkFirst(req));
    return;
  }

  // Manifest
  if (url.pathname === "/manifest.webmanifest") {
    event.respondWith(cacheFirst(req));
    return;
  }

  // Other static assets (cache-first)
  if (url.pathname.startsWith("/static/")) {
    event.respondWith(cacheFirst(req));
    return;
  }

  // Default: network-first, fallback to cache
  event.respondWith(fetch(req).catch(() => caches.match(req)));
});

/* Allow page to trigger update immediately */
self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "SKIP_WAITING") {
    self.skipWaiting();
  }
});



