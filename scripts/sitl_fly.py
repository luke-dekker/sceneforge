"""Fly a QGC .plan in ArduPilot SITL and score the flown path.

Launches the Windows SITL ArduCopter binary (tools/ardupilot-sitl), uploads
the mission over MAVLink, arms in AUTO, records GLOBAL_POSITION_INT until the
mission ends (RTL/disarm), then converts the flown track back into scene-local
ENU via scene.json and reports cross-track error against the planned
trajectory.

Usage: python scripts/sitl_fly.py --plan <mission.plan> \
           --scene-json <scene.json> [--traj <planned.traj.json>] \
           --out <flown.traj.json> [--speedup 5] [--timeout 600]
"""
import argparse
import json
import math
import subprocess
import time
from pathlib import Path

from pymavlink import mavutil
from pyproj import CRS, Transformer

SITL_DIR = Path(r"C:\Users\lucas\tools\ardupilot-sitl")
COPTER_MODES = {"STABILIZE": 0, "GUIDED": 4, "AUTO": 3, "RTL": 6, "LOITER": 5}


def launch_sitl(home, speedup):
    exe = SITL_DIR / "ArduCopter.elf"
    cmd = [str(exe), "--model", "+", "--speedup", str(speedup),
           "--defaults", str(SITL_DIR / "copter.parm"),
           "--home", f"{home[0]},{home[1]},{home[2]},0", "-I0"]
    log = open(SITL_DIR / "sitl.log", "w")
    proc = subprocess.Popen(cmd, cwd=str(SITL_DIR), stdout=log, stderr=log)
    print(f"SITL pid {proc.pid}, connecting...")
    return proc


def plan_items(plan):
    for item in plan["mission"]["items"]:
        p = [0.0 if v is None else float(v) for v in item["params"]]
        yield (item["command"], item["frame"], p)


def upload_mission(m, plan):
    home = plan["mission"]["plannedHomePosition"]
    items = [(16, 0, [0, 0, 0, 0, home[0], home[1], home[2]])]  # seq 0 = home
    items += list(plan_items(plan))
    m.mav.mission_count_send(m.target_system, m.target_component, len(items))
    sent = set()
    deadline = time.time() + 60
    while time.time() < deadline:
        msg = m.recv_match(type=["MISSION_REQUEST", "MISSION_REQUEST_INT",
                                 "MISSION_ACK"], blocking=True, timeout=10)
        if msg is None:
            raise RuntimeError("mission upload stalled")
        if msg.get_type() == "MISSION_ACK":
            if msg.type != 0:
                raise RuntimeError(f"mission rejected (MAV_MISSION result {msg.type})")
            print(f"mission uploaded ({len(items) - 1} items)")
            return
        seq = msg.seq
        cmd, frame, p = items[seq]
        m.mav.mission_item_int_send(
            m.target_system, m.target_component, seq, frame, cmd,
            0, 1, p[0], p[1], p[2], p[3],
            int(p[4] * 1e7), int(p[5] * 1e7), p[6])
        sent.add(seq)
    raise RuntimeError("mission upload timed out")


def set_mode(m, mode):
    m.mav.command_long_send(
        m.target_system, m.target_component,
        mavutil.mavlink.MAV_CMD_DO_SET_MODE, 0,
        mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
        COPTER_MODES[mode], 0, 0, 0, 0, 0)


def set_param(m, name, value):
    m.mav.param_set_send(m.target_system, m.target_component,
                         name.encode(), value,
                         mavutil.mavlink.MAV_PARAM_TYPE_REAL32)


def arm(m, retries=30):
    for i in range(retries):
        m.mav.command_long_send(m.target_system, m.target_component,
                                mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
                                0, 1, 0, 0, 0, 0, 0, 0)
        msg = m.recv_match(type="COMMAND_ACK", blocking=True, timeout=5)
        if msg and msg.command == mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM \
                and msg.result == 0:
            print("armed")
            return
        time.sleep(3)  # prearm checks still settling
    raise RuntimeError("failed to arm")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", type=Path, required=True)
    ap.add_argument("--scene-json", type=Path, required=True)
    ap.add_argument("--traj", type=Path, default=None,
                    help="planned trajectory json for error scoring")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--speedup", type=float, default=5.0)
    ap.add_argument("--timeout", type=float, default=600.0)
    args = ap.parse_args()

    plan = json.loads(args.plan.read_text(encoding="utf-8-sig"))
    scene = json.loads(args.scene_json.read_text(encoding="utf-8-sig"))
    home = plan["mission"]["plannedHomePosition"]

    proc = launch_sitl(home, args.speedup)
    try:
        m = mavutil.mavlink_connection("tcp:127.0.0.1:5760")
        m.wait_heartbeat(timeout=60)
        print("heartbeat ok")
        # ArduPilot streams nothing unsolicited - ask for everything at 4 Hz
        m.mav.request_data_stream_send(m.target_system, m.target_component,
                                       mavutil.mavlink.MAV_DATA_STREAM_ALL, 4, 1)
        # allow arming + auto-takeoff in AUTO without raising throttle
        set_param(m, "AUTO_OPTIONS", 3)
        # wait for GPS fix + EKF origin
        deadline = time.time() + 120
        while time.time() < deadline:
            msg = m.recv_match(type="GPS_RAW_INT", blocking=True, timeout=10)
            if msg and msg.fix_type >= 3:
                break
        else:
            raise RuntimeError("no GPS fix")
        print("GPS fix")
        time.sleep(5)

        upload_mission(m, plan)
        set_mode(m, "AUTO")
        arm(m)

        m.mav.command_long_send(
            m.target_system, m.target_component,
            mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL, 0,
            mavutil.mavlink.MAVLINK_MSG_ID_GLOBAL_POSITION_INT,
            200000, 0, 0, 0, 0, 0)  # 5 Hz sim-time

        flown = []
        armed = True
        t0 = None
        cur_seq = 0
        wall_deadline = time.time() + args.timeout
        while armed and time.time() < wall_deadline:
            msg = m.recv_match(type=["GLOBAL_POSITION_INT", "HEARTBEAT",
                                     "MISSION_CURRENT", "STATUSTEXT"],
                               blocking=True, timeout=10)
            if msg is None:
                continue
            t = msg.get_type()
            if t == "MISSION_CURRENT":
                cur_seq = msg.seq
            elif t == "GLOBAL_POSITION_INT":
                if t0 is None:
                    t0 = msg.time_boot_ms
                flown.append({"t": (msg.time_boot_ms - t0) / 1000.0,
                              "lat": msg.lat / 1e7, "lon": msg.lon / 1e7,
                              "rel_alt": msg.relative_alt / 1000.0,
                              "seq": cur_seq})
            elif t == "HEARTBEAT":
                armed = bool(msg.base_mode
                             & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
            elif t == "STATUSTEXT" and msg.severity <= 3:
                print("FC:", msg.text)
        print(f"flight ended, {len(flown)} samples recorded")
    finally:
        proc.terminate()

    # back to scene-local ENU
    off_e, off_n = scene["crs"]["utm_offset"]
    to_utm = Transformer.from_crs(CRS.from_epsg(4326),
                                  CRS.from_proj4(scene["crs"]["proj4"]),
                                  always_xy=True)
    rtl_seq = len(plan["mission"]["items"])  # seq 0 is home; RTL is the last item
    samples = []
    for s in flown:
        e, n = to_utm.transform(s["lon"], s["lat"])
        samples.append({"t": round(s["t"], 2), "seq": s["seq"],
                        "aircraft": {"pos": [
            round(e - off_e, 2), round(n - off_n, 2), round(s["rel_alt"], 2)]}})
    args.out.write_text(json.dumps(
        {"scene": scene["name"], "frame": "enu", "source": "sitl",
         "samples": samples}, indent=1))
    print(f"wrote {args.out}")

    if args.traj and samples:
        planned = json.loads(args.traj.read_text(encoding="utf-8-sig"))["samples"]
        pts = [p["aircraft"]["pos"] for p in planned]
        # cross-track: min distance from each airborne flown point to the plan
        errs = []
        for s in samples:
            p = s["aircraft"]["pos"]
            # score only the mission proper: airborne, past takeoff, before RTL
            if p[2] < 3 or s["seq"] <= 1 or s["seq"] >= rtl_seq:
                continue
            errs.append(min(math.dist(p, q) for q in pts))
        if errs:
            errs.sort()
            print(f"cross-track error vs plan ({len(errs)} airborne samples): "
                  f"mean {sum(errs)/len(errs):.1f} m, "
                  f"p95 {errs[int(0.95*len(errs))]:.1f} m, max {errs[-1]:.1f} m")


if __name__ == "__main__":
    main()
