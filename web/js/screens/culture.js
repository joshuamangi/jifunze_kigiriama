import { icon } from '../icons.js';
import { h, topbar } from '../ui.js';

function linkCard({ href, title, description, iconName }) {
  return h(
    'a',
    { class: 'card link-card', href, target: '_blank', rel: 'noopener noreferrer' },
    h('span', { class: 'muted' }, icon(iconName, 26)),
    h('span', { class: 'grow' }, h('div', { class: 'strong' }, title), description ? h('div', { class: 'small muted' }, description) : null),
    h('span', { class: 'muted' }, icon('external', 15)),
  );
}

export default async function culture() {
  return h(
    'div',
    null,
    topbar({ title: 'Culture & media' }),
    h(
      'main',
      { class: 'screen' },
      h('p', { class: 'lead' }, 'Real Giriama voices and sources — for listening, watching and reading alongside what you add yourself.'),
      h('h2', { class: 'eyebrow' }, 'Listen'),
      linkCard({ href: 'https://radiokaya.co.ke/about-us/', title: 'Radio Kaya', description: 'Giriama-language radio from the Kenyan coast', iconName: 'culture' }),
      h('h2', { class: 'eyebrow mt-lg' }, 'Watch'),
      linkCard({ href: 'https://www.youtube.com/watch?v=nJCcFV0eD8M&list=PLj5MjNsE7TuO45QDqbG2e37m0D2xnJwGs', title: 'Giriama video playlist — part 1', description: 'Opens on YouTube', iconName: 'play' }),
      linkCard({ href: 'https://www.youtube.com/watch?v=4PfbeooduVo&list=PLj5MjNsE7TuO45QDqbG2e37m0D2xnJwGs&index=1', title: 'Giriama video playlist — part 2', description: 'Opens on YouTube', iconName: 'play' }),
      h('h2', { class: 'eyebrow mt-lg' }, 'Read'),
      linkCard({ href: 'https://archive.org/details/giryamavocabula01taylgoog', title: 'Taylor, Giryama Vocabulary and Collections (1891)', description: 'Dictionary with grammar notes on noun classes and verbs. The scanned text is noisy, so check what you copy.', iconName: 'entries' }),
      linkCard({ href: 'https://www.maktaba.org/download/file/547/African_aphorisms_-_methali_za_kiswahili_.pdf', title: 'African Aphorisms (1891)', description: 'Mostly Swahili proverbs — the Giriama & Nyika section starts around page 150', iconName: 'entries' }),
      h('div', { class: 'banner mt-lg' }, icon('bulb', 18), h('div', null, 'Found a good proverb or phrase in one of these? Copy it into Add Entry so it joins your own study set.')),
    ),
  );
}
