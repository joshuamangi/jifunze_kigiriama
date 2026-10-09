import { icon } from '../icons.js';
import { h, topbar } from '../ui.js';

// The eight-tier ladder from CLAUDE.md. Nothing is unlockable yet, so no progress is claimed.
const TIERS = [
  ['Sounds & orthography', 'Pronunciation, vowel length and tone, spelling conventions.', 'soon'],
  ['Core vocabulary', 'High-frequency nouns and verbs, recognition practice.', 'soon'],
  ['Noun classes', 'How Giriama nouns group and agree with their modifiers.', 'locked'],
  ['Verb morphology', 'Subject prefixes and tense patterns on common verbs.', 'locked'],
  ['Proverbs', 'Short, self-contained phrases — a natural bridge to full sentences.', 'locked'],
  ['Single verses', 'Full sentences, paired with listening practice.', 'locked'],
  ['Short passages', 'Multi-sentence comprehension and cloze exercises.', 'locked'],
  ['Guided reading', 'Longer passages with a rolling glossary.', 'locked'],
];

export default async function learn() {
  return h(
    'div',
    null,
    topbar({ title: 'Learn' }),
    h(
      'main',
      { class: 'screen' },
      h('p', { class: 'lead' }, 'Your path from first sounds to full passages, in eight tiers.'),
      h(
        'ol',
        { class: 'plain-list' },
        TIERS.map(([name, description, state], index) =>
          h(
            'li',
            { class: `card tier tier-${state}` },
            h('div', { class: 'tier-num', 'aria-hidden': 'true' }, String(index + 1)),
            h(
              'div',
              { class: 'grow' },
              h('div', { class: 'row-between' }, h('div', { class: 'tier-name' }, name), state === 'locked' ? h('span', { class: 'muted' }, icon('lock', 16)) : null),
              h('div', { class: 'small muted' }, description),
              h('span', { class: state === 'soon' ? 'badge badge-warn' : 'badge' }, state === 'soon' ? 'Coming soon' : 'Locked'),
            ),
          ),
        ),
      ),
    ),
  );
}
