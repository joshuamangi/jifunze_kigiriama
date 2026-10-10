import { get } from '../api.js';
import { icon } from '../icons.js';
import { h, topbar } from '../ui.js';

// The eight-tier ladder from CLAUDE.md. Tiers 1 and 2 can be studied; the rest stay locked.
const TIERS = [
  ['Sounds & orthography', 'Spelling practice from your entries: see the meaning, write the word. Pronunciation and tone need audio, which comes later.', 'live'],
  ['Core vocabulary', 'High-frequency nouns and verbs, recognition practice.', 'live'],
  ['Noun classes', 'How Giriama nouns group and agree with their modifiers.', 'locked'],
  ['Verb morphology', 'Subject prefixes and tense patterns on common verbs.', 'locked'],
  ['Proverbs', 'Short, self-contained phrases \u2014 a natural bridge to full sentences.', 'locked'],
  ['Single verses', 'Full sentences, paired with listening practice.', 'locked'],
  ['Short passages', 'Multi-sentence comprehension and cloze exercises.', 'locked'],
  ['Guided reading', 'Longer passages with a rolling glossary.', 'locked'],
];

function stat(iconName, value, text) {
  return h('div', { class: 'card stat' }, h('span', { class: 'primary' }, icon(iconName, 20)), h('div', { class: 'stat-value' }, String(value)), h('div', { class: 'stat-label' }, text));
}

export default async function learn() {
  const today = await get('/api/learn/summary');
  const toStudy = today.due_today + today.new_available;

  const tierCard = ([name, description, state], index) => {
    const body = [
      h('div', { class: 'tier-num', 'aria-hidden': 'true' }, String(index + 1)),
      h(
        'div',
        { class: 'grow' },
        h('div', { class: 'row-between' }, h('div', { class: 'tier-name' }, name), state === 'locked' ? h('span', { class: 'muted' }, icon('lock', 16)) : h('span', { class: 'muted' }, icon('chevron', 16))),
        h('div', { class: 'small muted' }, description),
        h('span', { class: state === 'live' ? 'badge badge-ok' : 'badge' }, state === 'live' ? (toStudy ? `${toStudy} to study today` : 'Nothing due today') : 'Locked'),
      ),
    ];
    return state === 'live'
      ? h('li', null, h('a', { class: `card tier tier-live`, href: `#/study?tier=${index + 1}` }, body))
      : h('li', { class: 'card tier tier-locked' }, body);
  };

  return h(
    'div',
    null,
    topbar({ title: 'Learn' }),
    h(
      'main',
      { class: 'screen' },
      h('p', { class: 'lead' }, 'Your path from first sounds to full passages, in eight tiers.'),
      h('div', { class: 'stats' }, stat('flame', today.streak_days, 'Day streak'), stat('clock', toStudy, today.estimated_minutes ? `To study, about ${today.estimated_minutes} min` : 'To study today')),
      h('ol', { class: 'plain-list' }, TIERS.map(tierCard)),
    ),
  );
}
