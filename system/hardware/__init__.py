import os
from typing import cast

from openpilot.system.hardware.base import HardwareBase
from openpilot.system.hardware.tici.hardware import Tici
from openpilot.system.hardware.pc.hardware import Pc
from openpilot.system.hardware.jetson.hardware import JetsonOrinNano

TICI  = os.path.isfile('/TICI')
AGNOS = os.path.isfile('/AGNOS')

def _is_jetson() -> bool:
  if os.path.isfile('/JETSON'):
    return True
  try:
    with open('/proc/device-tree/compatible') as f:
      return 'nvidia' in f.read()
  except OSError:
    return False

JETSON = _is_jetson()

# PC = True only on a plain Linux/macOS development machine
PC = not TICI and not JETSON

if TICI:
  HARDWARE = cast(HardwareBase, Tici())
elif JETSON:
  HARDWARE = cast(HardwareBase, JetsonOrinNano())
else:
  HARDWARE = cast(HardwareBase, Pc())
