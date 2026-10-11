#!/usr/bin/env bash
# Back up the SQLite database: a consistent copy, checked, pruned, optionally copied off the Pi.
#
# Uses `sqlite3 .backup`, which is safe while the app is running in WAL mode (copying the file
# with cp is not). The copy is only kept if PRAGMA integrity_check says "ok".
#
# Settings (from the environment, or ENV_FILE if DATABASE_PATH is unset):
#   DATABASE_PATH         the live database
#   BACKUP_DIR            where copies go (default $BASE/backups)
#   BACKUP_KEEP           how many copies to keep (default 14)
#   BACKUP_STAMP_PATH     touched after a verified local backup; /api/admin/status shows its time
#   BACKUP_REQUIRE_MOUNT  set to 1 when BACKUP_DIR is a mounted disk (the SSD, bind-mounted): the
#                         script then refuses to run if it is NOT a mount point, so an unplugged
#                         SSD can never make backups pile up on the SD card instead
#   BACKUP_COPY_COMMAND   optional shell command run with the new file as "$1", e.g.
#                         'rclone copyto "$1" remote:jifunze/'. If it fails this script exits
#                         non-zero (so the OnFailure= email fires) even though the local backup
#                         and the stamp are already in place.
#
#   backup.sh [--dry-run]
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$HERE/lib.sh"

[ "${1:-}" = "--dry-run" ] && DRY_RUN=1
[ -n "${DATABASE_PATH:-}" ] || load_env
DB="${DATABASE_PATH:-$BASE/data/app.db}"
BACKUP_DIR="${BACKUP_DIR:-$BASE/backups}"
KEEP="${BACKUP_KEEP:-14}"
STAMP="${BACKUP_STAMP_PATH:-$(dirname "$DB")/last_backup}"

[ -f "$DB" ] || die "database not found: $DB"
case "$BACKUP_DIR$DB" in *\'*) die "paths may not contain a single quote" ;; esac

if [ "${BACKUP_REQUIRE_MOUNT:-0}" = 1 ] && [ "$DRY_RUN" = 0 ]; then
  command -v mountpoint >/dev/null 2>&1 || die "BACKUP_REQUIRE_MOUNT=1 but the mountpoint command is missing"
  mountpoint -q "$BACKUP_DIR" || die "$BACKUP_DIR is not a mounted disk: is the SSD plugged in?"
fi

name="app-$(date -u +%Y%m%dT%H%M%SZ).db"
final="$BACKUP_DIR/$name"
partial="$BACKUP_DIR/.$name.partial"

step "backup $DB -> $final"
run mkdir -p "$BACKUP_DIR"
# Permissions are best-effort: an exFAT disk has none (its owner and mode are fixed at mount time).
run chmod 700 "$BACKUP_DIR" 2>/dev/null || log "note: could not set permissions on $BACKUP_DIR"
if [ "$DRY_RUN" = 1 ]; then
  log "[dry-run] sqlite3 .backup, integrity_check, prune to $KEEP, touch $STAMP"
  exit 0
fi

trap 'rm -f "$partial"' EXIT
sqlite3 -cmd ".timeout 10000" "$DB" ".backup '$partial'"
result="$(sqlite3 "$partial" "PRAGMA integrity_check;")"
[ "$result" = "ok" ] || die "integrity check of the new backup failed: $result"
chmod 600 "$partial" 2>/dev/null || true
mv "$partial" "$final"
touch "$STAMP"
log "backup ok: $final ($(wc -c <"$final" | tr -d ' ') bytes)"

step "prune: keep the newest $KEEP"
# Names carry a sortable UTC timestamp, so a name sort is a date sort.
find "$BACKUP_DIR" -maxdepth 1 -type f -name 'app-*.db' | sort -r | tail -n +"$((KEEP + 1))" |
  while IFS= read -r old; do
    log "removing $old"
    rm -f "$old"
  done

if [ -n "${BACKUP_COPY_COMMAND:-}" ]; then
  step "off-device copy"
  sh -c "$BACKUP_COPY_COMMAND" jifunze-backup "$final" || die "off-device copy failed"
else
  log "no BACKUP_COPY_COMMAND set: this backup exists only on this machine"
fi
