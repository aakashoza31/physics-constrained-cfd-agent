#!/usr/bin/env bash
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

: "${GEMINI_API_KEY:?Set GEMINI_API_KEY before running this script}"
OUT="$REPO/demo/runs/nozzle_feedback"
mkdir -p "$OUT"

python scripts/check_environment.py

python scripts/run_nozzle_feedback.py \
  --case A \
  --out "$OUT" \
  --feedback-demo \
  --feedback-first-end-time 0.001 \
  --end-time 0.006 \
  --max-end-time 0.020 \
  --feedback-increment 0.005 \
  --max-iterations 4 \
  --max-diagnostic-requests 2 \
  --require-visuals

for CASE in B C; do
  python scripts/run_nozzle_feedback.py \
    --case "$CASE" \
    --out "$OUT" \
    --end-time 0.006 \
    --max-end-time 0.020 \
    --feedback-increment 0.005 \
    --max-iterations 4 \
    --max-diagnostic-requests 2 \
    --require-visuals
done

python scripts/build_nozzle_campaign_summary.py \
  --root "$OUT" \
  --out "$OUT/CAMPAIGN_SUMMARY.json"

echo "Campaign complete: $OUT"
