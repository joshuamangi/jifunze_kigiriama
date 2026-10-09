import { get, post } from '../api.js';
import { icon } from '../icons.js';
import { currentTheme, setTheme } from '../theme.js';
import { h, toast, topbar } from '../ui.js';

function appearanceSwitch() {
  const buttons = {};
  const paint = () => {
    for (const [name, button] of Object.entries(buttons)) button.setAttribute('aria-pressed', String(name === currentTheme()));
  };
  for (const [name, label, iconName] of [['dark', 'Dark', 'moon'], ['light', 'Light', 'sun']]) {
    buttons[name] = h('button', { class: 'chip', type: 'button' }, icon(iconName, 17), label);
    buttons[name].addEventListener('click', () => { setTheme(name); paint(); });
  }
  paint();
  return h('div', { class: 'switch' }, buttons.dark, buttons.light);
}

async function adminCard() {
  let detail = 'Approve or decline entries from members';
  try {
    const queue = await get('/api/review');
    detail = queue.pending_count === 0 ? 'Nothing is waiting for review' : `${queue.pending_count} ${queue.pending_count === 1 ? 'entry' : 'entries'} waiting for review`;
  } catch { /* keep the generic line; the Review screen shows the real error */ }
  return h(
    'section',
    null,
    h('h2', { class: 'eyebrow mt-lg' }, 'Admin'),
    h('a', { class: 'card link-card', href: '#/review' }, h('span', { class: 'primary' }, icon('shield', 20)), h('span', { class: 'grow' }, h('div', { class: 'strong' }, 'Review queue'), h('div', { class: 'small muted' }, detail)), h('span', { class: 'muted' }, icon('chevron', 16))),
  );
}

export default async function settings({ user, navigate, setUser }) {
  const logout = h('button', { class: 'btn btn-block', type: 'button' }, icon('logout', 18), 'Log out');
  logout.addEventListener('click', async () => {
    logout.disabled = true;
    try {
      await post('/api/logout');
    } catch (error) {
      if (error.status !== 401) {
        toast(error.message, 'error');
        logout.disabled = false;
        return;
      }
    }
    setUser(null);
    navigate('/login');
  });

  return h(
    'div',
    null,
    topbar({ title: 'Settings' }),
    h(
      'main',
      { class: 'screen' },
      h('h2', { class: 'eyebrow' }, 'Account'),
      h('div', { class: 'card stack' }, h('div', { class: 'row' }, h('span', { class: 'primary' }, icon('user', 20)), h('div', { class: 'grow' }, h('div', { class: 'strong' }, user.username), h('div', { class: 'small muted' }, user.role === 'admin' ? 'Admin' : 'Member'))), logout),
      h('h2', { class: 'eyebrow mt-lg' }, 'Study reminders'),
      h('div', { class: 'card notice-off' }, h('div', { class: 'row' }, h('span', { class: 'primary' }, icon('mail', 19)), h('div', { class: 'grow' }, h('div', { class: 'strong' }, 'Daily email reminder'), h('div', { class: 'small muted' }, 'Not available yet. Reminders will be switched on in a later update.')))),
      h('h2', { class: 'eyebrow mt-lg' }, 'Appearance'),
      appearanceSwitch(),
      user.role === 'admin' ? await adminCard() : null,
      h('h2', { class: 'eyebrow mt-lg' }, 'About'),
      h('div', { class: 'card' }, h('div', { class: 'strong' }, 'Jifunze Kigiriama'), h('p', { class: 'small muted no-margin' }, 'A self-hosted companion for learning Kigiriama, one entry at a time. Runs on your own Raspberry Pi.')),
    ),
  );
}
