# Open Gimbal — design memo (2026-08-17, draft 0)

Why: every gimbal under ~$200 is sized for a 19 mm FPV camera. Anything that
carries a real camera is $700+ and closed. We already own the microcontrollers,
and a 3-joint stabilized head is the same problem class as the robot joints in
`jointbus`. So: build the controller, size it for a mirrorless-class camera,
and grow the airframe to match. Companion to `MISSION_PLANNER.md` (which owns
the flight/mission side; this doc owns the payload).

Status: **thinking**. Nothing bought, nothing wired. Open questions at the end.

---

## 1. Target payload (drives everything)

Pick the camera class first — it sets motor size, gimbal mass, and airframe.

| Class | Camera + lens | Gimbal motors | Gimbal mass | Aircraft AUW | Airframe |
|---|---|---|---|---|---|
| A. APS-C mirrorless (recommended first target) | 450–700 g (Sony a6x00 + 16-50 / 20 mm pancake; mech shutter → mapping-grade) | GBM5208-class, ~100 g each | 500–800 g | 5–7 kg | 13–15" quad or 12–13" X8 |
| B. Full-frame + cine lens | 1.2–2 kg | GBM8108/8017-class | 1.2–1.8 kg | 9–13 kg | 15–18" X8 / hexa, 12S |

Class A gets the cine *and* the mapping camera in one payload and keeps the
aircraft in hobbyist-part territory. Class B roughly doubles every number and
pushes into 12S / big-motor land. **Design the controller for either (it
doesn't care); design mechanics + airframe for A.**

## 2. Architecture

```
                 ┌──────────────── aircraft ────────────────┐
 ELRS RX ──CRSF──┤ Pixhawk (ArduPilot = gimbal MANAGER)      │
 GCS/companion ──┤   TELEM2 ── MAVLink v2 ── gimbal DEVICE ──┼── our board
 mission ROI ────┤                                           │      │
                 └───────────────────────────────────────────┘      │
                                                                    ▼
      ┌──────────────────── our board ─────────────────────────────────┐
      │ MCU (ESP32-S3 or STM32/Teensy — whatever's on the bench)       │
      │  ├─ 3× 3-phase driver (DRV8313 / SimpleFOC Mini) → 3 motors    │
      │  ├─ 3× magnetic encoder (SPI: MT6701 or AS5048A) — joint angles │
      │  ├─ camera IMU (SPI ICM-42688-P) on the camera plate            │
      │  ├─ frame IMU (same part) on the base — optional but cheap      │
      │  ├─ UART: MAVLink gimbal-device protocol (primary)              │
      │  ├─ UART: SBUS/CRSF direct input (2nd operator, no-Pixhawk use) │
      │  ├─ USB/WiFi: tuning + live plots (no JSON reading)             │
      │  └─ camera trigger out + hot-shoe feedback in (geotag)          │
      └────────────────────────────────────────────────────────────────┘
```

Roles, hard boundary:
- **Controller (this board)**: 1 kHz camera-frame attitude control, joint-space
  motor control, angle reporting. Knows nothing about missions.
- **Manager (ArduPilot)**: arbitrates who's commanding — RC channels
  (`RCx_OPTION` 212-214), `DO_SET_ROI`, GCS gamepad, companion quaternion
  stream, head tracker via EdgeTX trainer. All already exist; we implement
  only the device side (`GIMBAL_DEVICE_INFORMATION`,
  `GIMBAL_DEVICE_ATTITUDE_STATUS`, handle `GIMBAL_DEVICE_SET_ATTITUDE`).
  Result: `MNT1_TYPE=4`-class integration with zero ArduPilot changes.

Optional later: expose the three joints on `jointbus`/`robotd` (SI radians,
50 Hz sample stream) so the gimbal is a "head" a policy can drive — same
recorder, same node-tool pipeline. Cheap because the joint angles are already
first-class thanks to the encoders.

## 3. Software stack (all OSI-licensed)

| Layer | Choice | License | Notes |
|---|---|---|---|
| Motor control | SimpleFOC (Arduino/PlatformIO) | MIT | Designed around gimbal motors; ESP32 MCPWM gives 12 outputs = 3 motors × 3PWM with room; STM32/Teensy have best timer support if ESP32 jitter bites |
| Attitude estimation | xioTechnologies **Fusion** (AHRS, Madgwick-derived) | MIT | Runs on camera IMU; frame IMU only for follow-mode reference |
| Protocol | mavlink/c_library_v2 (gimbal protocol v2) | MIT | Also parse SBUS/CRSF for direct input |
| Config/tuning UI | ESP32-hosted web page: live plots of error/rate/current, PID sliders, notch filter setup | — | Also stream samples as NDJSON on TCP like robotd, so node-tool can graph it |
| Build | PlatformIO | Apache | Same toolchain for ESP32/STM32/Teensy targets |

Control structure (per axis, ~1 kHz outer / 5–10 kHz FOC inner):

```
target quaternion (earth-frame or follow-mode) ─┐
                                                 ├─► attitude error (camera frame)
camera IMU → Fusion → camera quaternion ─────────┘        │
                                                          ▼ Jacobian from encoder angles
                                            per-joint rate/torque command → SimpleFOC (closed loop on encoder)
```
Encoders from day one — not an upgrade. They give real 3-axis kinematics (yaw
still works when pitched down), full holding stiffness, efficiency (no
open-loop voltage-mode heat), and correct angle reporting to MAVLink.

Modes: earth-lock (all axes), follow-yaw (yaw tracks aircraft heading, pitch/
roll locked), nadir (mapping, pitch −90 lock), RC-rate, MAVLink-attitude.

## 4. Electronics — bench BOM (class A gimbal)

| Item | Qty | ~$ | Note |
|---|---|---|---|
| MCU dev board (on hand) | 1 | 0 | ESP32-S3 preferred over classic ESP32 for USB + PSRAM; Teensy 4.1 if you have one is the strongest real-time option |
| SimpleFOC Mini v1 (DRV8313, 2.5 A, up to ~24 V) | 3 | 30 | Or bare DRV8313 breakouts; 6S = 25.2 V is right at the limit → run gimbal from a 4S/5S rail or a 5–18 V buck (a 6S-in buck to 16 V is the clean answer) |
| MT6701 or AS5048A magnetic encoder boards + diametric magnets | 3 | 12 | SPI, share bus, 3 CS lines |
| ICM-42688-P breakout | 2 | 10 | SPI; camera-side one is mandatory |
| GBM5208-200T gimbal motors (hollow shaft helps wiring) | 3 | 100–130 | Roll and pitch; yaw could be the same. Bigger (GBM5210) if class B creeps in |
| Slip ring 12-wire (continuous yaw) — optional | 1 | 15 | Or limited yaw travel + service loop |
| Buck 6S→16 V 3 A, connectors, silicone dampers ×8 | — | 25 | |
| **Total (excluding camera, frame plates)** | | **~$200–225** | vs $700+ for the closed equivalent |

Rev 2 (after it works): one KiCad board — MCU + 3× DRV8313 + IMU + connectors.
That's the thing worth sharing.

### 4a. Motor sizing (2026-08-18)

Budget per axis = imbalance + inertia×disturbance-accel + friction + wind,
×3–5 margin. 700 g mirrorless ≈ 0.1 N·m need → **0.35–0.5 N·m** → 5208
class. 300 g compact → ~0.15 → 3508/4108. GoPro → 0.05 → 2804.
Kt ≈ 9.55/KV: 2804-100T ~0.1 N·m/A (30 g, $10–15 w/ AS5600); 4108 ~0.2;
5208-200T ~0.35 (110 g). Encoder built-in is not a deciding factor — a $3
MT6701 + magnet fits any motor.

- **2804 w/ encoder = the Phase 0/1 bench motor. Buy 3 now.** Marginal for
  the real camera (soft, hot at ~1 A stall). Swap motors once camera fixed.
- **FPV motors (2204/2208) + timing belts: rejected.** Kt ~100× too small →
  needs ~20:1 to keep current sane; cogging ripple multiplies by the ratio
  (~0.1 N·m at output = whole budget), two belt stages add compliance
  resonance in-band, needs current-sense FOC, and pulleys/idlers eat the mass
  saving. Only legit belt use: 2–3:1 on **yaw** with a real gimbal motor.
- Real mass levers: lens choice (pancake vs kit zoom = 50 g), tube+clamp
  frame, bearing selection. Light body + pancake → 4108-class motors OK.

## 5. Mechanics (class A)

- Axis order outer→inner: **yaw → roll → pitch** (standard camera gimbal;
  roll in the middle keeps horizon simple, pitch innermost carries only camera).
- Every axis has adjustable balance (slotted plates): the camera's CoG must sit
  on each motor axis to within a few mm or the motors fight gravity forever.
- Far-side bearings on roll and pitch: a 5208's own bearing cannot cantilever
  a 700 g camera through vibration. Aluminium tube + clamp blocks + 3D-printed
  CF-nylon brackets, or CNC carbon plates from a local shop.
- Camera IMU rigidly on the camera plate, away from the motors; frame IMU on
  the damper plate.
- Damper plate with 8 silicone balls between airframe and gimbal — this plus
  camera IMU is what makes it cinematic, not the control loop alone.
- Weight budget target: ≤ 800 g gimbal, ≤ 700 g camera → 1.5 kg payload.

## 6. Airframe (only if we grow — the 10" carries a bench-test gimbal, not this)

Rule of thumb: hover at ≤ 50 % throttle. 1.5 kg payload + 1.5 kg 6S battery +
~1.8 kg frame/motors/electronics ≈ 5 kg AUW → need ≥ 10 kg max thrust.
- **X8 on 12–13"** (8× 4108/4114 ~380–400 KV, 6S): motor-out redundancy for the
  payload you care about, compact fold. Coaxial costs ~15 % efficiency.
- **Quad on 15–17"** (4× 4014 400 KV / 5008 340 KV, 6S): most efficient, best
  endurance, no redundancy, big footprint.
- Frames: Tarot 650/680/X6/X8 class or a plate-and-tube DIY. Pixhawk,
  ELRS, LC29H, and the mission stack all carry over unchanged. Everything in
  `MISSION_PLANNER.md` stays valid; only the params change.
Defer the airframe until the gimbal is stabilizing a real camera on the bench.

## 7. Phases

0. **Bench, one joint** — MCU + one SimpleFOC Mini + one motor + one encoder →
   closed-loop position/velocity. Then strap an IMU to a stick on the motor →
   1-axis stabilizer. Sensor rates, loop jitter measured. (evenings)
1. **3 axes, dummy mass** — water bottle at camera mass on a crude frame,
   earth-lock + follow modes, joystick over serial, web plots. Tune. Notch
   filters. This is where the Jacobian/kinematics get proven.
2. **MAVLink gimbal device** — talk to ArduPilot **SITL** first (SITL takes a
   real serial port), then the Pixhawk: `MNT1_TYPE=4`-class, RC channels, ROI
   from `mission_export.py` — Phase-0 tooling already emits `DO_SET_ROI`.
3. **Real camera, real frame** — balance jig, bearings, dampers, camera trigger
   + hot-shoe geotag. Hand-carried and car-mounted tests before it flies.
4. **Fly** — on a bigger airframe (§6), or on the 10" with a lighter camera
   only to shake out the flight integration.
5. **Rev-2 PCB + share** — KiCad board, BOM, docs; jointbus head interface.

## 8. Open questions

- Which camera? Own one already? (a6x00 / ZV-E10 / other) → fixes class A/B.
- MCU on hand: ESP32 classic / S3, any STM32 Nucleo or Teensy 4.x?
- Continuous yaw (slip ring) or ±170° with a service loop?
- Bigger frame appetite: X8 12–13" (redundancy, fold) vs quad 15–17"
  (endurance)? Battery preference (6S LiPo vs Li-ion pack)?
