# Building ZoMa: The Program

20 build days. 13 episodes. One robot, built from a flat sheet of acrylic.

Some episodes cover two or three build days in a single video. Day numbers always follow the build calendar. See [EQUIPMENT.md](EQUIPMENT.md) for the parts and tools needed on each day.

## Chapter 1: The Body (Days 1-7)

### Episode 1, Day 1: Building the Physical Skeleton
**Watch:** `TODO-URL`

Hand-cut acrylic with a ruler and a blade, no laser or CNC. Assemble the two-deck chassis and raise the vertical mast that becomes ZoMa's spine. No electronics yet.

### Episode 2, Day 2: Giving the Robot Wheels
**Watch:** `TODO-URL`

Install the drive motors, the rear wheels, and the front omniwheel. Then run the first raw spin test on the bench, before any brain and before any code.

### Episode 3, Day 3: The Power Problem
**Watch:** `TODO-URL`

Move from the cutting mat to the soldering station. Build a power distribution system with a capacitor bank and buck converters so every downstream chip gets clean power.

### Episode 4, Day 4: Bringing the Microchip to Life
**Watch:** `TODO-URL`

Mount the ESP32 microcontroller, tune its power, and run the first firmware. One blinking LED means the brain stem works.

### Episode 5, Day 5: Connecting Brain to Wheels
**Watch:** `TODO-URL`

Install the DRV8833 motor driver, wire motor control from the ESP32, and read encoder feedback for the first time.

### Episode 6, Days 6-7: Straight, and Exactly How Far
**Watch:** `TODO-URL`

Trim-tune the two rear motors until ZoMa drives dead straight. Then calibrate the encoders across measured floor runs so distance is accurate to the millimeter.

## Chapter 2: The Nervous System (Days 8-13)

### Episode 7, Day 8: Linking a PlayStation Controller
**Watch:** `TODO-URL`

Build a hand-made wireless transmitter and pair a PS5 DualSense controller to it over Bluetooth for manual control.

### Episode 8, Days 9-10: Cutting the Cord, and Taking the Wheel
**Watch:** `TODO-URL`

Establish a fast ESP-NOW radio link between the transmitter and the robot. Then translate joystick input into wheel commands and take ZoMa on its first manual drive, on the bench and across the floor.

### Episode 9, Days 11-12: A Sense of Direction
**Watch:** `TODO-URL`

Mount a BNO055 orientation sensor and watch live heading data stream in. Then use it for heading lock and exact turns, the difference between a robot that moves and one that navigates.

### Episode 10, Day 13: Installing the Onboard Computer and Eyes
**Watch:** `TODO-URL`

Assemble the top deck, mount the Raspberry Pi 4, and secure the camera on the mast.

## Chapter 3: The Mind (Days 14-20)

### Episode 11, Days 14-16: From Streaming Eyes to a Thinking Mind
**Watch:** `TODO-URL`

Stream live video from the robot, connect it to a local language model running on an off-board GPU, and have the first real-time conversation. Then let it describe what its camera sees.

### Episode 12, Days 17-19: Teaching ZoMa to Talk, and to Listen
**Watch:** `TODO-URL`

Add a speaker and text-to-speech so ZoMa can answer out loud. Then add a microphone and speech-to-text for fully hands-free, spoken conversation.

### Episode 13, Day 20: The Final AI Control Station
**Watch:** `TODO-URL`

Combine live video, sensor telemetry, and voice interaction into a single dashboard, and add an LED ring that shows when ZoMa is listening, thinking, or replying.

## Day-by-day reference

Checkpoints below are derived from the facts already in [EQUIPMENT.md](EQUIPMENT.md) and [WIRE_CONNECTIONS.md](WIRE_CONNECTIONS.md) — not independent specs. Where a day has no matching `WIRE_CONNECTIONS.md` section, none is listed (no wiring table exists for it yet — see the AI Build Partner's report on this for VL53L1X on Days 9–10, which `EQUIPMENT.md` lists as a part but `WIRE_CONNECTIONS.md` doesn't yet have a pin table for).

| Day | Episode | Scope | Done when | Repo material | Docs sections |
|---|---|---|---|---|---|
| 1 | Ep 1 | Hand-cut chassis, two decks, mast, cutouts. No electronics. | Both decks and the mast are assembled, cutouts made, structure is solid. | `mechanical/`, `mechanical/3d_design/` | EQUIPMENT Day 1 |
| 2 | Ep 2 | Drive motors, rear wheels, front omniwheel, first bench spin test. | Both motors spin the wheels on the bench supply; base is level. | `mechanical/` | EQUIPMENT Day 2 |
| 3 | Ep 3 | Battery, switch, WAGO distribution, capacitor bank, buck converters. | Every rail is measured with a multimeter at the right voltage before anything is connected to it. | — | EQUIPMENT Day 3 |
| 4 | Ep 4 | Mount the ESP32, tune its buck, flash first firmware. | The ESP32 runs on its regulated 5 V rail and the test LED blinks. | `esp32_rx/` | EQUIPMENT Day 4, SETUP §2 |
| 5 | Ep 5 | DRV8833 motor driver, motor control from the ESP32, first encoder readings. | The ESP32 drives the motors and encoder ticks are read. | `esp32_rx/` | EQUIPMENT Day 5, WIRE_CONNECTIONS (DRV8833 Motor Driver; Encoders) |
| 6 | Ep 6 (part 1) | Trim-tune the rear motors for a dead-straight drive. | The robot follows the floor tape line straight. | `esp32_rx/` | EQUIPMENT Day 6 |
| 7 | Ep 6 (part 2) | Calibrate encoders over measured floor runs. | You have your own ticks-per-mm number from real floor runs. | `esp32_rx/` | EQUIPMENT Day 7 |
| 8 | Ep 7 | Build the TX transmitter, pair a PS5 DualSense over Bluetooth. | The DualSense pairs with the TX ESP32. | `esp32_tx/`, `mechanical/3d_design/` (TX case) | EQUIPMENT Day 8, WIRE_CONNECTIONS (ESP32 TX Handheld Remote) |
| 9 | Ep 8 (part 1) | ESP-NOW radio link TX → RX. | TX and RX talk over ESP-NOW. | `esp32_tx/`, `esp32_rx/` | EQUIPMENT Days 9–10 |
| 10 | Ep 8 (part 2) | Joystick → wheel commands, first manual drives. | You drive ZoMa with the controller. | `esp32_tx/`, `esp32_rx/` | EQUIPMENT Days 9–10 |
| 11 | Ep 9 (part 1) | Mount the BNO055 orientation sensor, stream live heading. | Live heading data streams in. | `esp32_rx/` | EQUIPMENT Days 11–12, WIRE_CONNECTIONS (IMU BNO055) |
| 12 | Ep 9 (part 2) | Heading lock and exact turns. | The robot holds heading and turns by exact angles. | `esp32_rx/` | EQUIPMENT Days 11–12, WIRE_CONNECTIONS (IMU BNO055) |
| 13 | Ep 10 | Top deck, Raspberry Pi 4, camera on the mast. | Pi boots, camera is secured, data-only USB link to the ESP32 is in. | `pi/`, `pi/mediamtx.yml` | EQUIPMENT Day 13, SETUP §3, STARTUP_GUIDE §1.0–1.2, WIRE_CONNECTIONS (ESP32 RX ↔ Raspberry Pi 4 micro-ROS link) |
| 14 | Ep 11 (part 1) | Live video streaming from the robot. | Video from the robot shows on another machine. | `pi/mediamtx.yml`, `monster/zoma-brain/vision_stream.py` | EQUIPMENT Days 14–16, STARTUP_GUIDE §1.2 |
| 15 | Ep 11 (part 2) | Connect to a local LLM on the off-board GPU machine. | First real-time text conversation works. | `monster/zoma-brain/llm_engine.py`, `monster/zoma-brain/zoma_brain_server.py` | EQUIPMENT Days 14–16, STARTUP_GUIDE §2.2–2.3 |
| 16 | Ep 11 (part 3) | Vision: ZoMa describes what its camera sees. | ZoMa describes a live scene. | `monster/zoma-brain/vision_engine.py` | EQUIPMENT Days 14–16 |
| 17 | Ep 12 (part 1) | Speaker and text-to-speech. | ZoMa answers out loud. | `pi/scripts/zoma-audio-led/zoma_audio_client.py`, `monster/zoma-brain/tts_engine.py` | EQUIPMENT Days 17–19, WIRE_CONNECTIONS (Audio Subsystem), STARTUP_GUIDE §2.1 |
| 18 | Ep 12 (part 2) | Microphone array and speech-to-text. | ZoMa transcribes your voice. | `pi/scripts/zoma-audio-led/zoma_mic_client.py`, `monster/zoma-brain/zoma_brain_server.py` | EQUIPMENT Days 17–19, WIRE_CONNECTIONS (Audio Subsystem) |
| 19 | Ep 12 (part 3) | Fully hands-free spoken conversation. | A full voice conversation works. | `monster/zoma-brain/zoma_brain_server.py` | EQUIPMENT Days 17–19 |
| 20 | Ep 13 | Single dashboard (video, telemetry, voice) + LED ring status. | Dashboard works and the LED ring shows listening / thinking / speaking. | `web/index.html`, `pi/scripts/zoma-audio-led/zoma_state.py`, `pi/scripts/zoma-audio-led/lumini_ring.py` | EQUIPMENT Day 20, WIRE_CONNECTIONS (Status LED Ring APA102) |

## What comes next

Season 2 takes ZoMa from obeying commands to navigating on its own: mapping, planning, and driving autonomously with ROS2.

## Follow along

The full build is released as a video series on [TheMechanics-Lab on YouTube](https://www.youtube.com/@TheMechanics-Lab) — the series is collected in [this playlist](https://www.youtube.com/playlist?list=PLYKqW37Mjvkg).

---

*ZoMa is property of TheMechanics. Contact: mamau.mechanics@gmail.com*
