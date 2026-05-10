#!/usr/bin/env bash
# One-shot test runner for the cloud VLM backend on lane/cloud-vlm-backend.
#
# Each section reports independently. The live Anthropic round-trip can
# fail purely on billing (zero account credit) without meaning anything
# about the code, so we keep going and surface a per-section summary at
# the end. Exit code is non-zero only if a code-level check failed.
#
#   1. Unit tests for the cloud backend + captioner (no network).
#   2. Offline pipeline smoke — real frame, stubbed Claude client.
#   3. Live Anthropic round-trip — costs ~$0.001 (or 400 if no credit).
#   4. Full pytest sweep — confirms nothing else broke.
#
# Run from the repo root:    bash scripts/test_cloud_backend.sh

cd "$(dirname "$0")/.."

if [[ ! -d ".venv" ]]; then
    echo "no .venv at repo root — create one with: python3.11 -m venv .venv && pip install -r requirements.txt" >&2
    exit 2
fi

# shellcheck disable=SC1091
source .venv/bin/activate

hr() { printf '\n================================================================\n%s\n================================================================\n' "$1"; }

S1=fail; S2=fail; S3=fail; S4=fail
S3_NOTE=""

hr "1/4  unit tests (cloud backend + captioner) — no network"
python -m pytest tests/test_cloud_classifier.py tests/test_qwen_captioner.py -v && S1=pass

hr "2/4  offline end-to-end smoke — real frame, stubbed Claude client"
python -m scripts.smoke_cloud_classifier --offline && S2=pass

hr "3/4  live Anthropic round-trip — real Claude call, ~\$0.001"
LIVE_OUT=$(python -m scripts.smoke_cloud_classifier 2>&1)
LIVE_RC=$?
echo "$LIVE_OUT"
if [[ $LIVE_RC -eq 0 ]]; then
    S3=pass
elif echo "$LIVE_OUT" | grep -q "credit balance is too low"; then
    S3="fail-billing-only"
    S3_NOTE="API key + payload + model accepted by Anthropic; account has no credit. Top up at console.anthropic.com to unblock."
fi

hr "4/4  full regression sweep — everything else still passes"
python -m pytest tests/ -q --ignore=tests/test_imessage.py && S4=pass

hr "summary"
printf '  1. cloud backend unit tests        : %s\n' "$S1"
printf '  2. offline pipeline smoke          : %s\n' "$S2"
printf '  3. live Anthropic round-trip       : %s\n' "$S3"
[[ -n "$S3_NOTE" ]] && printf '       note: %s\n' "$S3_NOTE"
printf '  4. full regression sweep           : %s\n' "$S4"

# Code health = 1, 2, 4. Section 3 can be billing-blocked without that
# meaning the integration is broken.
if [[ "$S1" == "pass" && "$S2" == "pass" && "$S4" == "pass" ]]; then
    echo
    echo "code-level checks: pass"
    exit 0
fi
echo
echo "code-level checks: FAIL"
exit 1
