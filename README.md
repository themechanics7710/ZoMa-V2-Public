# ZoMa

**ZoMa** is a hand-built, differential-drive home robot with an onboard AI
assistant — **ZoMa Brain** — that can see, listen, talk, and eventually navigate
an apartment on its own. It's built from raw acrylic sheet with no laser cutter or
CNC machine: just a ruler, a blade, and a small pile of off-the-shelf electronics.

This repository is the complete, public source for the build: firmware, onboard
software, the AI backend, the web dashboard, and the mechanical design files.

---

## What ZoMa does

- **Drives itself around** using a lidar-based SLAM map (RTAB-Map) and Nav2 for
  path planning, fusing wheel-encoder odometry with IMU heading through an EKF.
- **Sees and hears** through an onboard camera and a far-field microphone array,
  streamed to an off-board GPU machine for real-time processing.
- **Talks back** with a voice pipeline (speech-to-text → LLM → text-to-speech)
  that supports interrupting it mid-sentence, and a tiered inference system —
  instant canned replies for simple things, a fast local model for everyday
  conversation, and a larger model for anything that needs deeper reasoning.
- **Shows its state** through a 16-LED ring that lights up differently depending
  on whether it's listening, thinking, or speaking — so interacting with it feels
  less like talking to a black box.
- **Drives manually** too, over a PS5 DualSense controller paired to a dedicated
  ESP32 transmitter, relayed to the robot over a low-latency ESP-NOW link.

It's built with room to grow: the chassis reserves space and power for a second
battery and a robotic arm, without needing a redesign.

## How the robot is put together

At a glance: two ESP32 microcontrollers handle real-time control (driving the
motors, reading the encoders and IMU, receiving the controller input), a
Raspberry Pi 4 handles onboard I/O (camera, microphone array, lidar, and talking
to the ESP32s over micro-ROS), and an off-board machine with a GPU does the heavy
lifting for AI (speech recognition, the language model, vision, and text-to-speech).
A browser-based dashboard ties the camera feed and a chat interface together.

```
Controller (PS5) ─▶ ESP32 TX ─ESP-NOW─▶ ESP32 RX ─▶ motors / encoders / IMU
                                             │
                                        micro-ROS (USB serial)
                                             │
                                       Raspberry Pi 4 ── camera / mic / lidar
                                             │
                                      (network / web dashboard)
                                             │
                                  Off-board GPU machine ("Monster")
                                  SLAM · Nav2 · ZoMa Brain (LLM/TTS/STT)
```

## Repository layout

| Folder | What's in it |
|---|---|
| [`docs/`](docs/) | Architecture, wiring reference, setup instructions, and how to start the AI backend — start here |
| [`esp32_rx/`](esp32_rx/) | Firmware for the ESP32 that drives the motors, reads the encoders/IMU, and talks to the Pi over micro-ROS |
| [`esp32_tx/`](esp32_tx/) | Firmware for the ESP32 that pairs with a PS5 controller and relays drive commands over ESP-NOW |
| [`pi/`](pi/) | Raspberry Pi–side scripts: audio streaming, the LED status ring client, mic-array control |
| [`monster/`](monster/) | The off-board AI backend — ZoMa Brain: speech recognition, the LLM engine, vision, memory, and text-to-speech |
| [`web/`](web/) | The browser dashboard: live camera feed with a HUD overlay, and a chat interface into ZoMa Brain |
| [`mechanical/`](mechanical/) | CAD and cut files for the acrylic chassis |

## Where to start

1. **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — the mechanical and
   electrical design, and how the software stack fits together. Read this first.
2. **[docs/WIRE_CONNECTIONS.md](docs/WIRE_CONNECTIONS.md)** — a flat pin-by-pin
   wiring reference for every connection in the build.
3. **[docs/SETUP.md](docs/SETUP.md)** — the development environment for each
   component (firmware toolchain, Pi software, the GPU backend) and how to build
   your own copy.
4. **[docs/STARTUP_GUIDE.md](docs/STARTUP_GUIDE.md)** — how to actually launch
   the ZoMa Brain server and its dependencies, with the full CLI reference.

If you're new to the project, reading those four in order will take you from "what
is this robot" to "I have it running."

---

*ZoMa is property of TheMechanics. Contact: mamau.mechanics@gmail.com*
