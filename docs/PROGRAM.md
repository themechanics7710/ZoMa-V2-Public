# Building ZoMa: The Program

20 build days. 13 episodes. One robot, built from a flat sheet of acrylic.

Some episodes cover two or three build days in a single video. Day numbers always follow the build calendar. See [EQUIPMENT.md](EQUIPMENT.md) for the parts and tools needed on each day.

## Chapter 1: The Body (Days 1-7)

### Episode 1, Day 1: Building the Physical Skeleton
Hand-cut acrylic with a ruler and a blade, no laser or CNC. Assemble the two-deck chassis and raise the vertical mast that becomes ZoMa's spine. No electronics yet.

### Episode 2, Day 2: Giving the Robot Wheels
Install the drive motors, the rear wheels, and the front omniwheel. Then run the first raw spin test on the bench, before any brain and before any code.

### Episode 3, Day 3: The Power Problem
Move from the cutting mat to the soldering station. Build a power distribution system with a capacitor bank and buck converters so every downstream chip gets clean power.

### Episode 4, Day 4: Bringing the Microchip to Life
Mount the ESP32 microcontroller, tune its power, and run the first firmware. One blinking LED means the brain stem works.

### Episode 5, Day 5: Connecting Brain to Wheels
Install the DRV8833 motor driver, wire motor control from the ESP32, and read encoder feedback for the first time.

### Episode 6, Days 6-7: Straight, and Exactly How Far
Trim-tune the two rear motors until ZoMa drives dead straight. Then calibrate the encoders across measured floor runs so distance is accurate to the millimeter.

## Chapter 2: The Nervous System (Days 8-13)

### Episode 7, Day 8: Linking a PlayStation Controller
Build a hand-made wireless transmitter and pair a PS5 DualSense controller to it over Bluetooth for manual control.

### Episode 8, Days 9-10: Cutting the Cord, and Taking the Wheel
Establish a fast ESP-NOW radio link between the transmitter and the robot. Then translate joystick input into wheel commands and take ZoMa on its first manual drive, on the bench and across the floor.

### Episode 9, Days 11-12: A Sense of Direction
Mount a BNO055 orientation sensor and watch live heading data stream in. Then use it for heading lock and exact turns, the difference between a robot that moves and one that navigates.

### Episode 10, Day 13: Installing the Onboard Computer and Eyes
Assemble the top deck, mount the Raspberry Pi 4, and secure the camera on the mast.

## Chapter 3: The Mind (Days 14-20)

### Episode 11, Days 14-16: From Streaming Eyes to a Thinking Mind
Stream live video from the robot, connect it to a local language model running on an off-board GPU, and have the first real-time conversation. Then let it describe what its camera sees.

### Episode 12, Days 17-19: Teaching ZoMa to Talk, and to Listen
Add a speaker and text-to-speech so ZoMa can answer out loud. Then add a microphone and speech-to-text for fully hands-free, spoken conversation.

### Episode 13, Day 20: The Final AI Control Station
Combine live video, sensor telemetry, and voice interaction into a single dashboard, and add an LED ring that shows when ZoMa is listening, thinking, or replying.

## What comes next

Season 2 takes ZoMa from obeying commands to navigating on its own: mapping, planning, and driving autonomously with ROS2.

## Follow along

The full build is released as a video series on [TheMechanics-Lab on YouTube](https://www.youtube.com/@TheMechanics-Lab).

---

*ZoMa is property of TheMechanics. Contact: mamau.mechanics@gmail.com*
