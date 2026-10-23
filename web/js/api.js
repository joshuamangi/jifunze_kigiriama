// Fetch wrapper: always sends the custom header the server requires on state-changing requests,
// turns network failures into OfflineError, and sends the user to Login on any 401.
const HEADER = { 'X-Requested-With': 'jifunze' };

export class ApiError extends Error {
  constructor(status, message, retryAfter = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.retryAfter = retryAfter;
  }
}

export class OfflineError extends Error {
  constructor(message) {
    super(message);
    this.name = 'OfflineError';
  }
}

let onUnauthorized = () => {};
export function setUnauthorizedHandler(fn) { onUnauthorized = fn; }

function describe(data, status) {
  const detail = data && data.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail) && detail.length) return 'Please check the form and try again.';
  return `Something went wrong (${status}).`;
}

// Cloudflare Access answers an expired session (24 h) with a redirect to its login page on another
// origin. fetch() follows it, the browser refuses it (no CORS headers) and the call throws, which
// looks exactly like being offline. So ask /healthz without following redirects: a redirect means the
// Access session expired, a throw means the network really is down.
async function accessSessionExpired() {
  try {
    const probe = await fetch('/healthz', { redirect: 'manual', cache: 'no-store' });
    return probe.type === 'opaqueredirect';
  } catch {
    return false;
  }
}

// Reload once so the browser (through the service worker, which asks the network first for pages)
// reaches the Cloudflare login. A second failure within 15 s does not reload again, so it cannot loop.
function reloadToSignIn() {
  const KEY = 'jifunze-access-reload';
  try {
    if (Date.now() - Number(sessionStorage.getItem(KEY) || 0) < 15000) return;
    sessionStorage.setItem(KEY, String(Date.now()));
  } catch {
    return; // storage blocked: do not risk a reload loop; the message says to reload by hand
  }
  location.reload();
}

export async function api(method, path, body) {
  let response;
  try {
    response = await fetch(path, {
      method,
      credentials: 'same-origin',
      headers: body === undefined ? HEADER : { ...HEADER, 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    if (await accessSessionExpired()) {
      reloadToSignIn();
      throw new ApiError(401, 'Your Cloudflare sign-in has expired. Reload this page to sign in again.');
    }
    throw new OfflineError("You're offline, or the server can't be reached.");
  }
  if (response.status === 401 && path !== '/api/login' && path !== '/api/access-login') {
    onUnauthorized();
    throw new ApiError(401, 'Please sign in again.');
  }
  if (response.status === 204) return null;
  let data = null;
  try { data = await response.json(); } catch { /* no body */ }
  if (!response.ok) {
    throw new ApiError(response.status, describe(data, response.status), response.headers.get('Retry-After'));
  }
  return data;
}

export const get = (path) => api('GET', path);
export const post = (path, body = {}) => api('POST', path, body);
export const patch = (path, body) => api('PATCH', path, body);
export const put = (path, body) => api('PUT', path, body);

export function query(params) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') q.set(k, String(v));
  }
  const text = q.toString();
  return text ? `?${text}` : '';
}
