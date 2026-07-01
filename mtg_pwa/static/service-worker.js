const CACHE_NAME = "mtg-price-tracker-v60";
const STATIC_ASSETS = [
  "/",
  "/styles.css?v=detail-printing-click-v1",
  "/app.js?v=detail-printing-click-v1",
  "/manifest.json",
  "/icon.svg",
  "/splash/splash-1.png",
  "/splash/splash-2.png",
  "/splash/splash-3.png",
];

self.addEventListener("install", (event) => {
  self.skipWaiting();
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS)));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)))),
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (
    url.pathname.startsWith("/api/") ||
    url.pathname.startsWith("/cache/set-icons/") ||
    url.pathname.startsWith("/cache/images/")
  ) {
    return;
  }

  if (event.request.mode === "navigate" || url.pathname.endsWith(".js") || url.pathname.endsWith(".css")) {
    event.respondWith(fetch(event.request).catch(() => caches.match(event.request)));
    return;
  }

  event.respondWith(
    caches.match(event.request).then((cached) => {
      if (cached) {
        return cached;
      }
      return fetch(event.request);
    }),
  );
});
