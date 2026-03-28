using Cxx = import "./include/c++.capnp";
$Cxx.namespace("cereal");

@0xb526ba661d550a59;

# custom.capnp: a home for empty structs reserved for custom forks
# These structs are guaranteed to remain reserved and empty in mainline
# cereal, so use these if you want custom events in your fork.

# DO rename the structs
# DON'T change the identifier (e.g. @0x81c2f05a394cf4af)

struct AgriMissionState @0x81c2f05a394cf4af {
  # Published by field_mission_planner at 10 Hz
  state            @0 :Text;    # MissionState name: IDLE/RUNNING/HEADLAND/PAUSED/COMPLETE/ABORT
  rowIndex         @1 :UInt16;  # current row index (0-based)
  waypointIndex    @2 :UInt16;  # waypoint index within current row
  totalRows        @3 :UInt16;  # total rows in the mission
  desiredCurvature @4 :Float32; # pure-pursuit curvature setpoint (1/m, +left)
  crossTrackErrorM @5 :Float32; # perpendicular distance from row line (metres)
  geofenceOk       @6 :Bool;    # True when tractor inside field boundary
}

struct AgriSupervisorState @0xaedffd8f31e7b55d {
  # Published by supervisor_watchdog at 20 Hz
  state       @0 :Text;     # SupervisorState name: INIT/NOMINAL/DEGRADED/ESTOP
  longEnabled @1 :Bool;     # True = longitudinal control authorised
  estopReason @2 :Text;     # last ESTOP trigger (empty when nominal)
  speedOk     @3 :Bool;
  gnssOk      @4 :Bool;
  plannerOk   @5 :Bool;
}

struct CustomReserved2 @0xf35cc4560bbf6ec2 {
}

struct CustomReserved3 @0xda96579883444c35 {
}

struct CustomReserved4 @0x80ae746ee2596b11 {
}

struct CustomReserved5 @0xa5cd762cd951a455 {
}

struct CustomReserved6 @0xf98d843bfd7004a3 {
}

struct CustomReserved7 @0xb86e6369214c01c8 {
}

struct CustomReserved8 @0xf416ec09499d9d19 {
}

struct CustomReserved9 @0xa1680744031fdb2d {
}

struct CustomReserved10 @0xcb9fd56c7057593a {
}

struct CustomReserved11 @0xc2243c65e0340384 {
}

struct CustomReserved12 @0x9ccdc8676701b412 {
}

struct CustomReserved13 @0xcd96dafb67a082d0 {
}

struct CustomReserved14 @0xb057204d7deadf3f {
}

struct CustomReserved15 @0xbd443b539493bc68 {
}

struct CustomReserved16 @0xfc6241ed8877b611 {
}

struct CustomReserved17 @0xa30662f84033036c {
}

struct CustomReserved18 @0xc86a3d38d13eb3ef {
}

struct CustomReserved19 @0xa4f1eb3323f5f582 {
}
