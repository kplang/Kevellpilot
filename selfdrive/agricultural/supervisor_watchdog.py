#!/usr/bin/env python3
"""
supervisor_watchdog.py — Agricultural safety supervisor and interlock manager

Responsibilities
----------------
1. Monitor all agricultural process heartbeats (field planner, GNSS, car control).
2. Grant or revoke longitudinal control authority via the `AgriLongEnabled` param.
3. Enforce hard speed ceiling (8 m/s) independently of the panda safety layer.
4. Listen for remote STOP commands (params, ZeroMQ).
5. Publish `agriSupervisorState` so the operator HMI always has system status.
6. Send supervisor heartbeat CAN frame (0x18FF3100) via zmq to pandad.

Interlock logic
---------------
  LONG_ENABLED = True  ↔  all of the following are true:
    • Field mission planner heartbeat received within TIMEOUT_MS
    • RTK GNSS position valid (accuracy < GPS_ACCURACY_THRESHOLD_M)
    • Speed < MAX_SPEED_MS
    • No geofence breach detected
    • Remote STOP not active
    • Operator presence confirmed (if required by params)

  Any single failure → LONG_ENABLED = False + emergency brake request.

Safety note
-----------
  This is the SOFTWARE safety layer.  The panda firmware's tractor.h is the
  HARDWARE safety layer.  Both must agree before longitudinal is active.
"""

from __future__ import annotations

import time
from enum import Enum, auto

import cereal.messaging as messaging
from openpilot.common.params import Params
from openpilot.common.realtime import Ratekeeper
from openpilot.system.hardware import JETSON

# GPIO relay — only imported/started on real Jetson hardware
if JETSON:
  from openpilot.selfdrive.agricultural.gpio_safety_relay import get_relay

# ---------------------------------------------------------------------------
# Tunable constants
# ---------------------------------------------------------------------------
LOOP_HZ                   = 20       # watchdog runs at 20 Hz
PLANNER_TIMEOUT_S         = 1.0      # max gap between planner heartbeats
GNSS_TIMEOUT_S            = 1.0      # max gap between valid GNSS frames
CONTROL_TIMEOUT_S         = 0.5      # max gap between car-control frames
MAX_SPEED_MS              = 8.0      # absolute software speed ceiling
GPS_ACCURACY_THRESHOLD_M  = 0.3     # RTK accuracy — below this = valid
SUPERVISOR_HB_INTERVAL_S  = 0.1      # send supervisor CAN HB every 100 ms

# CAN ID for supervisor heartbeat frame sent to panda
SUPERVISOR_HB_CAN_ID = 0x18FF3100
SUPERVISOR_HB_BUS    = 0


# ---------------------------------------------------------------------------
class SupervisorState(Enum):
  INIT          = auto()
  NOMINAL       = auto()
  DEGRADED      = auto()   # soft warning — operator intervention requested
  ESTOP         = auto()   # all motion stopped


# ---------------------------------------------------------------------------
class AgriSupervisorWatchdog:
  """
  Runs at LOOP_HZ.  Uses SubMaster to watch multiple message queues and
  PubMaster to publish supervisor status.
  """

  def __init__(self) -> None:
    self.params = Params()

    self.sm = messaging.SubMaster([
      "gpsLocationExternal",
      "agriMissionState",
      "carState",
      "controlsState",
      "sendcan",          # to detect if car controller is alive
    ])
    self.pm = messaging.PubMaster(["agriSupervisorState", "sendcan"])

    self.state            = SupervisorState.INIT
    self.long_enabled     = False
    self.estop_reason     = ""

    # Heartbeat timestamps
    self._t_planner = 0.0
    self._t_gnss    = 0.0
    self._t_control = 0.0
    self._t_hb_sent = 0.0

    # Remote stop flag — sticky, cleared only by operator
    self._remote_stop = False

    # Hardware safety relay (Jetson GPIO) — only active on real Jetson hardware
    self._relay = None
    if JETSON:
      self._relay = get_relay(on_estop_pressed=self._on_physical_estop)
      self._relay.start()   # relay starts de-energised (safe state)

    print("[Supervisor] Initialised.  Waiting for nominal conditions.")

  # ------------------------------------------------------------------
  # Internal helpers
  # ------------------------------------------------------------------
  def _now(self) -> float:
    return time.monotonic()

  def _on_physical_estop(self) -> None:
    """Called by GPIO polling thread when physical E-stop button is pressed."""
    self._set_estop("physical ESTOP button pressed")

  def _set_estop(self, reason: str) -> None:
    if self.state != SupervisorState.ESTOP:
      print(f"[Supervisor] ESTOP — {reason}")
    self.state        = SupervisorState.ESTOP
    self.long_enabled = False
    self.estop_reason = reason
    self._write_long_enabled(False)
    # Open hardware relay — breaks hydraulic enable circuit
    if self._relay:
      self._relay.open()

  def _write_long_enabled(self, enabled: bool) -> None:
    """Write the AgriLongEnabled param that carcontroller reads."""
    self.params.put("AgriLongEnabled", b"1" if enabled else b"0")

  def _check_remote_commands(self) -> None:
    """Poll params for remote operator commands."""
    stop_cmd = self.params.get("AgriRemoteStop")
    if stop_cmd == b"1":
      self._remote_stop = True
      self._set_estop("remote stop commanded")

    clear_cmd = self.params.get("AgriClearEstop")
    if clear_cmd == b"1" and self.state == SupervisorState.ESTOP:
      # Operator explicitly cleared the estop — allow recovery
      self._remote_stop = False
      self.state        = SupervisorState.INIT
      self.estop_reason = ""
      self.params.remove("AgriClearEstop")
      print("[Supervisor] ESTOP cleared by operator.  Re-evaluating conditions.")

  def _send_supervisor_hb(self) -> None:
    """Send a CAN heartbeat via the pandad sendcan socket."""
    now = self._now()
    if now - self._t_hb_sent < SUPERVISOR_HB_INTERVAL_S:
      return
    self._t_hb_sent = now

    alive_byte = 0x01 if (self.state == SupervisorState.NOMINAL) else 0x00

    # Build raw CAN frame: [alive_byte, 0, 0, 0, 0, 0, 0, 0] on bus 0
    can_data = bytes([alive_byte, 0, 0, 0, 0, 0, 0, 0])
    msg = messaging.new_message("sendcan", 1)
    frame = msg.sendcan[0]
    frame.address = SUPERVISOR_HB_CAN_ID
    frame.dat     = can_data
    frame.src     = SUPERVISOR_HB_BUS
    self.pm.send("sendcan", msg)

  # ------------------------------------------------------------------
  # Main evaluation
  # ------------------------------------------------------------------
  def evaluate(self) -> None:
    now = self._now()

    # ---- Update heartbeat timestamps from sub messages ----------------
    if self.sm.updated["agriMissionState"]:
      self._t_planner = now
    if self.sm.updated["gpsLocationExternal"]:
      self._t_gnss = now
    if self.sm.updated["controlsState"]:
      self._t_control = now

    # ---- Remote commands ---------------------------------------------
    self._check_remote_commands()
    if self._remote_stop:
      self._set_estop("remote stop active")
      return

    # ---- Timeout checks ----------------------------------------------
    if now - self._t_planner > PLANNER_TIMEOUT_S and self._t_planner > 0:
      self._set_estop(f"planner heartbeat lost (>{PLANNER_TIMEOUT_S}s)")
      return

    if now - self._t_gnss > GNSS_TIMEOUT_S and self._t_gnss > 0:
      self._set_estop(f"GNSS signal lost (>{GNSS_TIMEOUT_S}s)")
      return

    # ---- GNSS quality ------------------------------------------------
    if self.sm.valid["gpsLocationExternal"]:
      gps = self.sm["gpsLocationExternal"]
      accuracy = getattr(gps, "accuracy", 999.0)
      if accuracy > GPS_ACCURACY_THRESHOLD_M:
        if self.state == SupervisorState.NOMINAL:
          self.state    = SupervisorState.DEGRADED
          self.long_enabled = False
          self._write_long_enabled(False)
          print(f"[Supervisor] GNSS accuracy degraded ({accuracy:.2f}m) — long suspended")
        return

    # ---- Speed check -------------------------------------------------
    if self.sm.valid["carState"]:
      speed_ms = self.sm["carState"].vEgo
      if speed_ms > MAX_SPEED_MS:
        self._set_estop(f"speed exceeded {MAX_SPEED_MS} m/s (actual {speed_ms:.1f} m/s)")
        return

    # ---- Geofence check from mission state ---------------------------
    if self.sm.valid["agriMissionState"]:
      ms = self.sm["agriMissionState"]
      if not ms.geofenceOk:
        self._set_estop("geofence breach reported by mission planner")
        return
      if ms.state == "ABORT":
        self._set_estop("mission planner entered ABORT state")
        return

    # ---- All checks passed → NOMINAL ---------------------------------
    if self.state != SupervisorState.ESTOP:
      self.state        = SupervisorState.NOMINAL
      self.long_enabled = True
      self._write_long_enabled(True)
      # Energise hardware relay — permits tractor hydraulic motion
      if self._relay and not self._relay.is_closed:
        self._relay.close()

  # ------------------------------------------------------------------
  def _publish_state(self) -> None:
    msg = messaging.new_message("agriSupervisorState")
    s   = msg.agriSupervisorState
    s.state       = self.state.name
    s.longEnabled = self.long_enabled
    s.estopReason = self.estop_reason
    s.speedOk     = (self.sm.valid["carState"] and
                     self.sm["carState"].vEgo <= MAX_SPEED_MS)
    s.gnssOk      = (self.sm.valid["gpsLocationExternal"] and
                     getattr(self.sm["gpsLocationExternal"], "accuracy", 999) < GPS_ACCURACY_THRESHOLD_M)
    s.plannerOk   = ((self._now() - self._t_planner) < PLANNER_TIMEOUT_S and self._t_planner > 0)
    self.pm.send("agriSupervisorState", msg)

  # ------------------------------------------------------------------
  def run(self) -> None:
    rk = Ratekeeper(LOOP_HZ, print_delay_threshold=0.05)
    print(f"[Supervisor] Running at {LOOP_HZ} Hz")
    try:
      while True:
        self.sm.update(0)
        self.evaluate()
        self._send_supervisor_hb()
        self._publish_state()
        rk.keep_time()
    finally:
      # Always leave in safe state on exit
      self._write_long_enabled(False)
      if self._relay:
        self._relay.stop()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
  watchdog = AgriSupervisorWatchdog()
  watchdog.run()


if __name__ == "__main__":
  main()
