#!/usr/bin/env bash
set -euo pipefail

HOST="127.0.0.1"
PORT="7624"
FOCAL_LENGTH="800"
APERTURE="50"
LIMITING_MAG="18"
NOISE="0"
SKYGLOW="21"
X_SIZE="7"
Y_SIZE="7"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --indi-host) HOST="$2"; shift 2 ;;
    --indi-port) PORT="$2"; shift 2 ;;
    --focal-length) FOCAL_LENGTH="$2"; shift 2 ;;
    --aperture) APERTURE="$2"; shift 2 ;;
    --limiting-mag) LIMITING_MAG="$2"; shift 2 ;;
    --noise) NOISE="$2"; shift 2 ;;
    --skyglow) SKYGLOW="$2"; shift 2 ;;
    --x-size) X_SIZE="$2"; shift 2 ;;
    --y-size) Y_SIZE="$2"; shift 2 ;;
    *)
      echo "Unknown arg: $1"
      exit 2
      ;;
  esac
done

echo "[info] Starting INDI simulators (telescope + ccd)..."
indiserver indi_simulator_telescope indi_simulator_ccd &
INDI_PID=$!

cleanup() {
  echo "[info] Stopping indiserver..."
  kill "$INDI_PID" 2>/dev/null || true
}
trap cleanup EXIT

echo "[info] Waiting for devices..."
sleep 2

echo "[info] Connecting telescope + CCD simulator..."
indi_setprop -h "$HOST" -p "$PORT" "Telescope Simulator.CONNECTION.CONNECT=On"
indi_setprop -h "$HOST" -p "$PORT" "CCD Simulator.CONNECTION.CONNECT=On"

echo "[info] Linking CCD simulator to telescope and setting optics..."
indi_setprop -h "$HOST" -p "$PORT" "CCD Simulator.ACTIVE_DEVICES.ACTIVE_TELESCOPE=Telescope Simulator"
indi_setprop -h "$HOST" -p "$PORT" "CCD Simulator.SCOPE_INFO.FOCAL_LENGTH=$FOCAL_LENGTH"
indi_setprop -h "$HOST" -p "$PORT" "CCD Simulator.SCOPE_INFO.APERTURE=$APERTURE"

echo "[info] Adjusting simulator star settings..."
indi_setprop -h "$HOST" -p "$PORT" "CCD Simulator.SIMULATOR_SETTINGS.SIM_LIMITINGMAG=$LIMITING_MAG"
indi_setprop -h "$HOST" -p "$PORT" "CCD Simulator.SIMULATOR_SETTINGS.SIM_NOISE=$NOISE"
indi_setprop -h "$HOST" -p "$PORT" "CCD Simulator.SIMULATOR_SETTINGS.SIM_SKYGLOW=$SKYGLOW"
indi_setprop -h "$HOST" -p "$PORT" "CCD Simulator.SIMULATOR_SETTINGS.SIM_XSIZE=$X_SIZE"
indi_setprop -h "$HOST" -p "$PORT" "CCD Simulator.SIMULATOR_SETTINGS.SIM_YSIZE=$Y_SIZE"

echo "[info] Saving CCD simulator config..."
indi_setprop -h "$HOST" -p "$PORT" "CCD Simulator.CONFIG_PROCESS.CONFIG_SAVE=On"

echo "[info] INDI simulators configured. Leave this terminal open while using astrolabe."
wait "$INDI_PID"
