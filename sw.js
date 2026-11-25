const CACHE_NAME = 'broute-shell-2-0-beta-2';
const SHELL = ['/', '/manifest.json', '/icon.svg', '/broute-config.js'];
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', event => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== self.location.origin || url.pathname.startsWith('/api/')) return;
  if (url.pathname === '/broute-config.js') {
    event.respondWith(fetch(req).then(res => { caches.open(CACHE_NAME).then(cache => cache.put(req, res.clone())); return res; }).catch(() => caches.match(req)));
    return;
  }
  if (req.mode === 'navigate') {
    event.respondWith(fetch(req).then(res => {
      const copy = res.clone(); caches.open(CACHE_NAME).then(cache => cache.put('/', copy)); return res;
    }).catch(() => caches.match('/')));
    return;
  }
  event.respondWith(caches.match(req).then(cached => cached || fetch(req).then(res => {
    if (res.ok) caches.open(CACHE_NAME).then(cache => cache.put(req, res.clone())); return res;
  })));
});
