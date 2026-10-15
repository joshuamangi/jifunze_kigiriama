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
# The only privileged commands the deploy user may run: `systemctl restart` and
# `systemctl reset-failed` on this one service (see docs/PI_SETUP.md, sudoers). -n: never wait for a
# password, so a missing sudo rule fails at once instead of hanging a deploy.
read -r -a SYSTEMCTL_CMD <<<"${JIFUNZE_SYSTEMCTL:-sudo -n systemctl}"

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
  # A release that crashes on start makes systemd give up after StartLimitBurst tries ("start
  # request repeated too quickly") and refuse every later start, including the rollback's. Clearing
  # that state first is harmless on a healthy unit. Not fatal: an older sudo rule may lack it.
  run "${SYSTEMCTL_CMD[@]}" reset-failed "$SERVICE" || log "note: could not reset-failed $SERVICE"
  run "${SYSTEMCTL_CMD[@]}" restart "$SERVICE"
}
