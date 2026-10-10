#!/usr/bin/env bash
# Put the previous release back: point `current` at it, restart, health-check.
#
# deploy.sh records the release it replaced in $BASE/previous. Running rollback.sh twice swaps
# back to the newer release (it records the one it left), which is the roll-forward.
#
# Safe only because migrations are backward compatible (see deploy.sh): the old code must run on
# the new schema. A rollback never restores the database; that is a manual restore from backup.
#
#   rollback.sh [--dry-run]
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$HERE/lib.sh"

[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

[ -f "$BASE/previous" ] || die "no previous release recorded in $BASE/previous"
target="$(tr -d '[:space:]' <"$BASE/previous")"
case "$target" in '' | */* | .*) die "bad release name in $BASE/previous: '$target'" ;; esac
[ -d "$BASE/releases/$target" ] || die "release not found: $BASE/releases/$target"
left=""
[ -L "$BASE/current" ] && left="$(basename "$(readlink "$BASE/current")")"

step "rollback: current -> releases/$target"
if [ "$DRY_RUN" = 1 ]; then
  log "[dry-run] atomic switch of $BASE/current to releases/$target"
else
  atomic_link "releases/$target" "$BASE/current"
  [ -z "$left" ] || printf '%s\n' "$left" >"$BASE/previous"
fi
step "restart $SERVICE"
restart_service
step "health check"
if [ "$DRY_RUN" = 1 ]; then
  log "[dry-run] $HERE/healthcheck.sh"
else
  HEALTH_RETRIES="${HEALTH_RETRIES:-15}" "$HERE/healthcheck.sh" || die "rolled back to $target but the health check still fails"
fi
log "rolled back to $target"
