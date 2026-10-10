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
    throw new OfflineError("You're offline, or the server can't be reached.");
  }
  if (response.status === 401 && path !== '/api/login') {
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
