// Service worker for the Trip Fuel Calculator. Lets the page open offline.
// Change CACHE_NAME in a release to replace the cached shell.
// All paths are relative to this file, because the site lives under a sub-path.
const CACHE_NAME = "fc-v1";
const NETWORK_TIMEOUT_MS = 3000;

const SHELL = ["./", "./fuel-calculator.html", "./prices.js", "./manifest.webmanifest",
  "./icons/icon-180.png", "./icons/icon-192.png", "./icons/icon-512.png", "./icons/icon-maskable-512.png"];
const LEAFLET = [
  "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js",
  "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css"
];
const FONT_CSS = ["https://fonts.googleapis.com/css2?family=Geist:wght@300..600&display=swap"];   // font files are cached when first used

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE_NAME);
    // The shell must be there. A failure on the optional CDN files must not fail the install.
    await cache.addAll(SHELL.map((u) => new Request(u, { cache: "reload" })));
    await Promise.all(LEAFLET.concat(FONT_CSS).map(async (u) => {
      try {
        const res = await fetch(new Request(u, { mode: "cors" }));
        if (res.ok) await cache.put(u, res);
      } catch (e) { /* optional */ }
    }));
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    // Cache storage is shared by every project on this origin, so only touch our own (fc-) caches.
    for (const name of await caches.keys()) if (name.startsWith("fc-") && name !== CACHE_NAME) await caches.delete(name);
    await self.clients.claim();
  })());
});

function timeout(ms) { return new Promise((_, rej) => setTimeout(() => rej(new Error("timeout")), ms)); }

// config.js holds a key and is never cached. It is parser-blocking, so a slow network must not stall the page:
// give up after the timeout and answer with an empty script (the page works without it).
async function configJs(request) {
  try {
    return await Promise.race([fetch(request), timeout(NETWORK_TIMEOUT_MS)]);
  } catch (e) {
    return new Response("", { status: 200, headers: { "Content-Type": "text/javascript" } });
  }
}

// Network first, then the cache. A server error also falls back to the cache, and only ok responses are stored.
// The no-cache option makes the fetch revalidate, so the browser's own HTTP cache can't serve old files.
async function networkFirst(request, cacheKey, matchOptions) {
  const cache = await caches.open(CACHE_NAME);
  try {
    const res = await Promise.race([fetch(new Request(request, { cache: "no-cache" })), timeout(NETWORK_TIMEOUT_MS)]);
    if (res && res.ok) {
      cache.put(cacheKey, res.clone());
      return res;
    }
    const hit = await cache.match(cacheKey, matchOptions);
    return hit || res;
  } catch (e) {
    const hit = await cache.match(cacheKey, matchOptions);
    if (hit) return hit;
    throw e;
  }
}

async function cacheFirst(request) {
  const cache = await caches.open(CACHE_NAME);
  const hit = await cache.match(request);
  if (hit) return hit;
  const res = await fetch(request);
  if (res && (res.ok || res.type === "opaque")) cache.put(request, res.clone());
  return res;
}

async function staleWhileRevalidate(request) {
  const cache = await caches.open(CACHE_NAME);
  const hit = await cache.match(request);
  const refresh = fetch(request).then((res) => {
    if (res && (res.ok || res.type === "opaque")) cache.put(request, res.clone());
    return res;
  });
  if (hit) { refresh.catch(() => {}); return hit; }
  return refresh;
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);

  if (url.origin === self.location.origin) {
    const scope = new URL("./", self.location).pathname;
    const name = url.pathname.slice(scope.length);
    if (name === "config.js") {
      // Before the navigate branch, so a direct visit to /config.js is never cached either.
      event.respondWith(configJs(req));
    } else if (name === "prices.js") {
      // One cache entry, whatever the ?t= value is.
      const key = new URL("prices.js", self.location).href;
      event.respondWith(networkFirst(req, key, { ignoreSearch: true }));
    } else if (req.mode === "navigate" || name === "" || name === "fuel-calculator.html" || name === "index.html") {
      // Keyed by address without the query, so ?x=1 never adds entries. Offline, any page falls back to the app.
      const key = new URL(url.pathname, url.origin).href;
      event.respondWith(networkFirst(req, key, { ignoreSearch: true }).catch(
        () => caches.match(new URL("fuel-calculator.html", self.location).href)));
    } else if (name === "manifest.webmanifest" || name.startsWith("icons/")) {
      event.respondWith(cacheFirst(req));
    }
    return;   // anything else on this site: not intercepted
  }
  if (url.hostname === "cdnjs.cloudflare.com" && /\/leaflet\/1\.9\.4\//.test(url.pathname)) {
    event.respondWith(cacheFirst(req));
  } else if (url.hostname === "fonts.googleapis.com" || url.hostname === "fonts.gstatic.com") {
    event.respondWith(staleWhileRevalidate(req));
  }
});
