# ZoMa

**ZoMa** is a hand-built, differential-drive home robot with an onboard AI
assistant — **ZoMa Brain** — that can see, listen, talk, and eventually navigate
an apartment on its own. It's built from raw acrylic sheet with no laser cutter or
CNC machine: just a ruler, a blade, and a small pile of off-the-shelf electronics.

This repository is the complete, public source for the build: firmware, onboard
software, the AI backend, the web dashboard, and the mechanical design files.
The full build is documented as a 20-episode video series on
[**TheMechanics-Lab on YouTube**](https://www.youtube.com/@TheMechanics-Lab).

---

## What ZoMa does

- **Sees and hears** through an onboard camera and a far-field microphone array,
  streamed to an off-board GPU machine for real-time processing.
- **Talks back** with a voice pipeline (speech-to-text → LLM → text-to-speech)
  that supports interrupting it mid-sentence, and a tiered inference system —
  instant canned replies for simple things, a fast local model for everyday
  conversation, and a larger model for anything that needs deeper reasoning.
- **Shows its state** through a 40-LED ring (SparkFun LuMini, APA102) that lights
  up differently depending on whether it's listening, thinking, or speaking — so
  interacting with it feels less like talking to a black box.
- **Drives manually** too, over a PS5 DualSense controller paired to a dedicated
  ESP32 transmitter, relayed to the robot over a low-latency ESP-NOW link.

It's built with room to grow: the chassis reserves space and power for a second
battery and a robotic arm, without needing a redesign. Autonomous navigation
(lidar-based SLAM + Nav2 path planning, over ROS 2) is planned for a second
build season and isn't implemented yet — see
[docs/EQUIPMENT.md](docs/EQUIPMENT.md).

## How the robot is put together

At a glance: two ESP32 microcontrollers handle real-time control (driving the
motors, reading the encoders and IMU, receiving the controller input), a
Raspberry Pi 4 handles onboard I/O (camera, microphone array, and talking to the
ESP32s over micro-ROS), and an off-board machine with a GPU does the heavy
lifting for AI (speech recognition, the language model, vision, and text-to-speech).
A browser-based dashboard ties the camera feed and a chat interface together.

```
Controller (PS5) ─▶ ESP32 TX ─ESP-NOW─▶ ESP32 RX ─▶ motors / encoders / IMU
                                             │
                                        micro-ROS (USB serial)
                                             │
                                       Raspberry Pi 4 ── camera / mic array
                                             │
                                      (network / web dashboard)
                                             │
                                  Off-board GPU machine ("Monster")
                                    ZoMa Brain (LLM/TTS/STT)
                              (SLAM · Nav2 planned — Season 2)
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
| [`mechanical/`](mechanical/) | CAD/cut files for the acrylic chassis, and [3D-printable design files](mechanical/3d_design/) for printed parts |

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
5. **[docs/EQUIPMENT.md](docs/EQUIPMENT.md)** — the full parts and tools list,
   organized by build day, so you know exactly what to have on hand before you
   start.

If you're new to the project, reading those in order will take you from "what
is this robot" to "I have it running."

ZoMa was built and documented as a 20-day build, released as a video series on
[TheMechanics-Lab](https://www.youtube.com/@TheMechanics-Lab). ROS 2 and Nav2 —
autonomous SLAM navigation — are planned for a second season and aren't part of
this build.

## License

Hardware, CAD, 3D-printable designs, and documentation
(`mechanical/`, `docs/`) are licensed under
[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) —
personal/educational use and remixing only, no commercial use.

Software and firmware (`esp32_tx/`, `esp32_rx/`, `pi/`, `monster/`, `web/`)
are licensed under [GPL v3](https://www.gnu.org/licenses/gpl-3.0.html).

See [`LICENSE`](LICENSE) for the full text. For commercial inquiries or kit
licensing, contact mamau.mechanics@gmail.com.

---

*ZoMa is property of TheMechanics. Contact: mamau.mechanics@gmail.com*
