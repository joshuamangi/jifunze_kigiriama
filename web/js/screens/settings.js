import { get, post, put } from '../api.js';
import { icon } from '../icons.js';
import { currentTheme, setTheme } from '../theme.js';
import { banner, chipGroup, errorBanner, field, h, toast, topbar } from '../ui.js';

function appearanceSwitch() {
  const buttons = {};
  const paint = () => {
    for (const [name, button] of Object.entries(buttons)) button.setAttribute('aria-pressed', String(name === currentTheme()));
  };
  for (const [name, label, iconName] of [['dark', 'Dark', 'moon'], ['light', 'Light', 'sun']]) {
    buttons[name] = h('button', { class: 'chip', type: 'button' }, icon(iconName, 16), label);
    buttons[name].addEventListener('click', () => { setTheme(name); paint(); });
  }
  paint();
  return h('div', { class: 'switch' }, buttons.dark, buttons.light);
}

async function reminderCard() {
  let current;
  try {
    current = await get('/api/reminders');
  } catch (error) {
    return h('div', { class: 'card' }, errorBanner(error));
  }
  const enabled = chipGroup({ label: 'Reminder', options: [['on', 'On'], ['off', 'Off']], value: current.enabled ? 'on' : 'off' });
  const time = field({ label: 'Time', id: 'reminder-time', type: 'time', value: current.send_at });
  const how = chipGroup({ label: 'How often', options: [['daily', 'Every day'], ['weekdays', 'Weekdays only']], value: current.frequency });
  const email = field({ label: 'Send to', id: 'reminder-email', type: 'email', value: current.email, autocomplete: 'email', placeholder: 'you@example.com' });
  const message = h('div', { 'aria-live': 'polite' });
  const save = h('button', { class: 'btn btn-primary btn-block', type: 'submit' }, 'Save reminder');
  const form = h(
    'form',
    { class: 'card', novalidate: true },
    h('div', { class: 'row mb' }, h('span', { class: 'primary' }, icon('mail', 20)), h('div', { class: 'grow' }, h('div', { class: 'strong' }, 'Daily email reminder'), h('div', { class: 'small muted' }, 'A short nudge to do today\u2019s session'))),
    h('div', { class: 'field-label' }, 'Reminder'),
    enabled.node,
    time.node,
    h('div', { class: 'field-label' }, 'How often'),
    how.node,
    email.node,
    message,
    save,
    h('p', { class: 'small muted' }, `Sent once a day at this time (${current.timezone} time) by a scheduled job on the server. An email only goes out when you have cards to study.`),
  );
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    message.replaceChildren();
    save.disabled = true;
    try {
      await put('/api/reminders', { enabled: enabled.get() === 'on', send_at: time.input.value, frequency: how.get(), email: email.input.value });
      toast('Reminder saved.');
    } catch (error) {
      message.replaceChildren(error.status === 422 ? banner('warn', error.message) : errorBanner(error));
    } finally {
      save.disabled = false;
    }
  });
  return form;
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
    h('a', { class: 'card link-card', href: '#/status' }, h('span', { class: 'primary' }, icon('entries', 20)), h('span', { class: 'grow' }, h('div', { class: 'strong' }, 'System status'), h('div', { class: 'small muted' }, 'Database size, search index, backups, failed logins')), h('span', { class: 'muted' }, icon('chevron', 16))),
  );
}

export default async function settings({ user, navigate, setUser }) {
  const logout = h('button', { class: 'btn btn-block', type: 'button' }, icon('logout', 20), 'Log out');
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
      await reminderCard(),
      h('h2', { class: 'eyebrow mt-lg' }, 'Appearance'),
      appearanceSwitch(),
      user.role === 'admin' ? await adminCard() : null,
      h('h2', { class: 'eyebrow mt-lg' }, 'About'),
      h('div', { class: 'card' }, h('div', { class: 'strong' }, 'Jifunze Kigiriama'), h('p', { class: 'small muted no-margin' }, 'A self-hosted companion for learning Kigiriama, one entry at a time. Runs on your own Raspberry Pi.')),
    ),
  );
}
