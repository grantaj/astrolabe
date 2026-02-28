#!/usr/bin/env bash
set -euo pipefail

cleanup() {
  if [[ -n "${INDI_PID:-}" ]]; then
    kill "$INDI_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

echo "[integration] Starting indiserver with telescope simulator..."
indiserver indi_simulator_telescope indi_simulator_ccd &
INDI_PID=$!

echo "[integration] Waiting for INDI device to become available..."
ready=false
for _ in $(seq 1 30); do
  if indi_getprop -1 -t 1 "Telescope Simulator.CONNECTION.CONNECT" 2>/dev/null \
     | grep -q "Off"; then
    ready=true
    break
  fi
  sleep 0.5
done

if [[ "$ready" != "true" ]]; then
  echo "[integration] ERROR: Telescope Simulator did not appear within 15 seconds"
  exit 1
fi

echo "[integration] INDI simulator ready."
echo "[integration] Running: uv run pytest $*"
exec uv run pytest "$@"
