import { get } from '../api.js';
import { icon } from '../icons.js';
import { TOPIC_DESCRIPTIONS } from '../labels.js';
import { h, topbar } from '../ui.js';

const MIN_ENTRIES_FOR_SESSION = 5;

export default async function home() {
  const [categories, gap] = await Promise.all([get('/api/categories'), get('/api/suggestions/gap')]);
  const total = categories.reduce((sum, c) => sum + c.count, 0);
  // Fewest entries first, so the gap leads. Ties keep the server's list order.
  const topics = [...categories].sort((a, b) => a.count - b.count);

  // Nothing records study activity yet, so the streak is a true zero for now.
  const streak = 0;

  return h(
    'div',
    null,
    topbar({ title: 'Jifunze Kigiriama' }),
    h(
      'main',
      { class: 'screen' },
      h('p', { class: 'lead' }, "Welcome back. Let's build your Kigiriama, one entry at a time."),
      h(
        'div',
        { class: 'stats' },
        h('div', { class: 'card stat' }, h('span', { class: 'secondary' }, icon('flame', 20)), h('div', { class: 'stat-value' }, String(streak)), h('div', { class: 'stat-label' }, 'Current streak (days)')),
        h('div', { class: 'card stat' }, h('span', { class: 'info' }, icon('entries', 20)), h('div', { class: 'stat-value' }, String(total)), h('div', { class: 'stat-label' }, total === 1 ? 'Entry' : 'Entries')),
      ),
      h(
        'section',
        { class: 'card mb' },
        h('div', { class: 'row' }, h('span', { class: 'primary' }, icon('clock', 19)), h('h2', { class: 'h2 no-margin' }, "Today's 20-minute session")),
        total < MIN_ENTRIES_FOR_SESSION
          ? h('p', { class: 'small muted' }, `Add at least ${MIN_ENTRIES_FOR_SESSION} entries to unlock your first guided session — every review is built from words and phrases in the dictionary.`)
          : h('p', { class: 'small muted' }, 'Daily study sessions are coming in a later update.'),
        h('a', { class: 'btn btn-primary', href: `#/add?category=${encodeURIComponent(gap.id)}` }, icon('add', 18), total === 0 ? 'Add your first entries' : 'Add entries'),
      ),
      h('h2', { class: 'eyebrow' }, 'Suggested topics to start with'),
      topics.map((topic) =>
        h(
          'a',
          { class: 'card link-card', href: `#/add?category=${encodeURIComponent(topic.id)}` },
          h(
            'span',
            { class: 'grow' },
            h('div', { class: 'strong' }, topic.label),
            h('div', { class: 'small muted' }, TOPIC_DESCRIPTIONS[topic.id] || ''),
            h('div', { class: 'small muted' }, topic.count === 1 ? '1 entry' : `${topic.count} entries`),
          ),
          h('span', { class: 'muted' }, icon('arrow', 15)),
        ),
      ),
      h('p', { class: 'mt-lg' }, h('a', { class: 'btn', href: '#/culture' }, 'Explore Giriama culture & media', icon('arrow', 14))),
    ),
  );
}
