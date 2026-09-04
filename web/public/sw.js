// Replaced with the build's hashed assets by Vite. No private API or map tiles.
const precache = self.__TRAVEL_PRECACHE__ || ["./", "./manifest.webmanifest"];
const prefix = `shadow-travel-shell:${self.registration.scope}:`;
const shellCache = prefix + (self.__TRAVEL_BUILD__ || "dev");

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(shellCache).then((cache) => cache.addAll(precache)));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((key) => key.startsWith(prefix) && key !== shellCache).map((key) => caches.delete(key))))
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (!url.href.startsWith(self.registration.scope) || url.pathname.includes("/api/") || url.pathname.includes("/auth/")) return;
  const allowed = precache.some(path => new URL(path, self.registration.scope).href === url.href);
  if (request.mode !== "navigate" && !allowed) return;
  if (allowed && request.mode !== "navigate") {
    // The allowlist contains only immutable build assets. Vary: Origin can differ
    // between addAll's fetch and a crossorigin module script request.
    event.respondWith(caches.open(shellCache).then(async cache => (await cache.match(url.href, { ignoreVary: true })) || fetch(request)));
    return;
  }
  event.respondWith(
    fetch(request).catch(async () => {
      const cache = await caches.open(shellCache);
      return (await cache.match(request, { ignoreVary: true })) || (request.mode === "navigate" ? await cache.match(new URL("./", self.registration.scope), { ignoreVary: true }) : undefined) || Response.error();
    })
  );
});
