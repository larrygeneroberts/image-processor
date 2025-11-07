// Lightweight service worker for offline and caching behavior.
// This is intentionally conservative: precaches app shell, uses
// network-first for navigations and cache-first for thumbnails.

const APP_CACHE = 'app-shell-v1';
const IMAGE_CACHE = 'thumbnails-v1';
const OFFLINE_PAGE = '/offline';

const PRECACHE_URLS = [
  '/',
  '/static/css/improved-design.css',
  '/static/js/app.js',
  '/offline'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(APP_CACHE).then(cache => cache.addAll(PRECACHE_URLS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  // Clean up old caches if you change cache names in the future
  event.waitUntil(
    caches.keys().then(keys => Promise.all(
      keys.filter(k => k !== APP_CACHE && k !== IMAGE_CACHE).map(k => caches.delete(k))
    ))
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  const req = event.request;
  const url = new URL(req.url);

  // Navigation requests: network-first, fallback to cache, then offline page
  if (req.mode === 'navigate') {
    event.respondWith(
      fetch(req)
        .then(res => {
          const copy = res.clone();
          caches.open(APP_CACHE).then(cache => cache.put(req, copy));
          return res;
        })
        .catch(() => caches.match(req).then(r => r || caches.match(OFFLINE_PAGE)))
    );
    return;
  }

  // Thumbnails: cache-first
  if (url.pathname.startsWith('/photo/') && url.pathname.includes('/thumbnail')) {
    event.respondWith(
      caches.open(IMAGE_CACHE).then(async cache => {
        const cached = await cache.match(req);
        if (cached) return cached;
        try {
          const resp = await fetch(req);
          cache.put(req, resp.clone());
          return resp;
        } catch (err) {
          // return a transparent 1x1 GIF or placeholder if available
          return caches.match('/static/images/placeholder.png');
        }
      })
    );
    return;
  }

  // Default: stale-while-revalidate for other assets
  event.respondWith(
    caches.match(req).then(cachedResp => {
      const networkFetch = fetch(req).then(networkResp => {
        caches.open(APP_CACHE).then(cache => cache.put(req, networkResp.clone()));
        return networkResp;
      }).catch(() => null);
      return cachedResp || networkFetch;
    })
  );
});
