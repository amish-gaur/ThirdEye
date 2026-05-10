#!/usr/bin/env bash
# Simulate the iPhone half of the identity handoff while the iOS app's
# name/email screen isn't wired yet. Posts to /api/identity, prints the
# 6-character code, and (optionally) waits until the web claims it.
#
# Usage:
#   scripts/sim_phone.sh                                   # defaults
#   scripts/sim_phone.sh "Jane Doe" jane@example.com
#   scripts/sim_phone.sh --watch                           # block until claim
set -euo pipefail

ROUTER="${ROUTER_URL:-http://127.0.0.1:8001}"
NAME="${1:-Aditya Singh}"
EMAIL="${2:-adisin650@gmail.com}"
WATCH=0
[[ "${1:-}" == "--watch" ]] && { WATCH=1; NAME="${2:-Aditya Singh}"; EMAIL="${3:-adisin650@gmail.com}"; }
[[ "${3:-}" == "--watch" || "${4:-}" == "--watch" ]] && WATCH=1

if ! curl -fsS "$ROUTER/health" >/dev/null 2>&1; then
  echo "❌ router not reachable at $ROUTER — is 'make run' up?"
  exit 1
fi

RESP=$(curl -fsS -X POST "$ROUTER/api/identity" \
  -H 'Content-Type: application/json' \
  -d "$(printf '{"name":"%s","email":"%s","device_id":"sim-phone"}' "$NAME" "$EMAIL")")

CODE=$(printf '%s' "$RESP" | python3 -c 'import json,sys;print(json.load(sys.stdin)["code"])')

cat <<EOF

  ┌─────────────────────────────────────────────┐
  │                                             │
  │   ThirdEye sign-in code                     │
  │                                             │
  │            $CODE                            │
  │                                             │
  │   Open http://localhost:5173                │
  │   and type the code on the sign-in screen.  │
  │                                             │
  └─────────────────────────────────────────────┘

EOF

if (( WATCH )); then
  echo "⏳ waiting for web to claim …  (Ctrl+C to stop)"
  while :; do
    STATUS=$(curl -fsS "$ROUTER/api/identity/by-code/$CODE" 2>/dev/null \
      | python3 -c 'import json,sys;print(json.load(sys.stdin).get("status","?"))' 2>/dev/null \
      || echo "lost")
    if [[ "$STATUS" == "claimed" ]]; then
      echo "✅ claimed — you're logged in on the web."
      exit 0
    fi
    if [[ "$STATUS" == "lost" ]]; then
      echo "⚠ code $CODE expired or router went away."
      exit 1
    fi
    sleep 1
  done
fi
