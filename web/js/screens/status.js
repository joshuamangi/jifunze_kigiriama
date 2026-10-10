import { get } from '../api.js';
import { h, topbar } from '../ui.js';

function bytes(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function when(iso) {
  if (!iso) return 'Never';
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? 'Unknown' : date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

function row(label, value, note) {
  return h(
    'div',
    { class: 'row-between' },
    h('div', null, h('div', { class: 'strong' }, label), note ? h('div', { class: 'small muted' }, note) : null),
    h('div', null, value),
  );
}

export default async function status() {
  const s = await get('/api/admin/status');
  const pending = s.embeddings.pending;
  const failed = s.audit.failed_logins_24h;
  return h(
    'div',
    null,
    topbar({ title: 'System status', back: '#/settings' }),
    h(
      'main',
      { class: 'screen' },
      h('p', { class: 'lead' }, 'Read-only. Reload the page to refresh.'),
      h(
        'section',
        { class: 'card status-list' },
        row('Database', bytes(s.database.bytes), `Write-ahead log ${bytes(s.database.wal_bytes)}`),
        row('Waiting for search index', String(pending), pending === 0 ? 'All entries are indexed' : 'Entries not yet embedded for meaning search'),
        row('Last backup', when(s.backup.last_backup_at), s.backup.last_backup_at ? null : 'No backup has been recorded yet'),
        row('Failed logins, last 24 hours', String(failed)),
      ),
    ),
  );
}
