"""
gpio_safety_relay.py — Hardware safety relay control for Jetson Orin Nano

Drives a physical safety relay connected to Jetson's 40-pin GPIO header.
The relay breaks the tractor's hydraulic enable circuit when de-energised,
providing a hardware-level emergency stop independent of all software.

Pin assignment (default, override via env vars or params)
---------------------------------------------------------
  AGRI_RELAY_PIN=18   — Relay coil drive (high = relay closed = system enabled)
  AGRI_ESTOP_PIN=16   — Physical ESTOP button input (active LOW, normally closed)

Wiring notes
------------
  GPIO18 → Optocoupler → Relay coil → 12V relay (normally-open contacts)
  Relay NC contacts in series with John Deere "Implement Enable" CAN signal bypass

  The relay should be wired FAIL-SAFE:
    - Relay de-energised (GPIO LOW, no power) = tractor motion disabled
    - Relay energised (GPIO HIGH) = normal operation allowed

Installation
------------
  JetPack includes Jetson.GPIO automatically.
  Also install: pip install Jetson.GPIO
  Add user to gpio group: sudo usermod -aG gpio $USER

  The GPIO library uses BCM (Broadcom) pin numbers by default.
  The default pins (18, 16) refer to BOARD numbering on the 40-pin header.
  Set JETSON_GPIO_MODE=BOARD (default) or JETSON_GPIO_MODE=BCM.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Callable, Optional

# Try to import Jetson.GPIO; fall back to a software stub on non-Jetson hosts.
try:
  import Jetson.GPIO as GPIO
  _REAL_GPIO = True
except (ImportError, RuntimeError):
  GPIO = None          # type: ignore[assignment]
  _REAL_GPIO = False

# ---- Configuration (override with env vars) ----------------------------
_RELAY_PIN  = int(os.getenv("AGRI_RELAY_PIN",  "18"))   # 40-pin BOARD number
_ESTOP_PIN  = int(os.getenv("AGRI_ESTOP_PIN",  "16"))   # 40-pin BOARD number
_POLL_HZ    = int(os.getenv("AGRI_GPIO_HZ",    "50"))   # button poll rate


class SafetyRelay:
  """
  Controls a normally-open safety relay on Jetson GPIO.

  Thread-safe: relay_close() / relay_open() can be called from any thread.
  Starts an internal polling thread for the physical E-stop button.

  Usage
  -----
    relay = SafetyRelay(on_estop_pressed=handle_estop)
    relay.start()
    relay.close()   # energise relay — system enabled
    ...
    relay.open()    # de-energise relay — system disabled
    relay.stop()
  """

  def __init__(self, on_estop_pressed: Optional[Callable[[], None]] = None) -> None:
    self._on_estop   = on_estop_pressed
    self._lock       = threading.Lock()
    self._relay_on   = False
    self._running    = False
    self._poll_thread: Optional[threading.Thread] = None
    self._available  = _REAL_GPIO

    if not self._available:
      print("[GPIO] Jetson.GPIO not available — relay running in stub mode")

  # ------------------------------------------------------------------
  def start(self) -> None:
    """Initialise GPIO and start the button polling thread."""
    if self._available:
      GPIO.setmode(GPIO.BOARD)
      GPIO.setup(_RELAY_PIN, GPIO.OUT, initial=GPIO.LOW)   # safe default: relay open
      GPIO.setup(_ESTOP_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)  # NC button

    self._running = True
    self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
    self._poll_thread.start()
    print(f"[GPIO] SafetyRelay started. Relay pin={_RELAY_PIN}, ESTOP pin={_ESTOP_PIN}")

  def stop(self) -> None:
    """De-energise relay and clean up GPIO."""
    self._running = False
    self.open()    # force safe state
    if self._poll_thread:
      self._poll_thread.join(timeout=2)
    if self._available:
      GPIO.cleanup()
    print("[GPIO] SafetyRelay stopped and GPIO cleaned up")

  # ------------------------------------------------------------------
  def close(self) -> None:
    """Energise relay — system ENABLED (motion permitted)."""
    with self._lock:
      self._relay_on = True
      if self._available:
        GPIO.output(_RELAY_PIN, GPIO.HIGH)

  def open(self) -> None:
    """De-energise relay — system DISABLED (motion blocked)."""
    with self._lock:
      self._relay_on = False
      if self._available:
        GPIO.output(_RELAY_PIN, GPIO.LOW)

  @property
  def is_closed(self) -> bool:
    with self._lock:
      return self._relay_on

  # ------------------------------------------------------------------
  def _poll_loop(self) -> None:
    """
    Poll the physical ESTOP button at _POLL_HZ.
    Button is normally-closed → GPIO HIGH = OK, GPIO LOW = ESTOP pressed.
    """
    interval = 1.0 / _POLL_HZ
    prev_state = True   # assume OK at start

    while self._running:
      if self._available:
        state = bool(GPIO.input(_ESTOP_PIN))
      else:
        state = True   # stub: always OK

      # Falling edge: button pressed (NC opened → LOW)
      if prev_state and not state:
        print("[GPIO] Physical ESTOP button pressed — forcing relay OPEN")
        self.open()
        if self._on_estop:
          try:
            self._on_estop()
          except Exception as exc:
            print(f"[GPIO] on_estop callback error: {exc}")

      prev_state = state
      time.sleep(interval)


# ---- Module-level singleton ----------------------------------------
_relay: Optional[SafetyRelay] = None


def get_relay(on_estop_pressed: Optional[Callable[[], None]] = None) -> SafetyRelay:
  """Return (and lazily create) the module-level SafetyRelay singleton."""
  global _relay
  if _relay is None:
    _relay = SafetyRelay(on_estop_pressed=on_estop_pressed)
  return _relay
