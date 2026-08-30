const shellCache = "shadow-travel-shell-v1";

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(shellCache).then((cache) => cache.addAll(["./", "./manifest.webmanifest"])));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((key) => key !== shellCache).map((key) => caches.delete(key))))
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin || url.pathname.includes("/api/") || url.pathname.includes("/auth/")) return;
  event.respondWith(
    fetch(request).then((response) => {
      const copy = response.clone();
      void caches.open(shellCache).then((cache) => cache.put(request, copy));
      return response;
    }).catch(() => caches.match(request).then((response) => response ?? caches.match("./")))
  );
});
