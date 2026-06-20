/* Legacy /static/sw.js shim for old Android PWAs (gada-v3).
   Purges stale caches and hands control back to the page so /service-worker.js can register. */
self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.map((key) => caches.delete(key)));
    const clients = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    clients.forEach((client) => {
      try {
        client.postMessage({ type: "SW_LEGACY_PURGED" });
      } catch (_) {}
    });
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", () => {});
