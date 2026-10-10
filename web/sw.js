// Service worker: keeps the app shell available offline.
// It never touches the API: /api responses are not cached, so data is always live or an error.
const CACHE = 'jifunze-shell-v1';
const SHELL = [
  '/',
  '/css/theme.css',
  '/css/fonts.css',
  '/css/app.css',
  '/fonts/kodchasan-latin-400.woff2',
  '/fonts/kodchasan-latin-500.woff2',
  '/fonts/kodchasan-latin-600.woff2',
  '/fonts/kodchasan-latin-700.woff2',
  '/js/app.js',
  '/js/api.js',
  '/js/icons.js',
  '/js/labels.js',
  '/js/theme.js',
  '/js/ui.js',
  '/js/screens/login.js',
  '/js/screens/home.js',
  '/js/screens/add.js',
  '/js/screens/learn.js',
  '/js/screens/study.js',
  '/js/screens/culture.js',
  '/js/screens/settings.js',
  '/js/screens/review.js',
  '/manifest.webmanifest',
  '/icons/icon.svg',
  '/icons/icon-192.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()),
  );
});

function isApi(url) {
  return url.pathname.startsWith('/api/') || url.pathname === '/healthz';
}

self.addEventListener('fetch', (event) => {
  const request = event.request;
  const url = new URL(request.url);
  // Only same-origin GETs for the shell; everything else (all /api traffic, POSTs) goes straight to the network.
  if (request.method !== 'GET' || url.origin !== self.location.origin || isApi(url)) return;
  event.respondWith(staleWhileRevalidate(request));
});

async function staleWhileRevalidate(request) {
  const cache = await caches.open(CACHE);
  const cached = await cache.match(request, { ignoreSearch: request.mode === 'navigate' });
  const network = fetch(request)
    .then((response) => {
      if (response.ok && response.type === 'basic') cache.put(request, response.clone());
      return response;
    })
    .catch(() => null);
  if (cached) return cached;
  const response = await network;
  if (response) return response;
  if (request.mode === 'navigate') return (await cache.match('/')) || Response.error();
  return Response.error();
}
