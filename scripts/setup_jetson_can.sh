#!/usr/bin/env bash
set -euo pipefail

# Configure Jetson SocketCAN interfaces for agricultural testing.
# Usage:
#   sudo scripts/setup_jetson_can.sh                 # can0 @ 250000
#   sudo scripts/setup_jetson_can.sh 500000 can0
#   sudo scripts/setup_jetson_can.sh 250000 can1

BITRATE="${1:-250000}"
IFACE="${2:-can0}"

echo "[setup_jetson_can] configuring ${IFACE} bitrate=${BITRATE}"

# bring down first so type/bitrate can be updated safely
ip link set "${IFACE}" down 2>/dev/null || true
ip link set "${IFACE}" type can bitrate "${BITRATE}" restart-ms 100
ip link set "${IFACE}" txqueuelen 1024
ip link set "${IFACE}" up

echo "[setup_jetson_can] done"
ip -details link show "${IFACE}" | sed -n '1,5p'
