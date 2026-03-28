#!/usr/bin/env bash
set -euo pipefail

# Launch openpilot agricultural stack on Jetson.
# Expected to be run by systemd service.

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_DIR}"

# Activate project environment
source "${REPO_DIR}/.venv/bin/activate"

# Defaults can be overridden by service environment or drop-in.
export AGRI_MODE="${AGRI_MODE:-1}"
export AGRI_SOCKETCAN="${AGRI_SOCKETCAN:-1}"
export AGRI_CAN_IFACES="${AGRI_CAN_IFACES:-can0,can1}"

if [[ "${AGRI_DISABLE_PANDAD:-0}" == "1" ]]; then
  export AGRI_DISABLE_PANDAD=1
fi

exec python system/manager/manager.py
