#!/usr/bin/env bash
# Install one release and make it live, or put the previous one back.
#
#   deploy.sh [--dry-run] [--tarball FILE] <release-tag>
#
# The tarball (default $BASE/incoming/jifunze-<tag>.tar.gz) is built and checksummed by CI and
# holds app/, web/, migrations/, scripts/, deploy/, pyproject.toml and requirements.lock.
#
# Steps: unpack to releases/<tag> -> build its virtualenv from requirements.lock with hash
# checking -> BACK UP THE DATABASE -> run migrations -> switch the `current` symlink atomically
# -> restart -> health check -> on failure run rollback.sh. The last 5 releases are kept.
#
# RULE: MIGRATIONS MUST BE BACKWARD COMPATIBLE. Add columns and tables in one release and remove
# them in a later one, so the previous code still runs on the new schema. That is what lets a
# rollback be "point the symlink back" with no database restore. Migrations run before the switch
# while the old code is still serving, so this matters twice. Never edit an applied migration.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$HERE/lib.sh"

PYTHON="${JIFUNZE_PYTHON:-python3}"
tarball=""
tag=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --tarball)
      tarball="${2:-}"
      shift
      ;;
    -*) die "unknown option: $1" ;;
    *) tag="$1" ;;
  esac
  shift
done
[ -n "$tag" ] || die "usage: deploy.sh [--dry-run] [--tarball FILE] <release-tag>"
# The tag becomes a directory name: no slashes, no leading dot, nothing exotic.
[[ "$tag" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || die "bad release tag: $tag"
tarball="${tarball:-$BASE/incoming/jifunze-$tag.tar.gz}"
release="$BASE/releases/$tag"

if [ "$DRY_RUN" = 0 ]; then
  mkdir -p "$BASE/releases"
  if command -v flock >/dev/null 2>&1; then
    exec 9>"$BASE/.deploy.lock"
    flock -n 9 || die "another deploy is running"
  else
    log "flock is not installed: no guard against two deploys at once"
  fi
  [ -e "$release" ] && die "release already exists: $release (deploy a new tag)"
  [ -f "$tarball" ] || die "tarball not found: $tarball"
fi

created=0
switched=0
cleanup() {
  # A release that never went live is removed, so the same tag can be retried.
  if [ "$created" = 1 ] && [ "$switched" = 0 ]; then
    log "cleaning up the unfinished release $release"
    rm -rf "$release" "$release.partial"
  fi
}
trap cleanup EXIT

step "1/9 unpack $tarball -> $release"
if [ "$DRY_RUN" = 0 ]; then
  created=1
  rm -rf "$release.partial"
  mkdir -p "$release.partial"
  tar -xzf "$tarball" -C "$release.partial"
  mv "$release.partial" "$release"
else
  log "[dry-run] tar -xzf $tarball -C $release.partial && mv into place"
fi

step "2/9 build the virtualenv (hash-checked)"
run "$PYTHON" -m venv "$release/.venv"
run "$release/.venv/bin/pip" install --quiet --require-hashes --no-deps -r "$release/requirements.lock"

step "3/9 back up the database"
if [ "$DRY_RUN" = 1 ]; then
  log "[dry-run] $HERE/backup.sh"
else
  load_env
  if [ -f "${DATABASE_PATH:-$BASE/data/app.db}" ]; then
    "$HERE/backup.sh"
  else
    log "no database yet (first deploy): nothing to back up"
  fi
fi

step "4/9 run migrations with the new code"
if [ "$DRY_RUN" = 1 ]; then
  log "[dry-run] (cd $release && python -m app.migrate)"
else
  (cd "$release" && PYTHONPATH="$release" "$release/.venv/bin/python" -m app.migrate)
fi

step "5/9 switch current -> releases/$tag"
if [ "$DRY_RUN" = 1 ]; then
  log "[dry-run] record previous release, then atomic symlink switch"
else
  if [ -L "$BASE/current" ]; then
    basename "$(readlink "$BASE/current")" >"$BASE/previous"
  else
    rm -f "$BASE/previous"
  fi
  atomic_link "releases/$tag" "$BASE/current"
  switched=1
fi

step "6/9 restart $SERVICE"
restart_service

step "7/9 health check"
if [ "$DRY_RUN" = 1 ]; then
  log "[dry-run] $HERE/healthcheck.sh"
elif ! HEALTH_RETRIES="${HEALTH_RETRIES:-15}" "$HERE/healthcheck.sh"; then
  log "health check failed: rolling back"
  if [ -f "$BASE/previous" ]; then
    "$HERE/rollback.sh" || die "ROLLBACK FAILED: fix by hand (see docs/PI_SETUP.md)"
    die "release $tag failed its health check; the previous release is back"
  fi
  die "release $tag failed its health check and there is no previous release"
fi

step "8/9 prune old releases (keep $KEEP_RELEASES)"
if [ "$DRY_RUN" = 1 ]; then
  log "[dry-run] remove all but the newest $KEEP_RELEASES releases, never current or previous"
else
  live="$(basename "$(readlink "$BASE/current")")"
  prev="$(tr -d '[:space:]' <"$BASE/previous" 2>/dev/null || true)"
  # shellcheck disable=SC2012 # release names are restricted to [A-Za-z0-9._-]
  ls -1t "$BASE/releases" | tail -n +"$((KEEP_RELEASES + 1))" | while IFS= read -r old; do
    [ "$old" = "$live" ] || [ "$old" = "$prev" ] || {
      log "removing old release $old"
      rm -rf "${BASE:?}/releases/$old"
    }
  done
fi

step "9/9 done"
log "release $tag is live"
