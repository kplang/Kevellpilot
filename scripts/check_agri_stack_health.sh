#!/usr/bin/env bash
set -euo pipefail

# Health check for Jetson agricultural stack.
# Verifies:
#  - systemd services status
#  - SocketCAN interface state and bitrate
#  - process presence (manager + bridge)
#  - optional basic CAN traffic sample via candump
#
# Usage:
#   scripts/check_agri_stack_health.sh
#   scripts/check_agri_stack_health.sh can0

IFACE="${1:-can0}"
FAIL=0

pass() { echo "[PASS] $*"; }
warn() { echo "[WARN] $*"; }
fail() { echo "[FAIL] $*"; FAIL=1; }

check_service() {
  local svc="$1"
  if systemctl is-active --quiet "$svc"; then
    pass "service active: ${svc}"
  else
    fail "service inactive: ${svc}"
    systemctl --no-pager --full status "$svc" || true
  fi
}

check_iface() {
  if ip -br link show "$IFACE" >/dev/null 2>&1; then
    local state
    state="$(ip -br link show "$IFACE" | awk '{print $2}')"
    if [[ "$state" == "UP" || "$state" == "UNKNOWN" ]]; then
      pass "interface ${IFACE} exists and state=${state}"
    else
      fail "interface ${IFACE} state=${state}"
    fi

    local details
    details="$(ip -details link show "$IFACE" 2>/dev/null | tr '\n' ' ')"
    if echo "$details" | grep -q "bitrate"; then
      pass "interface ${IFACE} has CAN bitrate configured"
      echo "       $(ip -details link show "$IFACE" | grep -m1 -E 'bitrate|restart-ms' || true)"
    else
      warn "could not confirm CAN bitrate for ${IFACE}"
    fi
  else
    fail "interface ${IFACE} not found"
  fi
}

check_processes() {
  if pgrep -fa "system/manager/manager.py" >/dev/null; then
    pass "manager process running"
  else
    fail "manager process not running"
  fi

  if pgrep -fa "selfdrive.agricultural.jetson_can_bridge" >/dev/null; then
    pass "jetson CAN bridge process running"
  else
    fail "jetson CAN bridge process not running"
  fi
}

check_can_sample() {
  if ! command -v candump >/dev/null 2>&1; then
    warn "candump not installed (install can-utils for bus sampling)"
    return
  fi

  echo "[INFO] sampling CAN bus for 2 seconds on ${IFACE}..."
  set +e
  timeout 2s candump -L "$IFACE" > /tmp/agri_can_sample.log 2>/dev/null
  local rc=$?
  set -e

  if [[ $rc -eq 0 || $rc -eq 124 ]]; then
    if [[ -s /tmp/agri_can_sample.log ]]; then
      pass "observed CAN traffic on ${IFACE}"
      head -n 3 /tmp/agri_can_sample.log | sed 's/^/       /'
    else
      warn "no CAN frames observed in 2s window on ${IFACE}"
    fi
  else
    warn "candump exited with rc=${rc}; skipping traffic assertion"
  fi
}

echo "[INFO] Checking agricultural stack health..."
check_service openpilot-can.service
check_service openpilot-agri.service
check_iface
check_processes
check_can_sample

if [[ "$FAIL" -ne 0 ]]; then
  echo "[RESULT] HEALTH CHECK FAILED"
  exit 1
fi

echo "[RESULT] HEALTH CHECK PASSED"
