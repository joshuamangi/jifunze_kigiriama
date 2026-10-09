import { ApiError, OfflineError, post } from '../api.js';
import { icon } from '../icons.js';
import { banner, field, h, themeButton } from '../ui.js';

export default async function login({ navigate, setUser }) {
  const username = field({ label: 'Username', id: 'username', required: true, autocomplete: 'username' });
  const password = field({ label: 'Password', id: 'password', type: 'password', required: true, autocomplete: 'current-password' });
  const message = h('div', { 'aria-live': 'polite' });
  const submit = h('button', { class: 'btn btn-primary btn-block', type: 'submit' }, 'Log in');

  const form = h('form', { novalidate: true }, username.node, password.node, message, submit);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    message.replaceChildren();
    if (!username.input.value.trim() || !password.input.value) {
      message.replaceChildren(banner('warn', 'Enter your username and password.'));
      return;
    }
    submit.disabled = true;
    try {
      const user = await post('/api/login', { username: username.input.value.trim(), password: password.input.value });
      setUser(user);
      navigate('/home');
    } catch (error) {
      let text = error.message;
      if (error instanceof OfflineError) text = "You're offline. Connect to the internet to log in.";
      else if (error instanceof ApiError && error.status === 401) text = 'That username and password do not match.';
      else if (error instanceof ApiError && error.status === 429) {
        text = error.retryAfter ? `Too many attempts. Try again in ${error.retryAfter} seconds.` : 'Too many attempts. Try again later.';
      }
      message.replaceChildren(banner('danger', text));
      password.input.value = '';
      password.input.focus();
    } finally {
      submit.disabled = false;
    }
  });

  return h(
    'div',
    null,
    h('header', { class: 'topbar' }, h('h1', { class: 'topbar-title' }, 'Jifunze Kigiriama'), themeButton()),
    h(
      'main',
      { class: 'screen no-nav' },
      h('div', { class: 'brand' }, h('div', { class: 'login-mark' }, icon('lock', 24)), h('h2', { class: 'h1' }, 'Welcome back'), h('p', { class: 'lead' }, 'Sign in to continue your Kigiriama study set.')),
      form,
      h('p', { class: 'muted small' }, "Accounts are created by whoever runs this app — there's no self sign-up. New to the group? Ask for an invite."),
    ),
  );
}
