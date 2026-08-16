"""Export a sceneforge trajectory to a QGC .plan mission (ArduPilot).

Takes the trajectory json (local ENU samples from sceneforge_mission.py) plus
the scene's scene.json georef, and emits a QGroundControl .plan: TAKEOFF,
spline/normal waypoints downsampled to a minimum spacing, DO_CHANGE_SPEED on
speed changes, DO_SET_ROI following the gimbal-target track, optional RTL.

Altitudes are relative-to-home (engine ground plane ~= home altitude).

Usage: python scripts/mission_export.py --traj <traj.json> \
           --scene-json <scene.json> --out <mission.plan> \
           [--spacing 8] [--no-spline] [--no-rtl]
"""
import argparse
import json
import math
from pathlib import Path

from pyproj import CRS, Transformer

NAV_WAYPOINT = 16
NAV_SPLINE_WAYPOINT = 82
NAV_TAKEOFF = 22
NAV_RTL = 20
DO_CHANGE_SPEED = 178
DO_SET_ROI = 201
FRAME_RELATIVE_ALT = 3
FRAME_MISSION = 2


def dist2(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--traj", type=Path, required=True)
    ap.add_argument("--scene-json", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--spacing", type=float, default=8.0,
                    help="min waypoint spacing in meters")
    ap.add_argument("--speed-step", type=float, default=0.5,
                    help="emit DO_CHANGE_SPEED when speed changes this much")
    ap.add_argument("--roi-step", type=float, default=5.0,
                    help="emit DO_SET_ROI when the gimbal target moves this far")
    ap.add_argument("--no-spline", action="store_true")
    ap.add_argument("--no-rtl", action="store_true")
    args = ap.parse_args()

    traj = json.loads(args.traj.read_text(encoding="utf-8-sig"))
    scene = json.loads(args.scene_json.read_text(encoding="utf-8-sig"))
    off_e, off_n = scene["crs"]["utm_offset"]
    to_wgs84 = Transformer.from_crs(CRS.from_proj4(scene["crs"]["proj4"]),
                                    CRS.from_epsg(4326), always_xy=True)

    def enu_to_lla(pos):
        lon, lat = to_wgs84.transform(pos[0] + off_e, pos[1] + off_n)
        return lat, lon, pos[2]  # z = relative alt (ground plane ~ home)

    samples = traj["samples"]
    wp_cmd = NAV_WAYPOINT if args.no_spline else NAV_SPLINE_WAYPOINT

    items = []
    jid = [1]

    def add(command, params, frame=FRAME_RELATIVE_ALT):
        items.append({"type": "SimpleItem", "autoContinue": True,
                      "command": command, "doJumpId": jid[0],
                      "frame": frame, "params": params})
        jid[0] += 1

    first = samples[0]
    lat0, lon0, alt0 = enu_to_lla(first["aircraft"]["pos"])
    add(NAV_TAKEOFF, [0, 0, 0, None, lat0, lon0, alt0])

    last_wp = None
    last_speed = None
    last_roi = None
    for i, s in enumerate(samples):
        pos = s["aircraft"]["pos"]
        is_last = i == len(samples) - 1
        if last_wp is not None and dist2(pos, last_wp) < args.spacing and not is_last:
            continue
        speed = s["aircraft"].get("speed_mps")
        if speed and (last_speed is None
                      or abs(speed - last_speed) >= args.speed_step):
            add(DO_CHANGE_SPEED, [1, round(speed, 1), -1, 0, 0, 0, 0],
                frame=FRAME_MISSION)
            last_speed = speed
        roi = s.get("gimbal", {}).get("target")
        if roi and (last_roi is None or dist2(roi, last_roi) >= args.roi_step):
            rlat, rlon, ralt = enu_to_lla(roi)
            add(DO_SET_ROI, [0, 0, 0, 0, rlat, rlon, ralt])
            last_roi = roi
        lat, lon, alt = enu_to_lla(pos)
        # Spline waypoints need a normal waypoint as the final anchor
        add(NAV_WAYPOINT if is_last else wp_cmd,
            [0, 0, 0, None, lat, lon, alt])
        last_wp = pos

    if not args.no_rtl:
        add(NAV_RTL, [0, 0, 0, 0, 0, 0, 0], frame=FRAME_MISSION)

    plan = {
        "fileType": "Plan",
        "version": 1,
        "groundStation": "sceneforge",
        "geoFence": {"circles": [], "polygons": [], "version": 2},
        "rallyPoints": {"points": [], "version": 2},
        "mission": {
            "version": 2,
            "firmwareType": 3,   # ArduPilot
            "vehicleType": 2,    # multirotor
            "globalPlanAltitudeMode": 1,
            "cruiseSpeed": 15,
            "hoverSpeed": 5,
            "plannedHomePosition": [lat0, lon0, 0],
            "items": items,
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(plan, indent=1))
    n_wp = sum(1 for i in items if i["command"] in (NAV_WAYPOINT, NAV_SPLINE_WAYPOINT))
    n_roi = sum(1 for i in items if i["command"] == DO_SET_ROI)
    print(f"wrote {args.out}: {len(items)} items "
          f"({n_wp} waypoints, {n_roi} ROI updates), home {lat0:.6f},{lon0:.6f}")


if __name__ == "__main__":
    main()
