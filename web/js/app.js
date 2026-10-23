// Boot, hash router and the shell (bottom navigation). Each screen is a module that exports
// a default async function returning its root element.
import { get, OfflineError, post, setUnauthorizedHandler } from './api.js';
import { icon } from './icons.js';
import { initTheme } from './theme.js';
import { errorBanner, h, loading } from './ui.js';

const SCREENS = {
  '/login': () => import('./screens/login.js'),
  '/welcome': () => import('./screens/welcome.js'),
  '/home': () => import('./screens/home.js'),
  '/add': () => import('./screens/add.js'),
  '/learn': () => import('./screens/learn.js'),
  '/study': () => import('./screens/study.js'),
  '/culture': () => import('./screens/culture.js'),
  '/settings': () => import('./screens/settings.js'),
  '/review': () => import('./screens/review.js'),
  '/status': () => import('./screens/status.js'),
  '/people': () => import('./screens/people.js'),
};

const NAV = [
  ['/home', 'Home', 'home'],
  ['/add', 'Add', 'add'],
  ['/learn', 'Learn', 'learn'],
  ['/culture', 'Culture', 'culture'],
  ['/settings', 'Settings', 'settings'],
];
// Review is reached from Settings, so it keeps the Settings tab highlighted.
const NAV_PARENT = { '/review': '/settings', '/status': '/settings', '/people': '/settings', '/study': '/learn' };

const root = document.getElementById('app');
const session = { user: null };
let renderToken = 0;

export function navigate(path) {
  if (location.hash === `#${path}`) render();
  else location.hash = path;
}

function parseHash() {
  const raw = location.hash.replace(/^#/, '') || '/home';
  const [path, search = ''] = raw.split('?');
  return { path, params: new URLSearchParams(search) };
}

function tabbar(activePath) {
  const active = NAV_PARENT[activePath] || activePath;
  return h(
    'nav',
    { class: 'tabbar', 'aria-label': 'Main' },
    h(
      'div',
      { class: 'tabbar-inner' },
      NAV.map(([path, label, iconName]) =>
        h('a', { class: 'tab', href: `#${path}`, 'aria-current': path === active ? 'page' : undefined }, icon(iconName, 24), label),
      ),
    ),
  );
}

async function loadUser() {
  try {
    session.user = await get('/api/me');
  } catch (error) {
    session.user = null;
    if (error instanceof OfflineError) throw error;
  }
}

async function render() {
  const token = ++renderToken;
  let { path, params } = parseHash();

  if (!session.user && path !== '/login') return navigate('/login');
  if (session.user && path === '/login') return navigate('/home');
  if (!SCREENS[path] || (['/review', '/status', '/people'].includes(path) && session.user.role !== 'admin')) return navigate(session.user ? '/home' : '/login');

  const showNav = path !== '/login';
  root.replaceChildren(h('div', { class: 'app' }, h('main', { class: showNav ? 'screen' : 'screen no-nav' }, loading())));
  try {
    const module = await SCREENS[path]();
    const page = await module.default({ user: session.user, params, navigate, setUser });
    if (token !== renderToken) return; // a newer navigation won
    root.replaceChildren(h('div', { class: 'app' }, page, showNav ? tabbar(path) : null));
    window.scrollTo(0, 0);
  } catch (error) {
    if (token !== renderToken || (error && error.status === 401)) return;
    root.replaceChildren(h('div', { class: 'app' }, h('main', { class: showNav ? 'screen' : 'screen no-nav' }, errorBanner(error, render)), showNav ? tabbar(path) : null));
  }
}

function setUser(user) { session.user = user; }

// Behind Cloudflare Access the verified email is the sign-in: ask the server for a session, which it
// creates (or finds) from the Access token. Without Access the server answers 404, and so does a
// failure of any other kind, so the password login page is the fallback. Returns true if signed in.
async function signInWithAccess() {
  try {
    const user = await post('/api/access-login');
    session.user = { id: user.id, username: user.username, role: user.role };
    // A brand-new account gets the one-time "set a password" screen before Home.
    if (user.new) location.hash = '#/welcome';
    return true;
  } catch (error) {
    if (error instanceof OfflineError) throw error;
    return false;
  }
}

async function boot() {
  initTheme();
  setUnauthorizedHandler(async () => {
    session.user = null;
    // A session that ran out is replaced silently, so nobody is sent to a password page.
    if (await signInWithAccess().catch(() => false)) render();
    else navigate('/login');
  });
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js').catch(() => { /* the app works without it */ });
  }
  try {
    await loadUser();
    if (!session.user) await signInWithAccess();
  } catch (error) {
    root.replaceChildren(h('div', { class: 'app' }, h('main', { class: 'screen no-nav' }, errorBanner(error, () => location.reload()))));
    return;
  }
  // Only start routing once we know who the user is; offline, the banner offers a reload instead.
  window.addEventListener('hashchange', render);
  render();
}

boot();
