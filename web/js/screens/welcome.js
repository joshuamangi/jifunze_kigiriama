import { ApiError, OfflineError, put } from '../api.js';
import { icon } from '../icons.js';
import { banner, field, h, themeButton } from '../ui.js';

// Shown once, right after someone's first sign-in through Cloudflare Access. The password is
// optional: Access is what signs them in, so skipping loses nothing.
export default async function welcome({ user, navigate }) {
  const password = field({ label: 'New password', id: 'new-password', type: 'password', required: true, autocomplete: 'new-password' });
  const message = h('div', { 'aria-live': 'polite' });
  const save = h('button', { class: 'btn btn-primary btn-block', type: 'submit' }, 'Save password');
  const skip = h('button', { class: 'btn btn-block', type: 'button' }, 'Skip for now');
  skip.addEventListener('click', () => navigate('/home'));

  const form = h('form', { novalidate: true }, password.node, message, save, skip);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    message.replaceChildren();
    if (!password.input.value) {
      message.replaceChildren(banner('warn', 'Enter a password, or skip for now.'));
      return;
    }
    save.disabled = true;
    try {
      await put('/api/me/password', { password: password.input.value });
      navigate('/home');
    } catch (error) {
      let text = error.message;
      if (error instanceof OfflineError) text = "You're offline. Connect to the internet to save a password.";
      else if (error instanceof ApiError && error.status === 422) text = error.message;
      message.replaceChildren(banner('danger', text));
      password.input.focus();
    } finally {
      save.disabled = false;
    }
  });

  return h(
    'div',
    null,
    h('header', { class: 'topbar' }, h('h1', { class: 'topbar-title' }, 'Jifunze Kigiriama'), themeButton()),
    h(
      'main',
      { class: 'screen no-nav' },
      h('div', { class: 'brand' }, h('div', { class: 'login-mark' }, icon('lock', 24)), h('h2', { class: 'h1' }, `Karibu, ${user.username}`), h('p', { class: 'lead' }, 'Your email is confirmed, so you are signed in. You can set a password for your account now, or skip it.')),
      form,
    ),
  );
}
