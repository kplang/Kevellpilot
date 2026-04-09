#!/usr/bin/env python3
"""
jetson_can_bridge.py

SocketCAN bridge for Jetson-based agricultural deployments.

Flow:
- openpilot publishes actuator commands on `sendcan`
- this bridge forwards them to Linux SocketCAN interfaces (can0/can1)
- received SocketCAN frames are published back to openpilot `can`

Notes:
- This is intended for Jetson bring-up and supervised testing.
- Panda safety remains the preferred production safety path.
"""

from __future__ import annotations

import os
import select
import socket
import struct
import time
from typing import List, Tuple

import cereal.messaging as messaging
from openpilot.selfdrive.pandad.pandad_api_impl import can_capnp_to_list, can_list_to_can_capnp

# Linux CAN raw frame: can_id(u32), can_dlc(u8), pad(3), data(8)
_CAN_FRAME_FMT = "=IB3x8s"
_CAN_FRAME_SIZE = struct.calcsize(_CAN_FRAME_FMT)

# Linux SocketCAN flags
CAN_EFF_FLAG = 0x80000000  # Extended frame format flag
CAN_RTR_FLAG = 0x40000000
CAN_ERR_FLAG = 0x20000000
CAN_SFF_MASK = 0x000007FF
CAN_EFF_MASK = 0x1FFFFFFF


def _bind_can(ifname: str) -> socket.socket:
  s = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
  s.bind((ifname,))
  s.setblocking(False)
  return s


def _encode_can_frame(addr: int, dat: bytes) -> bytes:
  is_extended = addr > CAN_SFF_MASK
  can_id = (addr & (CAN_EFF_MASK if is_extended else CAN_SFF_MASK)) | (CAN_EFF_FLAG if is_extended else 0)
  dlc = min(len(dat), 8)
  payload = dat[:8].ljust(8, b"\x00")
  return struct.pack(_CAN_FRAME_FMT, can_id, dlc, payload)


def _decode_can_frame(raw: bytes) -> Tuple[int, bytes]:
  can_id_raw, dlc, payload = struct.unpack(_CAN_FRAME_FMT, raw)

  # ignore error/RTR frames for now
  if can_id_raw & (CAN_ERR_FLAG | CAN_RTR_FLAG):
    return -1, b""

  if can_id_raw & CAN_EFF_FLAG:
    addr = can_id_raw & CAN_EFF_MASK
  else:
    addr = can_id_raw & CAN_SFF_MASK

  return addr, payload[:dlc]


def main() -> None:
  can_ifaces = os.getenv("AGRI_CAN_IFACES", "can0,can1")
  iface_list = [i.strip() for i in can_ifaces.split(",") if i.strip()]

  sockets: List[socket.socket] = []
  sock_to_bus: dict[socket.socket, int] = {}
  for i, ifname in enumerate(iface_list):
    try:
      s = _bind_can(ifname)
      sockets.append(s)
      sock_to_bus[s] = i
      print(f"[can_bridge] Bound {ifname} as bus {i}")
    except OSError as e:
      print(f"[can_bridge] WARN: failed to bind {ifname}: {e}")

  if not sockets:
    raise RuntimeError("No SocketCAN interfaces available. Set AGRI_CAN_IFACES and bring interfaces up.")

  sendcan_sock = messaging.sub_sock("sendcan", conflate=False)
  can_pub = messaging.pub_sock("can")

  while True:
    # 1) Forward openpilot sendcan -> SocketCAN
    send_msgs = messaging.drain_sock_raw(sendcan_sock, wait_for_one=False)
    if send_msgs:
      for _, frames in can_capnp_to_list(send_msgs, msgtype="sendcan"):
        for addr, dat, src in frames:
          if src >= len(sockets):
            continue
          try:
            sockets[src].send(_encode_can_frame(addr, dat))
          except OSError:
            pass

    # 2) Forward SocketCAN -> openpilot can
    readable, _, _ = select.select(sockets, [], [], 0.01)
    rx_frames: List[Tuple[int, bytes, int]] = []
    for s in readable:
      while True:
        try:
          raw = s.recv(_CAN_FRAME_SIZE)
        except BlockingIOError:
          break
        except OSError:
          break

        if len(raw) < _CAN_FRAME_SIZE:
          break

        addr, dat = _decode_can_frame(raw)
        if addr >= 0:
          rx_frames.append((addr, dat, sock_to_bus[s]))

    if rx_frames:
      can_pub.send(can_list_to_can_capnp(rx_frames, msgtype="can", valid=True))

    time.sleep(0.001)


if __name__ == "__main__":
  main()
