#!/usr/bin/env bash
set -euo pipefail

# Install Jetson autostart services:
#   - openpilot-can.service   : configures SocketCAN at boot
#   - openpilot-agri.service  : runs openpilot manager in agri mode
#
# Usage:
#   sudo scripts/systemd/install_agri_autostart.sh [run_user] [run_group]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

RUN_USER="${1:-${SUDO_USER:-$USER}}"
RUN_GROUP="${2:-${RUN_USER}}"

CAN_UNIT_SRC="${SCRIPT_DIR}/openpilot-can.service"
AGRI_UNIT_SRC="${SCRIPT_DIR}/openpilot-agri.service"
HEALTH_UNIT_SRC="${SCRIPT_DIR}/openpilot-agri-health.service"
HEALTH_TIMER_SRC="${SCRIPT_DIR}/openpilot-agri-health.timer"
CAN_UNIT_DST="/etc/systemd/system/openpilot-can.service"
AGRI_UNIT_DST="/etc/systemd/system/openpilot-agri.service"
HEALTH_UNIT_DST="/etc/systemd/system/openpilot-agri-health.service"
HEALTH_TIMER_DST="/etc/systemd/system/openpilot-agri-health.timer"

if [[ ! -f "${CAN_UNIT_SRC}" || ! -f "${AGRI_UNIT_SRC}" || ! -f "${HEALTH_UNIT_SRC}" || ! -f "${HEALTH_TIMER_SRC}" ]]; then
  echo "[install_agri_autostart] unit template missing"
  exit 1
fi

# Render templates
sed -e "s|__REPO_DIR__|${REPO_DIR}|g" "${CAN_UNIT_SRC}" > "${CAN_UNIT_DST}"
sed -e "s|__REPO_DIR__|${REPO_DIR}|g" \
    -e "s|__RUN_USER__|${RUN_USER}|g" \
    -e "s|__RUN_GROUP__|${RUN_GROUP}|g" \
    "${AGRI_UNIT_SRC}" > "${AGRI_UNIT_DST}"
sed -e "s|__REPO_DIR__|${REPO_DIR}|g" \
  -e "s|__RUN_USER__|${RUN_USER}|g" \
  -e "s|__RUN_GROUP__|${RUN_GROUP}|g" \
  "${HEALTH_UNIT_SRC}" > "${HEALTH_UNIT_DST}"
cp "${HEALTH_TIMER_SRC}" "${HEALTH_TIMER_DST}"

systemctl daemon-reload
systemctl enable openpilot-can.service
systemctl enable openpilot-agri.service
systemctl enable openpilot-agri-health.timer

echo "[install_agri_autostart] installed"
echo "  user=${RUN_USER} group=${RUN_GROUP}"
echo "  units: ${CAN_UNIT_DST}, ${AGRI_UNIT_DST}, ${HEALTH_UNIT_DST}, ${HEALTH_TIMER_DST}"
echo "Next: sudo systemctl start openpilot-can.service && sudo systemctl start openpilot-agri.service"
echo "Then: ${REPO_DIR}/scripts/check_agri_stack_health.sh can0"
echo "Timer: sudo systemctl start openpilot-agri-health.timer"
