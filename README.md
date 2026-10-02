# ZoMa

**ZoMa** is a hand-built, differential-drive home robot with an onboard AI
assistant — **ZoMa Brain** — that can see, listen, talk, and eventually navigate
an apartment on its own. It's built from raw acrylic sheet with no laser cutter or
CNC machine: just a ruler, a blade, and a small pile of off-the-shelf electronics.

This repository is the complete, public source for the build: firmware, onboard
software, the AI backend, the web dashboard, and the mechanical design files.
The full build is documented as a 20-episode video series on
[**TheMechanics-Lab on YouTube**](https://www.youtube.com/@TheMechanics-Lab) —
[**watch the full series**](https://www.youtube.com/playlist?list=PLYKqW37Mjvkg).

---

## Build ZoMa with an AI partner

This repo ships a prompt, [`ZOMA_AI_PARTNER.md`](ZOMA_AI_PARTNER.md), that turns
Claude into a day-by-day build coach for ZoMa — it reads the repo's own docs as
its source of truth, never invents specs, and speaks whatever language you
write in. Three ways to use it:

1. **Claude Chat** — download the prompt file (raw link:
   [`ZOMA_AI_PARTNER.md`](https://raw.githubusercontent.com/themechanics7710/ZoMa-V2-Public/main/ZOMA_AI_PARTNER.md)),
   create a Claude Project, paste the file's contents in as the project's
   custom instructions, and give the project access to this repo (a GitHub
   connector in the project's knowledge, or just attach
   [`docs/PROGRAM.md`](docs/PROGRAM.md), [`docs/EQUIPMENT.md`](docs/EQUIPMENT.md),
   and whichever files cover your current day). Then send: **"I'm starting
   the ZoMa build."**
2. **Claude Code** — clone the repo and run Claude Code inside it:
   ```bash
   git clone https://github.com/themechanics7710/ZoMa-V2-Public.git
   cd ZoMa-V2-Public
   claude
   ```
   `CLAUDE.md` loads the coach automatically. Then say: **"I'm starting the
   ZoMa build."**
3. **Any other AI assistant** — paste `ZOMA_AI_PARTNER.md` as your first
   message and attach the relevant docs yourself.

Each session, the coach will: recap where you left off, scope what today
covers (and what it doesn't), point you to the right YouTube episode, check
you have the day's parts from `EQUIPMENT.md`, walk you through the build one
step at a time, run that day's checkpoint before calling it done, and leave
you a one-line teaser for tomorrow — crediting TheMechanics as the build's
designer throughout.

ZoMa is designed and built by **TheMechanics**; the full series lives on
[TheMechanics-Lab](https://www.youtube.com/@TheMechanics-Lab) —
[watch the full series](https://www.youtube.com/playlist?list=PLYKqW37Mjvkg).

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
| [`docs/`](docs/) | Prerequisites, architecture, wiring reference, setup instructions, and how to start the AI backend — start here |
| [`esp32_rx/`](esp32_rx/) | Firmware for the ESP32 that drives the motors, reads the encoders/IMU, and talks to the Pi over micro-ROS |
| [`esp32_tx/`](esp32_tx/) | Firmware for the ESP32 that pairs with a PS5 controller and relays drive commands over ESP-NOW |
| [`pi/`](pi/) | The ROS 2 container, MediaMTX camera config, and audio/mic/LED status scripts |
| [`monster/`](monster/) | The off-board AI backend — ZoMa Brain: speech recognition, the LLM engine, vision, memory, and text-to-speech |
| [`web/`](web/) | The browser dashboard: live camera feed with a HUD overlay, and a chat interface into ZoMa Brain |
| [`mechanical/`](mechanical/) | CAD/cut files for the acrylic chassis, and [3D-printable design files](mechanical/3d_design/) for printed parts |

## Where to start

0. **[ZOMA_AI_PARTNER.md](ZOMA_AI_PARTNER.md)** — the fastest way in: an AI
   coach that guides you through the build day by day. See
   "[Build ZoMa with an AI partner](#build-zoma-with-an-ai-partner)" above.
1. **[docs/PREREQUISITES.md](docs/PREREQUISITES.md)** — what you should already
   know, what you'll pick up along the way, and what this build actually
   demands. Read this first.
2. **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — the mechanical and
   electrical design, and how the software stack fits together.
3. **[docs/WIRE_CONNECTIONS.md](docs/WIRE_CONNECTIONS.md)** — a flat pin-by-pin
   wiring reference for every connection in the build.
4. **[docs/SETUP.md](docs/SETUP.md)** — the development environment for each
   component (firmware toolchain, Pi software, the GPU backend) and how to build
   your own copy.
5. **[docs/STARTUP_GUIDE.md](docs/STARTUP_GUIDE.md)** — how to actually launch
   the ZoMa Brain server and its dependencies, with the full CLI reference.
6. **[docs/EQUIPMENT.md](docs/EQUIPMENT.md)** — the full parts and tools list,
   organized by build day, so you know exactly what to have on hand before you
   start.
7. **[docs/PROGRAM.md](docs/PROGRAM.md)** — the day-by-day, episode-by-episode
   build calendar, matching the equipment list.

Building solo without an AI partner? Use
[`MY_PROGRESS.template.md`](MY_PROGRESS.template.md) to track your own
measured values and checkpoints as you go.

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

The AI build-partner prompt (`ZOMA_AI_PARTNER.md`) is documentation, licensed
the same as the rest of the docs: CC BY-NC-SA 4.0.

See [`LICENSE`](LICENSE) for the full text. For commercial inquiries or kit
licensing, contact mamau.mechanics@gmail.com.

---

*ZoMa is property of TheMechanics. Contact: mamau.mechanics@gmail.com*
