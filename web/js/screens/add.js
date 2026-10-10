// Add Entry: the form, keyword search, group filter, the list, and edit-in-place with history.
import { get, patch, post, query } from '../api.js';
import { icon } from '../icons.js';
import { SOURCE_CHIPS, SOURCE_LABELS, STATUS_LABELS, STATUS_OPTIONS } from '../labels.js';
import { banner, chipGroup, debounce, emptyState, errorBanner, field, formatDate, h, loading, toast, topbar } from '../ui.js';

const PAGE_SIZE = 50;

export default async function add({ user, params }) {
  const isAdmin = user.role === 'admin';
  const [categories, gap] = await Promise.all([get('/api/categories'), get('/api/suggestions/gap')]);
  const categoryOptions = categories.map((c) => [c.id, c.label]);
  const labelOf = Object.fromEntries(categoryOptions);
  const requested = params.get('category');
  const startCategory = labelOf[requested] ? requested : gap.id;

  // ---- the form -------------------------------------------------------------------------
  const giriama = field({ label: 'Kigiriama', id: 'new-giriama', required: true });
  const english = field({ label: 'English meaning', id: 'new-english', required: true });
  const category = chipGroup({ label: 'Word group', options: categoryOptions, value: startCategory });
  const source = chipGroup({ label: 'Source', options: SOURCE_CHIPS, value: 'own' });
  const formMessage = h('div', { 'aria-live': 'polite' });
  const save = h('button', { class: 'btn btn-primary btn-block', type: 'submit' }, icon('add', 20), 'Save entry');
  const form = h(
    'form',
    { class: 'card mb', novalidate: true },
    giriama.node,
    english.node,
    h('div', { class: 'field-label' }, 'Word group'),
    category.node,
    h('div', { class: 'field-label' }, 'Source'),
    source.node,
    formMessage,
    save,
    h('p', { class: 'small muted' }, isAdmin ? 'As an admin, your entries are added straight away.' : 'An admin reviews new entries before other members can see them.'),
  );
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    formMessage.replaceChildren();
    if (!giriama.input.value.trim() || !english.input.value.trim()) {
      formMessage.replaceChildren(banner('warn', 'Fill in both the Kigiriama text and its English meaning.'));
      return;
    }
    save.disabled = true;
    try {
      await post('/api/entries', { giriama: giriama.input.value, english: english.input.value, category: category.get(), source_type: source.get() });
      toast(isAdmin ? 'Entry saved.' : 'Entry saved. It is waiting for review.');
      giriama.input.value = '';
      english.input.value = '';
      giriama.input.focus();
      loadList(true);
    } catch (error) {
      formMessage.replaceChildren(errorBanner(error));
    } finally {
      save.disabled = false;
    }
  });

  // ---- search, filter and list ----------------------------------------------------------
  const filter = chipGroup({ label: 'Filter by group', options: [['all', 'All'], ...categoryOptions], value: 'all', onChange: () => loadList(true) });
  const searchInput = h('input', { class: 'input', type: 'search', placeholder: 'Search by English or Kigiriama word', 'aria-label': 'Search entries', autocomplete: 'off', spellcheck: 'false' });
  searchInput.addEventListener('input', debounce(() => loadList(true), 300));
  const searchMode = chipGroup({
    label: 'Search by',
    options: [['keyword', 'Keyword'], ['semantic', 'Meaning']],
    value: 'keyword',
    onChange: () => {
      paintHint();
      if (searchInput.value.trim()) loadList(true);
    },
  });
  const hint = h('p', { class: 'small muted' });
  const paintHint = () => {
    hint.textContent = searchMode.get() === 'semantic'
      ? 'Describe the meaning in English. Entries with a similar meaning are found even when the words differ.'
      : 'Finds words typed in English or Kigiriama.';
  };
  paintHint();
  let indexingNote = '';
  const summary = h('p', { class: 'small muted', 'aria-live': 'polite' });
  const list = h('div');
  const more = h('button', { class: 'btn btn-block', type: 'button', hidden: true }, 'Show more');
  more.addEventListener('click', () => loadList(false));

  let shown = [];
  let total = 0;
  let loadToken = 0;

  async function loadList(reset) {
    const token = ++loadToken;
    if (reset) {
      shown = [];
      list.replaceChildren(loading());
    }
    try {
      const text = searchInput.value.trim();
      if (searchMode.get() === 'semantic' && text) {
        // Ranked by closest meaning; the server returns the best matches, so there is no paging.
        const data = await get(`/api/search${query({ q: text, mode: 'semantic', limit: 20 })}`);
        if (token !== loadToken) return;
        const group = filter.get();
        shown = data.items.filter((item) => group === 'all' || item.category === group);
        total = shown.length;
        indexingNote = data.not_yet_indexed > 0
          ? `${data.not_yet_indexed} ${data.not_yet_indexed === 1 ? 'entry is' : 'entries are'} still being indexed and ${data.not_yet_indexed === 1 ? "isn't" : "aren't"} searched yet.`
          : '';
        paintList();
        return;
      }
      indexingNote = '';
      const data = await get(`/api/entries${query({ category: filter.get() === 'all' ? '' : filter.get(), q: text, limit: PAGE_SIZE, offset: shown.length })}`);
      if (token !== loadToken) return;
      shown = shown.concat(data.items);
      total = data.total;
      paintList();
    } catch (error) {
      if (token !== loadToken || error.status === 401) return;
      list.replaceChildren(errorBanner(error, () => loadList(true)));
      summary.textContent = '';
      more.hidden = true;
    }
  }

  function paintList() {
    const filtering = filter.get() !== 'all' || searchInput.value.trim() !== '';
    const byMeaning = searchMode.get() === 'semantic' && searchInput.value.trim() !== '';
    const base = byMeaning
      ? `${total} ${total === 1 ? 'entry' : 'entries'} by closest meaning.`
      : filtering ? `Showing ${shown.length} of ${total} matching ${total === 1 ? 'entry' : 'entries'}.` : `${total} ${total === 1 ? 'entry' : 'entries'}.`;
    summary.textContent = indexingNote ? `${base} ${indexingNote}` : base;
    list.replaceChildren(...(shown.length ? shown.map(entryButton) : [emptyState('inbox', filtering ? 'No entries match these filters yet.' : 'No entries yet. Add the first one above.')]));
    more.hidden = byMeaning || shown.length >= total;
  }

  function statusBadge(entry) {
    if (entry.declined) return h('span', { class: 'badge badge-danger' }, isAdmin ? 'Declined' : 'Declined — edit to resubmit');
    if (entry.verification_status === 'pending') return h('span', { class: 'badge badge-warn' }, 'Waiting for review');
    if (entry.verification_status === 'native_verified') return h('span', { class: 'badge badge-ok' }, 'Native verified');
    if (entry.verification_status === 'self_corrected') return h('span', { class: 'badge' }, 'Self-corrected');
    return null;
  }

  function entryButton(entry) {
    const button = h(
      'button',
      { class: 'entry', type: 'button', 'aria-label': `Open entry ${entry.giriama}, ${entry.english}` },
      h('span', { class: 'entry-main' }, h('span', { class: 'entry-giriama' }, entry.giriama), h('span', { class: 'entry-english' }, entry.english), statusBadge(entry), isAdmin && entry.created_by ? h('span', { class: 'small muted' }, ` by ${entry.created_by}`) : null),
      h('span', { class: 'pill' }, labelOf[entry.category] || entry.category),
    );
    button.addEventListener('click', () => openEditor(entry));
    return button;
  }

  // ---- edit in place + history ----------------------------------------------------------
  function openEditor(entry) {
    const lockedReason = isAdmin ? null : !entry.mine ? 'You can only edit your own entries.' : entry.verification_status === 'native_verified' ? 'Only an admin can edit a native-verified entry.' : null;
    const readonly = Boolean(lockedReason);
    const eg = field({ label: 'Kigiriama', id: 'edit-giriama', value: entry.giriama, readonly });
    const ee = field({ label: 'English meaning', id: 'edit-english', value: entry.english, readonly });
    const ec = readonly ? null : chipGroup({ label: 'Word group', options: categoryOptions, value: entry.category });
    const es = readonly ? null : chipGroup({ label: 'Source', options: SOURCE_CHIPS, value: entry.source_type });
    const est = isAdmin ? chipGroup({ label: 'Status', options: STATUS_OPTIONS, value: entry.verification_status }) : null;
    const message = h('div', { 'aria-live': 'polite' });
    const dialog = h('dialog', { class: 'sheet', 'aria-label': 'Edit entry' });
    const close = () => dialog.close();

    const saveButton = readonly ? null : h('button', { class: 'btn btn-primary grow', type: 'submit' }, 'Save changes');
    const cancel = h('button', { class: 'btn grow', type: 'button' }, readonly ? 'Close' : 'Cancel');
    cancel.addEventListener('click', close);

    let note = null;
    if (!isAdmin && !readonly) {
      if (entry.declined) note = 'This entry was declined. Saving resubmits it for review.';
      else if (entry.verification_status !== 'pending') note = "Saving sends this entry back to review, and other members won't see it until it is approved again.";
    }

    const editForm = h(
      'form',
      { novalidate: true },
      lockedReason ? banner('info', icon('lock', 20), lockedReason) : null,
      eg.node,
      ee.node,
      ec ? [h('div', { class: 'field-label' }, 'Word group'), ec.node] : h('p', { class: 'small muted' }, `Group: ${labelOf[entry.category] || entry.category}`),
      es ? [h('div', { class: 'field-label' }, 'Source'), es.node] : h('p', { class: 'small muted' }, `Source: ${SOURCE_LABELS[entry.source_type] || entry.source_type}`),
      est ? [h('div', { class: 'field-label' }, 'Status'), est.node] : h('p', { class: 'small muted' }, `Status: ${STATUS_LABELS[entry.verification_status] || entry.verification_status}${entry.declined ? ' · declined' : ''}`),
      note ? h('p', { class: 'small muted' }, note) : null,
      message,
      h('div', { class: 'row' }, cancel, saveButton),
    );
    editForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (readonly) return;
      const body = {};
      const next = { giriama: eg.input.value.trim(), english: ee.input.value.trim(), category: ec.get(), source_type: es.get() };
      if (est) next.verification_status = est.get();
      for (const [key, value] of Object.entries(next)) if (value !== entry[key]) body[key] = value;
      if (!next.giriama || !next.english) {
        message.replaceChildren(banner('warn', 'Both the Kigiriama text and its English meaning are needed.'));
        return;
      }
      if (Object.keys(body).length === 0) {
        toast('No changes to save.');
        close();
        return;
      }
      saveButton.disabled = true;
      try {
        await patch(`/api/entries/${entry.id}`, body);
        toast(isAdmin ? 'Changes saved.' : 'Changes saved. The entry is waiting for review.');
        close();
        loadList(true);
      } catch (error) {
        message.replaceChildren(errorBanner(error));
        saveButton.disabled = false;
      }
    });

    const historyBox = h('div');
    const canSeeHistory = isAdmin || entry.mine;
    dialog.append(h('div', { class: 'sheet-body' }, h('h2', { class: 'h1' }, 'Edit entry'), editForm, canSeeHistory ? h('section', { class: 'mt-lg' }, h('h3', { class: 'h2 row' }, icon('history', 20), 'Earlier versions'), historyBox) : null));
    document.body.append(dialog);
    dialog.addEventListener('close', () => dialog.remove());
    dialog.showModal();
    if (canSeeHistory) loadHistory(entry, historyBox, close);
  }

  async function loadHistory(entry, box, close) {
    box.replaceChildren(loading());
    try {
      const rows = await get(`/api/entries/${entry.id}/history`);
      if (rows.length === 0) {
        box.replaceChildren(h('p', { class: 'small muted' }, 'No earlier versions — this entry has not been changed.'));
        return;
      }
      box.replaceChildren(...rows.map((row) => historyRow(entry, row, close)));
    } catch (error) {
      box.replaceChildren(errorBanner(error, () => loadHistory(entry, box, close)));
    }
  }

  function historyRow(entry, row, close) {
    const restore = h('button', { class: 'btn', type: 'button' }, icon('history', 16), 'Restore this version');
    let armed = false;
    restore.addEventListener('click', async () => {
      if (!armed) {
        armed = true;
        restore.textContent = 'Tap again to confirm';
        setTimeout(() => { armed = false; restore.replaceChildren(icon('history', 16), 'Restore this version'); }, 4000);
        return;
      }
      restore.disabled = true;
      try {
        await post(`/api/entries/${entry.id}/history/${row.id}/revert`);
        toast(isAdmin ? 'Earlier version restored.' : 'Earlier version restored. The entry is waiting for review.');
        close();
        loadList(true);
      } catch (error) {
        toast(error.message, 'error');
        restore.disabled = false;
      }
    });
    const who = isAdmin && row.changed_by ? ` by ${row.changed_by}` : '';
    return h(
      'div',
      { class: 'history-item' },
      h('div', { class: 'small muted' }, `Changed ${formatDate(row.changed_at)}${who}. Before that:`),
      h('div', { class: 'entry-giriama' }, row.old.giriama),
      h('div', { class: 'entry-english' }, `${row.old.english} · ${labelOf[row.old.category] || row.old.category} · ${SOURCE_LABELS[row.old.source_type] || row.old.source_type}`),
      h('div', { class: 'mt' }, restore),
    );
  }

  loadList(true);

  return h(
    'div',
    null,
    topbar({ title: 'Add entry' }),
    h(
      'main',
      { class: 'screen' },
      startCategory === gap.id ? banner('info', icon('bulb', 20), gap.count === 0 ? `Today's gap: you have no ${gap.label} entries yet — the form below is set to that group, ready to go.` : `Today's gap: ${gap.label} has the fewest entries (${gap.count}) — the form below is set to that group.`) : null,
      form,
      h('div', { class: 'search' }, icon('search', 16), searchInput),
      searchMode.node,
      hint,
      h('div', { class: 'field-label' }, 'Filter by group'),
      filter.node,
      summary,
      list,
      more,
    ),
  );
}
