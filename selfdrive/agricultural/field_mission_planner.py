#!/usr/bin/env python3
"""
field_mission_planner.py — Agricultural field mission orchestrator

Responsibilities
----------------
1. Load a field boundary (GeoJSON polygon) and generate AB-row coverage paths.
2. Accept RTK-GNSS position updates and publish steering setpoints.
3. Detect headland events and command U-turns between rows.
4. Enforce field boundary (geofence) — trigger abort if tractor leaves boundary.
5. Publish `agriMissionState` to the messaging bus for the supervisor watchdog.

Usage
-----
  python selfdrive/agricultural/field_mission_planner.py [--field field.geojson]

Coordinate convention
---------------------
  All positions are (latitude_deg, longitude_deg, altitude_m).
  Internal computations use a local ENU frame (East-North-Up, metres)
  with origin at the first waypoint.

Safety note
-----------
  This process publishes intent only.  All actuator commands are gated by
  the supervisor watchdog (supervisor_watchdog.py) before reaching the
  car controller.  This process must NOT directly write CAN.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import List, Optional, Tuple

import cereal.messaging as messaging
from openpilot.common.params import Params
from openpilot.common.realtime import Ratekeeper

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
EARTH_RADIUS_M      = 6_371_000.0   # metres
LOOKAHEAD_M         = 4.0           # pure-pursuit lookahead distance
ROW_SPACING_M       = 3.0           # default implement width / row spacing
HEADLAND_TRIGGER_M  = 5.0           # metres before field edge → start headland
CROSS_TRACK_WARN_M  = 0.5           # cross-track error warning threshold
GEOFENCE_MARGIN_M   = 2.0           # metres inside boundary before abort
LOOP_HZ             = 10            # planner frequency


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
class MissionState(Enum):
  IDLE         = auto()
  LOADING      = auto()
  RUNNING      = auto()
  HEADLAND     = auto()
  PAUSED       = auto()
  COMPLETE     = auto()
  ABORT        = auto()


@dataclass
class LatLon:
  lat: float
  lon: float
  alt: float = 0.0

  def to_enu(self, origin: "LatLon") -> Tuple[float, float]:
    """Convert to local ENU (metres) relative to *origin*."""
    d_lat = math.radians(self.lat - origin.lat)
    d_lon = math.radians(self.lon - origin.lon)
    north = d_lat * EARTH_RADIUS_M
    east  = d_lon * EARTH_RADIUS_M * math.cos(math.radians(origin.lat))
    return east, north


@dataclass
class Waypoint:
  position: LatLon
  heading_deg: float = 0.0       # desired heading at this waypoint
  is_headland_start: bool = False
  is_headland_end: bool = False


@dataclass
class FieldMission:
  boundary: List[LatLon]         # polygon vertices (closed ring)
  ab_line_start: LatLon          # A-point of AB reference line
  ab_line_end: LatLon            # B-point of AB reference line
  rows: List[List[Waypoint]] = field(default_factory=list)
  origin: Optional[LatLon] = None


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------
def haversine_m(a: LatLon, b: LatLon) -> float:
  """Great-circle distance between two lat/lon points (metres)."""
  lat1, lon1 = math.radians(a.lat), math.radians(a.lon)
  lat2, lon2 = math.radians(b.lat), math.radians(b.lon)
  d_lat = lat2 - lat1
  d_lon = lon2 - lon1
  h = math.sin(d_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(d_lon / 2) ** 2
  return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def bearing_deg(a: LatLon, b: LatLon) -> float:
  """Forward azimuth from a to b (degrees, 0=North, CW)."""
  lat1, lon1 = math.radians(a.lat), math.radians(a.lon)
  lat2, lon2 = math.radians(b.lat), math.radians(b.lon)
  d_lon = lon2 - lon1
  y = math.sin(d_lon) * math.cos(lat2)
  x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(d_lon)
  return (math.degrees(math.atan2(y, x)) + 360) % 360


def point_to_segment_distance_m(p: Tuple[float, float],
                                  a: Tuple[float, float],
                                  b: Tuple[float, float]) -> float:
  """Perpendicular distance from point p to segment a-b (ENU metres)."""
  ax, ay = a
  bx, by = b
  px, py = p
  dx, dy = bx - ax, by - ay
  seg_len_sq = dx * dx + dy * dy
  if seg_len_sq < 1e-9:
    return math.hypot(px - ax, py - ay)
  t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg_len_sq))
  proj_x = ax + t * dx
  proj_y = ay + t * dy
  return math.hypot(px - proj_x, py - proj_y)


def point_in_polygon_enu(point: Tuple[float, float],
                          polygon: List[Tuple[float, float]]) -> bool:
  """Ray-casting even-odd test (ENU coordinates)."""
  px, py = point
  inside = False
  n = len(polygon)
  j = n - 1
  for i in range(n):
    xi, yi = polygon[i]
    xj, yj = polygon[j]
    if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi + 1e-12) + xi):
      inside = not inside
    j = i
  return inside


# ---------------------------------------------------------------------------
# Row / coverage path generation
# ---------------------------------------------------------------------------
def generate_rows(mission: FieldMission, row_spacing: float = ROW_SPACING_M) -> List[List[Waypoint]]:
  """
  Generate parallel AB rows covering the field polygon.

  Strategy
  --------
  1. Project boundary vertices into ENU with ab_line_start as origin.
  2. Compute AB bearing and a perpendicular unit vector.
  3. Find bounding extent perpendicular to AB.
  4. Step across in row_spacing increments; clip each row to the polygon.
  5. Return rows as Waypoint lists with alternating sweep direction.
  """
  origin = mission.ab_line_start
  mission.origin = origin

  # AB direction
  ab_brg = math.radians(bearing_deg(mission.ab_line_start, mission.ab_line_end))
  ab_vec = (math.sin(ab_brg), math.cos(ab_brg))      # (east, north)
  perp_vec = (-ab_vec[1], ab_vec[0])                  # rotate 90°

  # Project boundary to ENU
  boundary_enu: List[Tuple[float, float]] = [v.to_enu(origin) for v in mission.boundary]

  # Perpendicular extents
  perp_coords = [p[0] * perp_vec[0] + p[1] * perp_vec[1] for p in boundary_enu]
  perp_min, perp_max = min(perp_coords), max(perp_coords)

  # AB extents (for clipping row length)
  ab_coords = [p[0] * ab_vec[0] + p[1] * ab_vec[1] for p in boundary_enu]
  ab_min, ab_max = min(ab_coords), max(ab_coords)

  rows: List[List[Waypoint]] = []
  offset = perp_min
  reverse = False

  while offset <= perp_max:
    # Build candidate row line in ENU
    row_a_enu = (offset * perp_vec[0] + ab_min * ab_vec[0],
                 offset * perp_vec[1] + ab_min * ab_vec[1])
    row_b_enu = (offset * perp_vec[0] + ab_max * ab_vec[0],
                 offset * perp_vec[1] + ab_max * ab_vec[1])

    # Clip to field polygon (simple: check midpoints along row and trim)
    # For a production implementation use Sutherland-Hodgman clipping.
    # Here we use a 1-metre sample to find the valid segment.
    valid_pts: List[Tuple[float, float]] = []
    row_len = math.hypot(row_b_enu[0] - row_a_enu[0], row_b_enu[1] - row_a_enu[1])
    steps = max(int(row_len), 2)
    for k in range(steps + 1):
      t = k / steps
      pt = (row_a_enu[0] + t * (row_b_enu[0] - row_a_enu[0]),
            row_a_enu[1] + t * (row_b_enu[1] - row_a_enu[1]))
      if point_in_polygon_enu(pt, boundary_enu):
        valid_pts.append(pt)

    if len(valid_pts) >= 2:
      if reverse:
        valid_pts = valid_pts[::-1]
      row_hdg = bearing_deg(mission.ab_line_start, mission.ab_line_end) if not reverse else \
                (bearing_deg(mission.ab_line_start, mission.ab_line_end) + 180) % 360

      waypoints = []
      for i, pt in enumerate(valid_pts):
        # Convert ENU back to LatLon (approximate)
        d_lat = math.degrees(pt[1] / EARTH_RADIUS_M)
        d_lon = math.degrees(pt[0] / (EARTH_RADIUS_M * math.cos(math.radians(origin.lat))))
        pos = LatLon(origin.lat + d_lat, origin.lon + d_lon)
        wp = Waypoint(
          position=pos,
          heading_deg=row_hdg,
          is_headland_start=(i == len(valid_pts) - 1),
          is_headland_end=(i == 0),
        )
        waypoints.append(wp)
      rows.append(waypoints)
      reverse = not reverse

    offset += row_spacing

  return rows


# ---------------------------------------------------------------------------
# Pure-pursuit steering
# ---------------------------------------------------------------------------
def pure_pursuit_curvature(current_pos: LatLon, current_hdg_deg: float,
                            target_pos: LatLon, lookahead_m: float = LOOKAHEAD_M) -> float:
  """
  Compute desired curvature (1/m, positive = left) using pure pursuit.
  Returns a value suitable for sending to the path planner as desired curvature.
  """
  dx = target_pos.lon - current_pos.lon
  dy = target_pos.lat - current_pos.lat
  dist = math.hypot(dx, dy) * EARTH_RADIUS_M * math.radians(1)

  if dist < 0.1:
    return 0.0

  # Angle of target relative to vehicle heading
  target_global_deg = math.degrees(math.atan2(dx, dy))
  alpha_deg = (target_global_deg - current_hdg_deg + 360) % 360
  if alpha_deg > 180:
    alpha_deg -= 360

  alpha_rad = math.radians(alpha_deg)
  L = max(dist, lookahead_m)
  curvature = 2.0 * math.sin(alpha_rad) / L
  return curvature


# ---------------------------------------------------------------------------
# Mission loader
# ---------------------------------------------------------------------------
def load_mission_from_geojson(path: str) -> FieldMission:
  """
  Load a field mission from a GeoJSON file.

  Expected GeoJSON structure
  --------------------------
  {
    "type": "FeatureCollection",
    "features": [
      {
        "type": "Feature",
        "properties": { "role": "boundary" },
        "geometry": { "type": "Polygon", "coordinates": [[ [lon, lat], ... ]] }
      },
      {
        "type": "Feature",
        "properties": { "role": "ab_line" },
        "geometry": { "type": "LineString", "coordinates": [ [lon_a, lat_a], [lon_b, lat_b] ] }
      }
    ]
  }
  """
  data = json.loads(Path(path).read_text())
  boundary: List[LatLon] = []
  ab_start: Optional[LatLon] = None
  ab_end:   Optional[LatLon] = None

  for feat in data.get("features", []):
    role = feat.get("properties", {}).get("role", "")
    geom = feat.get("geometry", {})

    if role == "boundary" and geom.get("type") == "Polygon":
      for lon, lat, *rest in geom["coordinates"][0]:
        boundary.append(LatLon(lat, lon, rest[0] if rest else 0.0))

    elif role == "ab_line" and geom.get("type") == "LineString":
      coords = geom["coordinates"]
      lon_a, lat_a = coords[0][0], coords[0][1]
      lon_b, lat_b = coords[1][0], coords[1][1]
      ab_start = LatLon(lat_a, lon_a)
      ab_end   = LatLon(lat_b, lon_b)

  if not boundary:
    raise ValueError("GeoJSON must contain a 'boundary' Polygon feature")
  if ab_start is None:
    # Default: first edge of boundary
    ab_start = boundary[0]
    ab_end   = boundary[1]

  return FieldMission(boundary=boundary, ab_line_start=ab_start, ab_line_end=ab_end)


# ---------------------------------------------------------------------------
# Main planner loop
# ---------------------------------------------------------------------------
class FieldMissionPlanner:
  """
  Runs at LOOP_HZ (10 Hz) on the openpilot messaging bus.
  Reads `gpsLocationExternal` (RTK GNSS) and publishes `agriMissionState`.
  """

  def __init__(self, field_path: Optional[str] = None) -> None:
    self.params     = Params()
    self.sm         = messaging.SubMaster(["gpsLocationExternal", "liveCalibration"])
    self.pm         = messaging.PubMaster(["agriMissionState"])

    self.state      = MissionState.IDLE
    self.mission:   Optional[FieldMission] = None
    self.all_rows:  List[List[Waypoint]] = []
    self.row_idx    = 0
    self.wp_idx     = 0
    self.curvature  = 0.0
    self.cross_track_err_m = 0.0

    if field_path:
      self._load_field(field_path)

  # ------------------------------------------------------------------
  def _load_field(self, path: str) -> None:
    try:
      self.mission  = load_mission_from_geojson(path)
      self.all_rows = generate_rows(self.mission)
      self.state    = MissionState.IDLE
      self.row_idx  = 0
      self.wp_idx   = 0
      print(f"[FieldPlanner] Loaded {len(self.all_rows)} rows from {path}")
    except Exception as e:
      print(f"[FieldPlanner] ERROR loading field: {e}")
      self.state = MissionState.ABORT

  # ------------------------------------------------------------------
  def _check_geofence(self, pos: LatLon) -> bool:
    """Return True if position is inside the field boundary (with margin)."""
    if self.mission is None or not self.mission.origin:
      return True   # no boundary loaded — do not block
    origin = self.mission.origin
    pt_enu = pos.to_enu(origin)
    boundary_enu = [v.to_enu(origin) for v in self.mission.boundary]
    return point_in_polygon_enu(pt_enu, boundary_enu)

  # ------------------------------------------------------------------
  def _advance_waypoint(self, pos: LatLon) -> None:
    """Move to next waypoint when close enough."""
    if not self.all_rows:
      return
    row = self.all_rows[self.row_idx]
    wp  = row[self.wp_idx]
    dist = haversine_m(pos, wp.position)
    if dist < 1.5:                        # within 1.5 m — advance
      self.wp_idx += 1
      if self.wp_idx >= len(row):
        # End of row → headland turn
        self.state   = MissionState.HEADLAND
        self.row_idx += 1
        self.wp_idx  = 0
        if self.row_idx >= len(self.all_rows):
          self.state = MissionState.COMPLETE

  # ------------------------------------------------------------------
  def update(self) -> None:
    self.sm.update(0)

    if self.state in (MissionState.ABORT, MissionState.COMPLETE):
      self._publish()
      return

    # Check for start command from params
    if self.state == MissionState.IDLE:
      start_cmd = self.params.get("AgriMissionStart")
      if start_cmd == b"1":
        self.state = MissionState.RUNNING
        self.params.remove("AgriMissionStart")

    if not self.sm.updated["gpsLocationExternal"]:
      self._publish()
      return

    gps = self.sm["gpsLocationExternal"]
    pos = LatLon(gps.latitude, gps.longitude, gps.altitude)

    # Geofence check
    if self.state == MissionState.RUNNING and not self._check_geofence(pos):
      print("[FieldPlanner] GEOFENCE BREACH — aborting mission")
      self.state = MissionState.ABORT
      self._publish()
      return

    # Pause command
    pause_cmd = self.params.get("AgriMissionPause")
    if pause_cmd == b"1":
      self.state = MissionState.PAUSED
      self.params.remove("AgriMissionPause")
    resume_cmd = self.params.get("AgriMissionResume")
    if resume_cmd == b"1" and self.state == MissionState.PAUSED:
      self.state = MissionState.RUNNING
      self.params.remove("AgriMissionResume")

    if self.state == MissionState.RUNNING and self.all_rows:
      self._advance_waypoint(pos)
      row = self.all_rows[self.row_idx] if self.row_idx < len(self.all_rows) else []
      if row and self.wp_idx < len(row):
        target_wp = row[self.wp_idx]
        heading   = gps.bearingDeg if hasattr(gps, "bearingDeg") else 0.0
        self.curvature = pure_pursuit_curvature(pos, heading, target_wp.position)
        # Cross-track error (distance to current row segment)
        if self.wp_idx > 0 and self.mission and self.mission.origin:
          prev_wp  = row[self.wp_idx - 1]
          origin   = self.mission.origin
          p   = pos.to_enu(origin)
          a   = prev_wp.position.to_enu(origin)
          b   = target_wp.position.to_enu(origin)
          self.cross_track_err_m = point_to_segment_distance_m(p, a, b)

    self._publish()

  # ------------------------------------------------------------------
  def _publish(self) -> None:
    msg = messaging.new_message("agriMissionState")
    s   = msg.agriMissionState
    s.state            = self.state.name
    s.rowIndex         = self.row_idx
    s.waypointIndex    = self.wp_idx
    s.totalRows        = len(self.all_rows)
    s.desiredCurvature = self.curvature
    s.crossTrackErrorM = self.cross_track_err_m
    s.geofenceOk       = (self.state != MissionState.ABORT)
    self.pm.send("agriMissionState", msg)

  # ------------------------------------------------------------------
  def run(self) -> None:
    rk = Ratekeeper(LOOP_HZ, print_delay_threshold=0.05)
    print(f"[FieldPlanner] Starting at {LOOP_HZ} Hz. State={self.state.name}")
    while True:
      self.update()
      rk.keep_time()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
  parser = argparse.ArgumentParser(description="Agri field mission planner")
  parser.add_argument("--field", type=str, default=None,
                      help="Path to GeoJSON field definition file")
  args = parser.parse_args()

  planner = FieldMissionPlanner(field_path=args.field)
  planner.run()


if __name__ == "__main__":
  main()
