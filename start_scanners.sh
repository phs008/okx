#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

cd "$ROOT_DIR"

stop_existing() {
  local label="$1"
  local command="$2"
  local pids

  pids="$(pgrep -f "$command" || true)"
  if [[ -z "$pids" ]]; then
    return
  fi

  printf 'Stopping existing %s daemon pid(s): %s\n' "$label" "$(tr '\n' ' ' <<<"$pids")"
  kill $pids

  for _ in {1..10}; do
    if ! pgrep -f "$command" >/dev/null; then
      return
    fi
    sleep 1
  done

  pids="$(pgrep -f "$command" || true)"
  if [[ -n "$pids" ]]; then
    printf 'Force stopping %s daemon pid(s): %s\n' "$label" "$(tr '\n' ' ' <<<"$pids")"
    kill -9 $pids
  fi
}

stop_existing "RSI/VWMA" "python[[:digit:].]* -m okx_scanner daemon"
stop_existing "Signal" "python[[:digit:].]* -m okx_scanner power-daemon"

nohup setsid "$PYTHON_BIN" -m okx_scanner daemon > rsi_scanner.log 2>&1 < /dev/null &
RSI_PID=$!

nohup setsid "$PYTHON_BIN" -m okx_scanner power-daemon > signal_scanner.log 2>&1 < /dev/null &
SIGNAL_PID=$!

sleep 2

if ! kill -0 "$RSI_PID" 2>/dev/null; then
  printf 'RSI/VWMA daemon failed to stay running. Recent log:\n' >&2
  tail -n 20 rsi_scanner.log >&2
  exit 1
fi

if ! kill -0 "$SIGNAL_PID" 2>/dev/null; then
  printf 'Signal daemon failed to stay running. Recent log:\n' >&2
  tail -n 20 signal_scanner.log >&2
  exit 1
fi

printf 'RSI/VWMA daemon started pid=%s log=%s\n' "$RSI_PID" "$ROOT_DIR/rsi_scanner.log"
printf 'Signal daemon started pid=%s log=%s\n' "$SIGNAL_PID" "$ROOT_DIR/signal_scanner.log"
