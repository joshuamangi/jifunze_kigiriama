import { get, post } from '../api.js';
import { icon } from '../icons.js';
import { banner, emptyState, errorBanner, field, h, toast, topbar } from '../ui.js';

// Admin only (the server checks too). The allow-list itself lives in Cloudflare Access.
export default async function people() {
  const state = await get('/api/admin/people');
  if (!state.enabled) {
    return h(
      'div',
      null,
      topbar({ title: 'People', back: '#/settings' }),
      h('main', { class: 'screen' }, banner('warn', 'Invites are not set up on this server yet. Add the Cloudflare settings described in docs/CLOUDFLARE_SETUP.md, then reload.')),
    );
  }

  let list = state.people;
  const rows = h('div');
  const summary = h('p', { class: 'lead', 'aria-live': 'polite' });
  const email = field({ label: 'Email address', id: 'invite-email', type: 'email', required: true, autocomplete: 'off', placeholder: 'name@example.com' });
  const message = h('div', { 'aria-live': 'polite' });
  const send = h('button', { class: 'btn btn-primary btn-block', type: 'submit' }, icon('mail', 20), 'Invite');

  async function reload() {
    list = (await get('/api/admin/people')).people;
    paint();
  }

  function row(person) {
    const status = person.signed_in_before ? `Signed in before as ${person.username}` : 'Has not signed in yet';
    const remove = h('button', { class: 'btn', type: 'button' }, icon('x', 16), 'Remove');
    let armed = false;
    remove.addEventListener('click', async () => {
      if (!armed) {
        armed = true;
        remove.textContent = 'Tap again to remove';
        setTimeout(() => { armed = false; remove.replaceChildren(icon('x', 16), 'Remove'); }, 4000);
        return;
      }
      remove.disabled = true;
      try {
        await post('/api/admin/people/remove', { email: person.email });
        toast('Removed. They can no longer sign in.');
        await reload();
      } catch (error) {
        remove.disabled = false;
        toast(error.message, 'error');
      }
    });
    return h(
      'article',
      { class: 'card' },
      h('div', { class: 'row-between' }, h('div', { class: 'entry-main' }, h('div', { class: 'strong' }, person.email), h('div', { class: 'small muted' }, person.is_you ? 'You' : status)), person.role === 'admin' ? h('span', { class: 'pill' }, 'Admin') : null),
      person.is_you ? null : h('div', { class: 'row' }, remove),
    );
  }

  function paint() {
    summary.textContent = `${list.length} ${list.length === 1 ? 'person is' : 'people are'} allowed in.`;
    rows.replaceChildren(...(list.length === 0 ? [emptyState('shield', 'Nobody is on the list.')] : list.map(row)));
  }

  const form = h('form', { class: 'card', novalidate: true }, email.node, message, send, h('p', { class: 'small muted' }, 'They get an email with the address of the app. Cloudflare then sends them a one-time code when they open it.'));
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    message.replaceChildren();
    if (!email.input.value.trim()) {
      message.replaceChildren(banner('warn', 'Enter an email address.'));
      return;
    }
    send.disabled = true;
    try {
      const result = await post('/api/admin/people', { email: email.input.value.trim() });
      email.input.value = '';
      if (!result.added) toast('That address was already on the list.');
      else if (result.emailed) toast('Invited. The email is on its way.');
      else message.replaceChildren(banner('warn', `${result.email} can now sign in, but the invite email did not send. Tell them the address yourself.`));
      await reload();
    } catch (error) {
      message.replaceChildren(error.status === 422 ? banner('warn', error.message) : errorBanner(error));
    } finally {
      send.disabled = false;
    }
  });

  paint();
  return h('div', null, topbar({ title: 'People', back: '#/settings' }), h('main', { class: 'screen' }, form, summary, rows, state.other_rules ? h('p', { class: 'small muted' }, `${state.other_rules} other access ${state.other_rules === 1 ? 'rule' : 'rules'} (such as a whole domain) can only be changed in Cloudflare.`) : null));
}
