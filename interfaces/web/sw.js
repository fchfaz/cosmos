// Service worker minimal: cache cangkang halaman agar PWA bisa dibuka cepat. API tidak pernah di-cache.
const CACHE = 'jarvis-shell-v1';
self.addEventListener('install', e => e.waitUntil(caches.open(CACHE).then(c => c.addAll(['/']))));
self.addEventListener('activate', e => e.waitUntil(
  caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))));
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.pathname !== '/') return;
  e.respondWith(fetch(e.request).catch(() => caches.match('/')));
});
