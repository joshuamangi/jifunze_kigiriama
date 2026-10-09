// Interface wording shared by several screens. None of this is Kigiriama text.
export const SOURCE_CHIPS = [
  ['own', 'My own'],
  ['dictionary', 'Dictionary'],
  ['proverb', 'Proverb'],
  ['scripture', 'Scripture'],
];

export const SOURCE_LABELS = {
  own: 'Own addition',
  dictionary: 'From dictionary',
  proverb: 'From proverb collection',
  scripture: 'From scripture',
};

export const STATUS_OPTIONS = [
  ['pending', 'Pending review'],
  ['unverified', 'Unverified'],
  ['self_corrected', 'Self-corrected'],
  ['native_verified', 'Native verified'],
];

export const STATUS_LABELS = Object.fromEntries(STATUS_OPTIONS);

export const TOPIC_DESCRIPTIONS = {
  greetings: 'The first words for any conversation',
  family: 'Kinship terms and family words',
  numbers: 'Start with 1–10, build from there',
  proverbs: 'Short sayings — great for memorisation',
  food: 'Everyday vocabulary for routines',
};
