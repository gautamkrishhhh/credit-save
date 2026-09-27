#!/usr/bin/env bash
# The verification loop: unit/integration tests -> boot the real server ->
# drive every screen in a headless browser -> screenshots in ./screenshots.
# Usage: scripts/verify.sh [--loop N]   (repeat N times, stop on first failure)
set -euo pipefail
cd "$(dirname "$0")/.."
ROUNDS=1
[[ "${1:-}" == "--loop" ]] && ROUNDS="${2:-3}"
PORT="${PORT:-8765}"
for round in $(seq 1 "$ROUNDS"); do
  echo "=== verify round $round/$ROUNDS ==="
  python3 -m pytest -q tests
  DB="$(mktemp -d)/verify.db"
  CREDITSAGE_DB="$DB" PORT="$PORT" python3 run.py >/tmp/creditsage-verify.log 2>&1 &
  PID=$!
  trap 'kill $PID 2>/dev/null || true' EXIT
  for _ in $(seq 1 40); do curl -sf "localhost:$PORT/api/health" >/dev/null && break; sleep 0.5; done
  node scripts/e2e.mjs "http://127.0.0.1:$PORT" screenshots
  kill $PID; wait $PID 2>/dev/null || true
  trap - EXIT
done
echo "✅ all verification rounds passed"
