// Behaviour of web/js/api.js and web/sw.js under the network conditions a phone really meets, run by
// tests/test_web_behaviour.py. Plain Node, no dependencies: prints "ok ..." / "FAIL ..." per case.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import vm from 'node:vm';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const failures = [];
async function test(name, fn) {
  try {
    await fn();
    console.log(`ok   ${name}`);
  } catch (error) {
    failures.push(name);
    console.log(`FAIL ${name}\n     ${error && error.message}`);
  }
}

// ---- api.js ------------------------------------------------------------------------------------
const { api, ApiError, OfflineError } = await import(pathToFileURL(path.join(root, 'web/js/api.js')).href);

function phone({ fetchImpl }) {
  const store = new Map();
  const state = { reloads: 0 };
  globalThis.sessionStorage = {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
  };
  globalThis.location = { reload: () => { state.reloads += 1; } };
  globalThis.fetch = fetchImpl;
  return state;
}

const accessRedirect = async (url, options) => {
  // Cloudflare Access: every request is redirected to its login page on another origin. Following
  // that redirect is a CORS failure (a thrown TypeError); asking not to follow gives an opaque redirect.
  if (options && options.redirect === 'manual') return { type: 'opaqueredirect', status: 0, ok: false };
  throw new TypeError('Failed to fetch');
};

await test('an expired Cloudflare Access session is reported as that, not as being offline', async () => {
  const state = phone({ fetchImpl: accessRedirect });
  await assert.rejects(api('GET', '/api/me'), (e) => {
    assert.ok(e instanceof ApiError, `got ${e.name}`);
    assert.match(e.message, /sign-in has expired/i);
    return true;
  });
  assert.equal(state.reloads, 1, 'reloads once so the browser reaches the Cloudflare login');
});

await test('it does not reload in a loop', async () => {
  const state = phone({ fetchImpl: accessRedirect });
  await assert.rejects(api('GET', '/api/me'), ApiError);
  await assert.rejects(api('GET', '/api/me'), ApiError);
  assert.equal(state.reloads, 1);
});

await test('really being offline is still reported as offline, without reloading', async () => {
  const state = phone({ fetchImpl: async () => { throw new TypeError('Failed to fetch'); } });
  await assert.rejects(api('GET', '/api/me'), OfflineError);
  assert.equal(state.reloads, 0);
});

await test('a normal response is untouched', async () => {
  phone({ fetchImpl: async () => ({ ok: true, status: 200, type: 'basic', json: async () => ({ id: 1 }) }) });
  assert.deepEqual(await api('GET', '/api/me'), { id: 1 });
});

// ---- sw.js -------------------------------------------------------------------------------------
function serviceWorker({ fetchImpl, cached = {} }) {
  const listeners = {};
  const puts = [];
  const cache = {
    addAll: async () => {},
    match: async (request) => {
      const key = typeof request === 'string' ? request : new URL(request.url).pathname;
      return cached[key];
    },
    put: async (request) => { puts.push(request.url); },
  };
  const context = {
    self: {
      addEventListener: (type, fn) => { listeners[type] = fn; },
      location: { origin: 'https://app.test' },
      skipWaiting: () => {},
      clients: { claim: () => {} },
    },
    caches: { open: async () => cache, keys: async () => [], delete: async () => true },
    fetch: fetchImpl,
    Response: class { static error() { return { type: 'error' }; } },
    URL, Promise, setTimeout, clearTimeout,
  };
  vm.runInNewContext(readFileSync(path.join(root, 'web/sw.js'), 'utf8'), context);
  return {
    puts,
    async handle(request) {
      let answer;
      const event = { request, respondWith: (p) => { answer = p; } };
      listeners.fetch(event);
      return answer === undefined ? undefined : await answer;
    },
  };
}
const page = { method: 'GET', url: 'https://app.test/', mode: 'navigate' };

await test('a page load reaches the Cloudflare login when the Access session has expired', async () => {
  const redirect = { type: 'opaqueredirect', status: 0, ok: false };
  const sw = serviceWorker({ fetchImpl: async () => redirect, cached: { '/': { cachedShell: true } } });
  assert.equal(await sw.handle(page), redirect, 'the redirect must not be hidden behind the cached shell');
});

await test('a page load falls back to the cached shell when the network is down', async () => {
  const shell = { cachedShell: true };
  const sw = serviceWorker({ fetchImpl: async () => { throw new TypeError('Failed to fetch'); }, cached: { '/': shell } });
  assert.equal(await sw.handle(page), shell);
});

await test('a good page load is returned and cached', async () => {
  const fresh = { ok: true, type: 'basic', clone() { return this; } };
  const sw = serviceWorker({ fetchImpl: async () => fresh, cached: { '/': { cachedShell: true } } });
  assert.equal(await sw.handle(page), fresh);
  assert.equal(sw.puts.length, 1);
});

await test('API calls never go through the service worker', async () => {
  const sw = serviceWorker({ fetchImpl: async () => { throw new Error('should not be called'); } });
  assert.equal(await sw.handle({ method: 'GET', url: 'https://app.test/api/me', mode: 'cors' }), undefined);
});

await test('static files still come from the cache first', async () => {
  const css = { cachedCss: true };
  const sw = serviceWorker({ fetchImpl: async () => { throw new TypeError('offline'); }, cached: { '/css/app.css': css } });
  assert.equal(await sw.handle({ method: 'GET', url: 'https://app.test/css/app.css', mode: 'no-cors' }), css);
});

if (failures.length) {
  console.log(`\n${failures.length} failed`);
  process.exit(1);
}
