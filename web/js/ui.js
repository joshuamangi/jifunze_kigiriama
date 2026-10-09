// Small DOM helpers. User text only ever reaches the page as text nodes or attribute values,
// never as markup (a test forbids the HTML-string DOM APIs in web/js).
import { icon } from './icons.js';
import { currentTheme, setTheme } from './theme.js';

export function h(tag, props, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === 'class') el.className = value;
    else if (key.startsWith('on') && typeof value === 'function') el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value === true ? '' : String(value));
  }
  for (const child of children.flat(Infinity)) {
    if (child === undefined || child === null || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

export function debounce(fn, ms) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

export function formatDate(iso) {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
}

export function toast(message, kind = 'info') {
  const host = document.getElementById('toasts');
  const node = h('div', { class: kind === 'error' ? 'toast toast-error' : 'toast' }, message);
  host.append(node);
  setTimeout(() => node.remove(), 4000);
}

export function banner(kind, ...children) {
  return h('div', { class: kind === 'info' ? 'banner' : `banner banner-${kind}`, role: kind === 'info' ? undefined : 'alert' }, ...children);
}

// Shown when an API call fails. Offline gets its own wording so an empty list is never mistaken
// for "no data".
export function errorBanner(error, retry) {
  const offline = error && error.name === 'OfflineError';
  const message = offline ? "You're offline. Connect to the internet to load this." : (error && error.message) || 'Something went wrong.';
  return banner(
    offline ? 'warn' : 'danger',
    icon(offline ? 'offline' : 'x', 18),
    h('div', { class: 'grow' }, message, retry ? h('div', null, h('button', { class: 'btn', type: 'button', onclick: retry }, 'Try again')) : null),
  );
}

export function loading(text = 'Loading…') {
  return h('p', { class: 'muted small', role: 'status' }, text);
}

export function emptyState(iconName, text) {
  return h('div', { class: 'empty' }, icon(iconName, 34), h('div', null, text));
}

export function themeButton() {
  const button = h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Toggle colour theme' });
  const paint = () => button.replaceChildren(icon(currentTheme() === 'dark' ? 'sun' : 'moon', 17));
  button.addEventListener('click', () => setTheme(currentTheme() === 'dark' ? 'light' : 'dark'));
  document.addEventListener('themechange', paint);
  paint();
  return button;
}

export function topbar({ title, back } = {}) {
  return h(
    'header',
    { class: 'topbar' },
    h(
      'div',
      { class: 'topbar-left' },
      back ? h('a', { class: 'icon-btn', href: back, 'aria-label': 'Back' }, icon('back', 16)) : null,
      h('h1', { class: 'topbar-title' }, title),
    ),
    themeButton(),
  );
}

// A row of toggle buttons where exactly one is pressed. Returns { node, get, set }.
export function chipGroup({ label, options, value, onChange }) {
  let current = value;
  const buttons = new Map();
  const node = h('div', { class: 'chips', role: 'group', 'aria-label': label });
  for (const [id, text] of options) {
    const button = h('button', { class: 'chip', type: 'button', 'aria-pressed': String(id === current) }, text);
    button.addEventListener('click', () => set(id, true));
    buttons.set(id, button);
    node.append(button);
  }
  function set(id, notify = false) {
    current = id;
    for (const [key, button] of buttons) button.setAttribute('aria-pressed', String(key === id));
    if (notify && onChange) onChange(id);
  }
  return { node, get: () => current, set };
}

export function field({ label, id, value = '', type = 'text', placeholder = '', required = false, readonly = false, autocomplete }) {
  const input = h('input', { class: 'input', id, type, value, placeholder, required, readonly, autocomplete, autocapitalize: 'none', spellcheck: 'false' });
  return { node: h('label', { class: 'field', for: id }, h('span', { class: 'field-label' }, label), input), input };
}
