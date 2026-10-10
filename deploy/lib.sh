#!/usr/bin/env bash
# shellcheck disable=SC2034 # the variables are used by the scripts that source this file
# Shared settings and helpers for the deploy scripts. Sourced, never executed.
#
# Every path and command can be overridden from the environment; the scripts' tests rely on that
# to run against a temporary directory with fake systemctl and health-check commands.

BASE="${JIFUNZE_BASE:-/srv/jifunze}"
ENV_FILE="${JIFUNZE_ENV_FILE:-/etc/jifunze/jifunze.env}"
SERVICE="${JIFUNZE_SERVICE:-jifunze.service}"
SOCKET="${JIFUNZE_SOCKET:-/run/jifunze/app.sock}"
KEEP_RELEASES="${JIFUNZE_KEEP_RELEASES:-5}"
# The one privileged command the deploy user may run (see docs/PI_SETUP.md, sudoers).
read -r -a SYSTEMCTL_CMD <<<"${JIFUNZE_SYSTEMCTL:-sudo systemctl}"

DRY_RUN=0

log() { printf '%s %s\n' "$(date -u +%H:%M:%SZ)" "$*"; }
step() { log "==> $*"; }
die() {
  log "ERROR: $*" >&2
  exit 1
}

# Run a command, or only print it in --dry-run mode.
run() {
  if [ "$DRY_RUN" = 1 ]; then
    log "[dry-run] $*"
  else
    "$@"
  fi
}

# Load the environment file (KEY=value lines) the same way the systemd units do.
load_env() {
  if [ -f "$ENV_FILE" ]; then
    set -a
    # shellcheck source=/dev/null
    . "$ENV_FILE"
    set +a
  fi
}

# Point symlink $2 at $1 in one rename, so there is never a moment with no `current`.
atomic_link() {
  local target=$1 link=$2 tmp
  tmp="${link}.new.$$"
  ln -s "$target" "$tmp"
  # GNU mv (the Pi) has -T; BSD mv (a Mac running the tests) has -h.
  if ! mv -Tf "$tmp" "$link" 2>/dev/null; then
    mv -hf "$tmp" "$link"
  fi
}

restart_service() {
  run "${SYSTEMCTL_CMD[@]}" restart "$SERVICE"
}
