import { get, post } from '../api.js';
import { icon } from '../icons.js';
import { SOURCE_LABELS } from '../labels.js';
import { emptyState, formatDate, h, toast, topbar } from '../ui.js';

export default async function review() {
  const [queue, categories] = await Promise.all([get('/api/review'), get('/api/categories')]);
  const labels = Object.fromEntries(categories.map((c) => [c.id, c.label]));
  let pending = queue.items;

  const summary = h('p', { class: 'lead', 'aria-live': 'polite' });
  const list = h('div');

  function paint() {
    summary.textContent = pending.length === 0 ? 'Nothing is waiting for review.' : `${pending.length} ${pending.length === 1 ? 'entry' : 'entries'} waiting for review.`;
    list.replaceChildren(...(pending.length === 0 ? [emptyState('check', 'Queue is clear — nothing waiting on review.')] : pending.map(card)));
  }

  function card(item) {
    const decline = h('button', { class: 'btn grow', type: 'button' }, icon('x', 14), 'Decline');
    const approve = h('button', { class: 'btn btn-success grow', type: 'button' }, icon('check', 14), 'Approve');
    const act = async (verb) => {
      decline.disabled = approve.disabled = true;
      try {
        await post(`/api/review/${item.id}/${verb}`);
        pending = pending.filter((p) => p.id !== item.id);
        toast(verb === 'approve' ? 'Approved.' : 'Declined.');
        paint();
      } catch (error) {
        decline.disabled = approve.disabled = false;
        toast(error.message, 'error');
      }
    };
    decline.addEventListener('click', () => act('decline'));
    approve.addEventListener('click', () => act('approve'));
    return h(
      'article',
      { class: 'card' },
      h('div', { class: 'row-between' }, h('div', { class: 'entry-main' }, h('div', { class: 'entry-giriama' }, item.giriama), h('div', { class: 'entry-english' }, item.english)), h('span', { class: 'pill' }, labels[item.category] || item.category)),
      h('p', { class: 'small muted' }, `${SOURCE_LABELS[item.source_type] || item.source_type} · added by ${item.created_by || 'unknown'} · ${formatDate(item.created_at)}`),
      h('div', { class: 'row' }, decline, approve),
    );
  }

  paint();
  return h('div', null, topbar({ title: 'Review queue', back: '#/settings' }), h('main', { class: 'screen' }, summary, list));
}
