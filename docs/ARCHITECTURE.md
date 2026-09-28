# ZoMa — Architecture

ZoMa is a differential-drive apartment robot with an onboard AI system — **ZoMa
Brain** — built for autonomous indoor navigation (SLAM + Nav2) and natural voice
interaction. The chassis is hand-built from raw acrylic, no laser cutter or CNC.

This document covers the physical and electrical architecture: chassis layout,
power system, sensors, compute, and the two onboard microcontrollers. For pin-level
wiring detail, see [WIRE_CONNECTIONS.md](WIRE_CONNECTIONS.md). For how to build and
flash each component, see [SETUP.md](SETUP.md).

---

## 1. Mechanical layout

- **Chassis**: 3 mm acrylic, 30×30 cm footprint, two-deck structure with a vertical
  camera mast rising from the center of the top deck. Hand-cut with a ruler and
  blade — no laser, no CNC.
- **Bottom deck**: battery placement is centered and low, and is the primary anchor
  for center-of-gravity — every other component is positioned around it.
- **Front wheels**: 48 mm omniwheels, with at least 5 cm of clearance between the
  bottom deck and the floor — enough to roll over carpet transitions without
  snagging.
- **Rear wheels**: differential-drive pair, JGB37-520 DC 6V encoder motors, 200 RPM,
  6 mm D-shaft, with mounting brackets.
- **Camera mast**: vertical acrylic tower on the top deck, holding the front-facing
  camera at height for a clear field of view.

## 2. Electrical architecture

### 2.1 Power

A single **Zeee 2S 5200 mAh LiPo** battery powers the robot, mounted centered on the
bottom deck. The deck reserves physical space for a second battery of the same
footprint, two additional power branches, and a 16-channel servo driver board (for
the arm — see §2.4) with its own regulated supply tap, so the platform can grow
without a chassis redesign.

**Isolation principle:** the motor domain (drive motor driver, PWM switching) is
kept physically and electrically separate from the IMU's power and ground return
path. Motor PWM switching is a real noise source for nearby I2C/analog sensors, so
the fix is rail separation at design time rather than filtering after the fact.

### 2.2 IMU

A BNO055 absolute orientation sensor (I2C, SDA=GPIO21, SCL=GPIO22 — the ESP32's
default I2C pins) is mounted away from the motor driver and high-current wiring, on
its own filtered supply tap. It runs in IMUPLUS mode (gyro + accelerometer fusion,
no magnetometer), so yaw is a relative heading, not a compass bearing.

### 2.3 Status indicator — ZoMa Brain interaction ring

A 5V WS2812 individually-addressable RGB LED ring (16 LEDs) gives a visual readout
of what ZoMa Brain is doing — a distinct color/animation for "listening,"
"thinking," and "speaking" — so interaction has visible turn-taking instead of
feeling like a black box.

### 2.4 Arm (reserved)

Deck space and a power branch are reserved for a 16-channel PWM servo driver to
control an arm. Servo count and arm DOF are part of a future build phase and aren't
populated in the current build.

### 2.5 Compute

A Raspberry Pi 4 is the onboard compute. An off-board GPU machine (referred to
throughout this repo as **Monster**) runs the local LLM / vision-language backend
and heavier ZoMa Brain inference, reached over the robot's web dashboard rather than
running onboard.

### 2.6 Microcontrollers

- **RX** (`esp32_rx/`): motors, IMU, encoders, micro-ROS client, ESP-NOW receive,
  e-stop arbitration.
- **TX** (`esp32_tx/`): PS5 DualSense pairing over Bluetooth Classic, ESP-NOW drive
  link to RX, and a WS2812B 12-LED ring for Bluetooth/ESP-NOW connection status. TX
  forwards raw controller state only — no deadzone or sign normalization — RX owns
  all interpretation.

RX ships two PlatformIO build environments from the same firmware source:

- **`debug_bench`** — plain `Serial.println()` debug output, no micro-ROS code
  compiled in. Used with a normal/data USB cable for bench testing via the Serial
  Monitor.
- **`deploy_ros`** — micro-ROS active over the board's USB serial connection (data
  only — the cable's power wire is cut so the Pi doesn't also try to power the
  board), all debug output compiles to nothing. Used for real robot operation, with
  the RX board's USB port connected to the Raspberry Pi.

Any RX firmware change is proven on `debug_bench` before being run under
`deploy_ros`.

## 3. Software / navigation stack

- **SLAM**: lidar-only ICP (RTAB-Map), `Reg/Strategy:=1` (ICP),
  `Reg/Force3DoF:=true`, `approx_sync:=true` for independently-clocked `/scan` and
  `/odometry/filtered`.
- **Nav2** on top of the SLAM map for autonomous path planning.
- **EKF** (`robot_localization`): wheel encoders provide odometry, IMU yaw is fed
  directly via `imu0_config` — encoders and IMU each report only what they
  physically measure, fused in the EKF rather than combined in firmware.
- **ZoMa Brain**: tiered inference —
  - Tier 0: reflex / canned responses, near-instant.
  - Tier 1: small local model, fast first-token response.
  - Tier 2: larger model on the off-board GPU machine (Monster), for deeper
    reasoning — async, not blocking basic interaction.
  - Voice pipeline: TTS output with barge-in interrupt; STT/mic input for
    fully hands-free conversation.

## 4. Repository structure

```
ZoMa-V2-Public/
├── docs/               # this file, WIRE_CONNECTIONS.md, SETUP.md, STARTUP_GUIDE.md
├── esp32_tx/           # PS5 pairing + ESP-NOW to RX
├── esp32_rx/           # motors, IMU, encoders, micro-ROS client, e-stop
├── pi/                 # camera capture, micro-ROS agent, ROS publishers, lidar driver
├── monster/            # SLAM, Nav2, EKF, camera pipeline, ZoMa Brain (off-board GPU machine)
├── web/                # dashboard / web UI
└── mechanical/         # CAD / cut files for the acrylic chassis
```

---

*ZoMa is property of TheMechanics. Contact: mamau.mechanics@gmail.com*
