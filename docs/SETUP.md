# ZoMa — Setup

Repository layout and the development environment for each part of the build:
firmware, onboard Pi software, the off-board GPU machine, and the mechanical
chassis.

---

## 1. Repository layout

```
ZoMa-V2-Public/
├── docs/            # ARCHITECTURE.md, WIRE_CONNECTIONS.md, SETUP.md (this file), STARTUP_GUIDE.md, EQUIPMENT.md
├── esp32_tx/        # PS5 pairing + ESP-NOW to RX
├── esp32_rx/        # motors, IMU, encoders, micro-ROS client, e-stop
├── pi/              # camera capture, micro-ROS agent, ZoMa Brain audio/LED clients
├── monster/         # camera pipeline, ZoMa Brain (off-board GPU machine)
├── web/             # dashboard / web UI
└── mechanical/      # CAD/cut files for the chassis, and 3D-printable design files
```

Clone the full repository even if you're only working on one component — the docs
and cross-component wiring reference assume the whole tree is present.

Line endings are normalized to LF (`.gitattributes`: `* text=auto eol=lf`) so the
repo builds cleanly across Windows and macOS/Linux.

Secrets, Wi-Fi credentials, and any other machine-specific values are never
committed — see each component's section below for how they're supplied instead
(environment variables or a local, gitignored file).

## 2. Firmware build environment (ESP32 RX / TX)

- ESP32 RX firmware is built under WSL/Ubuntu on Windows machines — the
  `micro_ros_platformio` dependency build invokes colcon/meson via bash scripts
  that don't run natively on Windows. Builds work natively on macOS.
- `platformio.ini`'s `deploy_ros` environment is pinned to
  `platform = espressif32@6.5.0` — newer platform releases moved to an Arduino
  core that `micro_ros_platformio`'s build system doesn't support. Don't let a
  dependency update silently bump this.
- micro-ROS requires a baud rate of 921600.
- Each board ships a `debug_bench` environment (plain Serial output, no
  micro-ROS) and a `deploy_ros` environment (micro-ROS active, debug output
  compiled out). Prove a firmware change on `debug_bench` before flashing
  `deploy_ros`.
- `upload_port`/`monitor_port` are intentionally left unset in the committed
  `platformio.ini` files, so PlatformIO auto-detects the board. If you need to pin
  a specific port on your machine, set it in a local, gitignored
  `platformio.ini` override rather than committing one.

## 3. Onboard software (Raspberry Pi)

- ROS 2 Humble, run in Docker — runs the micro-ROS agent that bridges the RX
  board's `deploy_ros` firmware to the rest of the system.
- Boot automation: a systemd service launches the onboard stack (micro-ROS agent,
  audio/LED host processes) into a tmux session, so it's inspectable and
  restartable without re-running everything by hand.
- The scripts in `pi/scripts/` reference the repo's install location on the Pi
  through a variable near the top of each script — set that to wherever you clone
  this repo on your own Pi.
- EKF, a lidar driver, and Nav2 are part of the planned Season 2 autonomous
  navigation stack — not part of this build. See
  [ARCHITECTURE.md](ARCHITECTURE.md#4-planned--autonomous-navigation-season-2).

## 4. Off-board GPU machine — `monster/` (ZoMa Brain)

- Runs the camera pipeline and ZoMa Brain (local LLM + vision-language model
  serving, TTS/STT).
- GPU passthrough (`--gpus all`) is required for any container touching the GPU.
- If running under WSL2: GStreamer pipelines relying on wall-clock timestamps can
  break due to WSL2 clock stepping — use a no-clock pipeline pattern
  (`buffer-mode=none ntp-sync=false` + `use_gst_timestamps:true`) if this comes up.
- API keys (e.g. `ANTHROPIC_API_KEY`) and other secrets are read from environment
  variables or a local file outside the repo — never hardcoded. See
  [STARTUP_GUIDE.md](STARTUP_GUIDE.md) for the exact variables ZoMa Brain expects.

## 5. Mechanical build

- 3 mm acrylic, 30×30 cm two-deck chassis with a vertical camera mast, hand-cut
  with a ruler and blade (no laser, no CNC).
- CAD/cut templates and 3D-printable design files live in `mechanical/` (see
  [`mechanical/3d_design/`](../mechanical/3d_design/) for printed parts).
- Battery placement (centered, bottom deck), the reserved second-battery
  footprint, and IMU isolation are mechanical constraints — factor them into any
  cut-layout changes, not just the electrical wiring. See
  [ARCHITECTURE.md](ARCHITECTURE.md) for the reasoning behind each of these.

## 6. Before you build

1. Read [ARCHITECTURE.md](ARCHITECTURE.md) and [WIRE_CONNECTIONS.md](WIRE_CONNECTIONS.md).
2. Check [EQUIPMENT.md](EQUIPMENT.md) for the parts and tools needed, organized
   by build day.
3. Build and prove each module in isolation (`debug_bench` for firmware, or the
   equivalent bench setup for other components) before integrating it into the
   full, deployed system.
4. Confirm physical assumptions (encoder counts-per-revolution, pin behavior,
   wiring) against your own hardware rather than trusting a datasheet alone — real
   builds vary.

---

*ZoMa is property of TheMechanics. Contact: mamau.mechanics@gmail.com*
