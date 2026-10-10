#!/usr/bin/env bash
# Is the app answering? Then, on a Raspberry Pi, is the hardware healthy?
#
# Calls GET /healthz through the Unix socket. Exit 0 only if the app says {"status":"ok"}.
# The power and temperature checks only print warnings: they say why the Pi is struggling but
# must not make a deploy roll back.
#
#   HEALTH_RETRIES   attempts before giving up (default 1; deploy.sh uses more, since the
#                    service needs a few seconds to load the embedding model)
#   HEALTH_INTERVAL  seconds between attempts (default 2)
#   JIFUNZE_HEALTH_URL  use this URL instead of the socket (tests, or a TCP dev server)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$HERE/lib.sh"

retries="${HEALTH_RETRIES:-1}"
interval="${HEALTH_INTERVAL:-2}"

probe() {
  if [ -n "${JIFUNZE_HEALTH_URL:-}" ]; then
    curl -fsS --max-time 5 "$JIFUNZE_HEALTH_URL"
  else
    curl -fsS --max-time 5 --unix-socket "$SOCKET" http://localhost/healthz
  fi
}

ok=0
for ((i = 1; i <= retries; i++)); do
  if body="$(probe 2>/dev/null)" && grep -q '"status" *: *"ok"' <<<"$body"; then
    ok=1
    break
  fi
  [ "$i" -lt "$retries" ] && sleep "$interval"
done
if [ "$ok" != 1 ]; then
  log "health check FAILED after $retries attempt(s)" >&2
  exit 1
fi
log "app: ok"

# Hardware, only where the Raspberry Pi tool exists.
if command -v vcgencmd >/dev/null 2>&1; then
  throttled="$(vcgencmd get_throttled 2>/dev/null | cut -d= -f2 || true)"
  if [ -n "$throttled" ] && [ "$((throttled))" -ne 0 ]; then
    flags=$((throttled))
    [ $((flags & 0x1)) -ne 0 ] && log "WARN: under-voltage right now (check the power supply)"
    [ $((flags & 0x2)) -ne 0 ] && log "WARN: ARM frequency capped right now"
    [ $((flags & 0x4)) -ne 0 ] && log "WARN: throttled right now"
    [ $((flags & 0x8)) -ne 0 ] && log "WARN: soft temperature limit active"
    [ $((flags & 0x10000)) -ne 0 ] && log "WARN: under-voltage has occurred since boot"
    [ $((flags & 0x40000)) -ne 0 ] && log "WARN: throttling has occurred since boot"
  else
    log "power: ok (get_throttled=${throttled:-unknown})"
  fi
  temp="$(vcgencmd measure_temp 2>/dev/null | sed -e "s/temp=//" -e "s/'C//" || true)"
  if [ -n "$temp" ]; then
    log "temperature: ${temp} C"
    if awk -v t="$temp" 'BEGIN { exit !(t >= 80) }'; then
      log "WARN: temperature is 80 C or more; the CPU will throttle"
    fi
  fi
fi
