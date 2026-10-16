// Service worker: keeps the app shell available offline.
// It never touches the API: /api responses are not cached, so data is always live or an error.
const CACHE = 'jifunze-shell-v3';
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
  '/js/screens/status.js',
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
  event.respondWith(request.mode === 'navigate' ? networkFirstPage(request) : staleWhileRevalidate(request));
});

const PAGE_TIMEOUT_MS = 4000;

function withTimeout(promise, ms) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('timeout')), ms);
    promise.then(
      (value) => { clearTimeout(timer); resolve(value); },
      (error) => { clearTimeout(timer); reject(error); },
    );
  });
}

// Pages: ask the network first. If Cloudflare Access wants a new sign-in (the session lasts 24 hours) the
// answer is a redirect to its login page, and that must reach the browser instead of being hidden
// behind the cached shell. The cache is only the fallback when the network is down or slow.
async function networkFirstPage(request) {
  const cache = await caches.open(CACHE);
  try {
    const response = await withTimeout(fetch(request), PAGE_TIMEOUT_MS);
    if (response.ok && response.type === 'basic') cache.put(request, response.clone());
    return response;
  } catch {
    return (await cache.match(request, { ignoreSearch: true })) || (await cache.match('/')) || Response.error();
  }
}

// Static files: the cached copy at once, refreshed in the background.
async function staleWhileRevalidate(request) {
  const cache = await caches.open(CACHE);
  const cached = await cache.match(request);
  const network = fetch(request)
    .then((response) => {
      if (response.ok && response.type === 'basic') cache.put(request, response.clone());
      return response;
    })
    .catch(() => null);
  if (cached) return cached;
  return (await network) || Response.error();
}
