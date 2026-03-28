# Agricultural autonomy package for openpilot-based tractor platform.
# Processes:
#   supervisor_watchdog   — safety interlock and heartbeat manager
#   field_mission_planner — AB-line coverage path generator
#
# Enable by setting the AGRI_MODE environment variable before starting the manager:
#   AGRI_MODE=1 system/manager/manager.py
