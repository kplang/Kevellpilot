"""
Jetson Orin Nano hardware class for openpilot agricultural platform.

Abstracts JetPack-specific APIs behind the HardwareBase interface:
  - Thermal monitoring (L4T thermal zones)
  - Power mode management (nvpmodel)
  - Network type
  - Device identity

JetPack compatibility: 5.x (Ubuntu 20.04, CUDA 11.4) and 6.x (Ubuntu 22.04, CUDA 12.x)
"""

import os
import subprocess
from cereal import log
from openpilot.system.hardware.base import HardwareBase, ThermalConfig, ThermalZone

NetworkType = log.DeviceState.NetworkType

# nvpmodel IDs for Jetson Orin Nano 4GB / 8GB
# Mode 0 = MAXN (all cores, full clocks — use for inference)
# Mode 1 = 10W, Mode 2 = 7W (lower power)
NVPMODEL_MAXN = 0
NVPMODEL_10W  = 1


def _read_file(path: str, default: str = "") -> str:
  try:
    with open(path) as f:
      return f.read().strip()
  except OSError:
    return default


def get_device_type() -> str:
  """Identify exact Jetson Orin module from device-tree compatible string."""
  compatible = _read_file("/proc/device-tree/compatible")
  if "p3767-0003" in compatible or "p3767-0004" in compatible:
    return "jetson_orin_nano_4gb"
  if "p3767-0005" in compatible:
    return "jetson_orin_nano_8gb"
  if "p3767" in compatible:
    return "jetson_orin_nano"
  if "p3701" in compatible or "p3737" in compatible:
    return "jetson_agx_orin"
  if "nvidia" in compatible:
    return "jetson_generic"
  return "jetson_unknown"


class JetsonOrinNano(HardwareBase):
  """
  Hardware backend for NVIDIA Jetson Orin Nano running JetPack 5/6.

  Thermal zones are read from L4T's sysfs interface.
  The names here match what JetPack 6 exposes; JetPack 5 names are similar.
  """

  # L4T thermal zone names for Jetson Orin
  _THERMAL_CONFIG = ThermalConfig(
    cpu=[
      ThermalZone("cpu-thermal"),         # CPU cluster A
    ],
    gpu=[
      ThermalZone("gpu-thermal"),
    ],
    memory=ThermalZone("soc2-thermal"),   # closest to RAM bus
  )

  def get_device_type(self) -> str:
    return get_device_type()

  def get_network_type(self):
    # Jetson Orin Nano has built-in GbE; treat as ethernet
    return NetworkType.ethernet

  def get_thermal_config(self):
    return self._THERMAL_CONFIG

  def get_cpu_temps(self):
    zones = self._THERMAL_CONFIG.cpu or []
    return [z.read() for z in zones]

  def get_gpu_temp(self) -> float:
    zones = self._THERMAL_CONFIG.gpu or []
    return zones[0].read() if zones else 0.0

  # ------------------------------------------------------------------
  # Power management
  # ------------------------------------------------------------------
  def set_power_mode(self, mode: int = NVPMODEL_MAXN) -> bool:
    """Set nvpmodel power mode (requires sudo or passwordless sudo rule)."""
    try:
      subprocess.run(["sudo", "nvpmodel", "-m", str(mode)],
                     check=True, capture_output=True)
      return True
    except (subprocess.CalledProcessError, FileNotFoundError):
      return False

  def get_power_mode(self) -> int:
    try:
      out = subprocess.check_output(["nvpmodel", "-q", "--verbose"],
                                     encoding="utf-8", stderr=subprocess.DEVNULL)
      for line in out.splitlines():
        if "NV Power Mode" in line:
          return int(line.split(":")[-1].strip())
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
      pass
    return -1

  def set_max_performance(self) -> None:
    """Switch to MAXN mode and trigger Jetson clocks maximization."""
    self.set_power_mode(NVPMODEL_MAXN)
    try:
      subprocess.run(["sudo", "jetson_clocks"], check=True, capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
      pass

  # ------------------------------------------------------------------
  # Screen / display (no-op — Jetson Orin Nano has no built-in display)
  # ------------------------------------------------------------------
  def set_screen_brightness(self, percentage: int) -> None:
    pass

  def get_screen_brightness(self) -> int:
    return 0

  def set_display_power(self, on: bool) -> None:
    pass

  # ------------------------------------------------------------------
  # Misc
  # ------------------------------------------------------------------
  def get_imei(self, slot: int) -> str:
    return ""

  def get_serial(self) -> str:
    return _read_file("/proc/device-tree/serial-number")

  def reboot(self, reason: str | None = None) -> None:
    subprocess.run(["sudo", "reboot"])

  def shutdown(self) -> None:
    subprocess.run(["sudo", "shutdown", "now"])
