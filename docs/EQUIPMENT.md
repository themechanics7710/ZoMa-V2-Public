# ZoMa — Equipment List by Build Day

Every part, tool and consumable used to build ZoMa, grouped by the **20-day build calendar**. The build is published as a video series whose episode numbers don't map 1:1 to build days, so follow the day headings here rather than episode numbers.

The reasoning behind most choices lives in [`ARCHITECTURE.md`](ARCHITECTURE.md) and [`WIRE_CONNECTIONS.md`](WIRE_CONNECTIONS.md). Days 1–8 are built and fully specified; Days 9–20 list planned hardware and will firm up as each day is built.

3D-printable design files (the TX case, chassis edge profiles, brackets, and mast cap referenced below) live in [`mechanical/3d_design/`](../mechanical/3d_design/).

**Legend**
- ✅ Confirmed on the robot
- 🟡 Planned or proposed — not installed yet
- ⚠️ Detail still to confirm (model, value or quantity)
- 🔁 Reused from an earlier day
- 💡 Engineering note — read before you buy or wire

---

## Workshop Tools (reused across the build)

| Tool | First used | Notes |
|---|---|---|
| Green cutting mat | Day 1 | Mechanical / fabrication work |
| Black silicone soldering mat | Day 3 | Electronics work from Day 3 onward |
| Metal ruler | Day 1 | Straight cuts and measuring |
| Manual acrylic cutter (scoring knife) | Day 1 | All straight cuts — no laser, no CNC |
| Coping saw | Day 1 | Rounded corners |
| Drill + bits | Day 1 | Mounting holes, battery case, switch, pillars ⚠️ bit sizes |
| Wet/dry sandpaper, multiple grits | Day 1 | Mast edges ⚠️ grit sequence |
| 3D printer | Day 1 | Edge profiles, caps, brackets, transmitter case |
| Screwdrivers (incl. small precision) | Day 1 | Assembly, buck-converter trimpots |
| Tweezers | Day 2 | Holding nuts in tight spots |
| Bubble level | Day 2 | Two-axis level check of the drive base |
| Bench power supply (Wanptek) | Day 2 | First motor spin test |
| Soldering iron (Pinecil) | Day 3 | Run at 320 °C |
| Digital multimeter (voltage + continuity) | Day 3 | Every power stage is measured before anything is connected to it |
| Lighter or heat gun | Day 3 | Heat shrink |
| Hot glue gun | Day 3 | Insulation, strain relief, LED diffuser |
| Hobby knife | Day 8 | Trimming glue flush |
| Tape measure / floor ruler (~2 m) | Day 7 | Odometry runs |
| Computer with VS Code + PlatformIO + Git | Day 4 | Firmware push → pull → flash workflow |
| Fusion 360 (CAD) | Day 8 | Transmitter case design |

---

## CHAPTER 1 — THE BODY

### Day 1 — Building the Physical Skeleton

**Materials**

| Item | Qty | Spec | Status |
|---|---|---|---|
| Black acrylic sheet | 1 | 3 mm, 30×30 cm finished — bottom / drive deck | ✅ |
| Clear acrylic sheet | 1 | 3 mm, 30×30 cm finished — top / compute deck | ✅ |
| Clear acrylic panels | 4 | Rectangular, form the camera mast | ✅ ⚠️ dimensions |
| Mast base | 1 | Joins mast to top deck | ✅ ⚠️ material |
| Pillars | 6 | Join the decks; screwed to top now, glued to bottom after wiring | ✅ ⚠️ length/type |
| Standoffs | — | Bottom deck | ✅ ⚠️ size & qty |
| Screws / nuts | — | Deck and mast assembly | ⚠️ sizes & qty |
| 3D-printed edge profiles | — | Clean up every hand-cut edge | ✅ — design files in [`mechanical/3d_design/`](../mechanical/3d_design/) |
| 3D-printed mast cap | 1 | Top of mast; camera bracket mounts here later | ✅ |
| Front + rear bumpers | 2 | Protection + a second structural link between decks | ✅ ⚠️ material |
| Foam | — | Under-deck battery bay | ✅ ⚠️ type |

**Consumables**

| Item | Notes |
|---|---|
| Cut layout drawn on the acrylic's protective film | 30×30 cm is bigger than standard paper, so lines go straight onto the film |
| Pencil / marker | Layout |
| Two-part epoxy | Repairing a mis-cut switch opening |
| Water | Wet sanding |

**Cutouts made today (for later parts):** battery case holes, wheel-support holes, power-switch hole, motor-wire pass-through, trapezoid wheel wells, top-deck central cable cutout, mast camera-wire hole, 2 rear mast slots reserved for lidar.

💡 **Battery first, everything else around it.** The battery is the heaviest single part, so its position (centered, low, bottom deck) is fixed first and every other component is placed around it. That keeps the center of gravity predictable.

---

### Day 2 — Giving the Robot Wheels

| Item | Qty | Spec | Status |
|---|---|---|---|
| Omniwheel (front, free-spinning) | ⚠️ 1 or 2 | 48 mm | ✅ ⚠️ qty |
| Omniwheel support bracket | 1 per omniwheel | Screwed to drive base | ✅ |
| M3 axle bolt | 1 per omniwheel | 50 mm used — **40 mm recommended** | ✅ |
| Flanged bearings | 2 per omniwheel | One each side of the wheel | ✅ ⚠️ size |
| M3 washer | 1 per omniwheel | | ✅ |
| M3 nyloc (self-locking) nut | 1 per omniwheel | | ✅ |
| Rear drive wheels | 2 | 65 mm nominal | ✅ |
| Rear wheel supports | 2 | Screwed to drive base | ✅ |
| JGB37-520 DC gear motor with Hall encoder | 2 | 6 V, 200 RPM, 6 mm D-shaft, 6-wire (see below) | ✅ |
| Motor mounting brackets | 2 | Included with the JGB37-520 kit | ✅ |
| Brass shaft hubs | 2 | 6 mm bore to match the D-shaft | ✅ |
| Silicone spray | — | Axle lubrication | ✅ |

**Encoder motor wire colors** (checked on the actual motors — don't trust a generic diagram):

| Wire | Pin | Function |
|---|---|---|
| Red | M1 | Motor power |
| White | M2 | Motor power |
| Black | GND | Encoder ground |
| Blue | VCC | Encoder power |
| Green | C1 | Encoder phase A |
| Yellow | C2 | Encoder phase B |

Minimum **5 cm** clearance between the bottom deck and the floor — enough to cross apartment carpet transitions without snagging.

---

### Day 3 — The Power Problem

| Item | Qty | Spec | Status |
|---|---|---|---|
| LiPo battery (Zeee) | 1 | 2S, 7.4 V nominal / 8.4 V full, 5200 mAh | ✅ |
| Battery case | 1 | Mounted centered on bottom deck | ✅ |
| Battery connector | 1 | Match the plug on your battery's lead | ✅ ⚠️ type |
| WAGO lever connectors | 2+ | 1-in / 5-out ground; separate positive | ✅ ⚠️ model |
| Power switch | 1 | Mounts in the Day 1 cutout, faces the floor | ✅ ⚠️ model |
| 3D-printed switch cover | 1 | | ✅ |
| Perfboard | 1 | Capacitor bank / buffer station | ✅ ⚠️ size |
| Ceramic capacitors | ~6 | 0.1 µF | ✅ |
| Electrolytic capacitors | — | 470 µF (most branches) | ✅ ⚠️ voltage rating & qty |
| Electrolytic capacitor | 1 | 1000 µF (motor branch) | ✅ ⚠️ voltage rating |
| Perfboard standoffs | — | | ✅ ⚠️ size |
| LM2596 buck converter | 2 | #1 motor branch, #2 ESP32 branch | ✅ |
| Buck converter for Raspberry Pi 4 | 1 | Must supply 5.1 V at ≥3 A | ✅ ⚠️ model |
| UBEC | 1 | Lidar branch — installed now, lidar comes later | ✅ ⚠️ model |
| Hookup wire, red/black + branch colors | — | | ✅ ⚠️ gauge & branch colors |
| Bare jumper wire | — | Perfboard rails (6 pairs) | ✅ |

**Consumables:** 0.6 mm solder, assorted heat shrink, hot glue.

💡 **Rate for 8.4 V, not 7.4 V.** A "7.4 V" 2S pack reads 8.4 V when fully charged. Any capacitor on the battery side should be rated **16 V or higher** to keep a safe margin.

💡 **Capacitors buffer spikes — they don't add current.** The bank smooths short bursts (motor start, Wi-Fi transmit), but it can't make a regulator deliver more sustained current than it's rated for. Size the regulators for the steady load first.

💡 **Separate the motor domain from the sensors.** The motor driver gets its own buck and its own ground return path, away from the IMU's supply. Motor PWM switching is a known noise source; separating it at design time beats filtering later.

---

### Day 4 — Bringing the Microchip to Life

| Item | Qty | Spec | Status |
|---|---|---|---|
| ESP32 dev board (receiver / "RX") | 1 | ESP32-WROOM-32 class (PlatformIO board `esp32dev`) | ✅ ⚠️ exact board |
| ESP32 breakout / carrier board | 1 | Mounted on bottom deck | ✅ |
| Ceramic capacitor | 1 | Local high-frequency filtering | ✅ |
| Electrolytic capacitor | 1 | 470 µF, local reserve | ✅ |
| Reverse-protection diode | 1 | Recommended | ⚠️ part number |
| Breadboard | 1 | Test rig | ✅ |
| Blue LED | 1 | Blink test | ✅ |
| Current-limiting resistor | 1 | Typically 220–330 Ω | ✅ ⚠️ value used |
| USB-C cable | 1 | Flashing | ✅ |

**Setup:** ESP32 buck trimmed from 7.79 V → 5.1–5.2 V.

💡 **Why the buck read 7.79 V at first.** An LM2596 module isn't preset — until you turn its trimpot, the output sits close to the input voltage. Always trim with a multimeter **before** connecting a load.

---

### Day 5 — Connecting Brain to Wheels

| Item | Qty | Spec | Status |
|---|---|---|---|
| DRV8833 dual motor driver breakout | 1 | Powered from the dedicated motor buck | ✅ |
| Electrolytic capacitor | 1 | Across driver power rails | ✅ ⚠️ value |
| Jumper wires | — | Buck → driver, encoders → ESP32 GPIO | ✅ |

**Setup:** motor buck trimmed from 7.75 V → 6.0 V. ESP32 GND and motor-buck GND both land on the driver's GND pin.

💡 **Check your board, not the generic datasheet.** This DRV8833 breakout has **no separate VM pin** — VCC powers both the logic and the motor outputs. Its J1 solder jumper ties nSLEEP to VCC, so the driver wakes whenever the motor rail is on (continuity-test J1 before first power-up).

💡 **Shared ground is not optional.** The PWM signals from the ESP32 only mean something relative to a common ground. Without the ESP32 GND wire to the driver, the motors can behave unpredictably even with the driver powered.

---

### Day 6 — Chasing a Straight Line

| Item | Qty | Spec | Status |
|---|---|---|---|
| Red floor tape | 1 roll | Straight reference line | ✅ |

**Result:** 82% duty (210/255), `RIGHT_TRIM = 1.00`, `LEFT_TRIM = 1.0097`.

---

### Day 7 — Measuring Every Millimeter

| Item | Qty | Spec | Status |
|---|---|---|---|
| Floor ruler / tape measure | 1 | ~2 m | ✅ |
| Reference mark on the tire | — | For one-revolution tick counts | ✅ |

**Result:** **5.754 ticks/mm**, averaged over measured floor runs ✅ — this is the number the odometry uses.

Derived values still being reconciled ⚠️: ticks per wheel revolution (~1,330 from a hand-spin vs ~1,247 from the floor cross-check) and effective wheel diameter (~69 mm from the floor number — a diameter, not a circumference).

💡 **Calibrate on the floor, under load.** A wheel spun by hand or in the air doesn't behave like one carrying the robot. The distance constant is measured by driving a known distance on the real floor; ticks/rev and diameter are only intermediate numbers.

---

## CHAPTER 2 — THE NERVOUS SYSTEM

### Day 8 — Linking a PlayStation Controller (Transmitter build)

| Item | Qty | Spec | Status |
|---|---|---|---|
| PlayStation 5 DualSense controller | 1 | Bluetooth | ✅ |
| ESP32 board with U.FL antenna connector (transmitter / "TX") | 1 | USB-C, original ESP32 (Bluetooth Classic + ESP-NOW) | ✅ ⚠️ model |
| External antenna + U.FL pigtail | 1 | Brass bulkhead connector through rear panel | ✅ ⚠️ SMA vs RP-SMA, gain |
| Addressable RGB LED ring | 1 | 12 LEDs, 3-wire (5 V / GND / data) — link status | ✅ ⚠️ model |
| Resistor, inline on the LED data line | 1 | Reduces signal ringing | ✅ ⚠️ value |
| TP4056 charger module | 1 | USB-C | ✅ |
| LiPo pouch battery | 1 | 1S, 3.7 V | ✅ ⚠️ capacity |
| Boost converter | 1 | 3.7 V → 5 V | ✅ ⚠️ model |
| Rocker switch | 1 | Master cutoff | ✅ |
| Double-sided adhesive strip | — | Under the ESP32 | ✅ |
| 3D-printed case | 1 set | Deck, walls, lid, front faceplate | ✅ — design files in [`mechanical/3d_design/`](../mechanical/3d_design/) |

**Consumables:** yellow heat shrink, parchment paper, hot glue (diffuser + insulation), solder.

⚠️ **The boost converter ships set to 12 V.** Desolder its jumper to select 5 V **before** connecting anything to it.

💡 **Not every ESP32 can pair a PS5 controller.** The DualSense uses Bluetooth Classic, which only the original ESP32 has. The ESP32-S2, S3, C3 and C6 have BLE only (or no Bluetooth) and won't work here.

💡 **TP4056 is a charger, not a fuel gauge.** Its two status pins only say "charging" or "done" — they can't report how much charge is left.

---

### Days 9–10 — Cutting the Cord & Taking the Wheel

ESP-NOW link between the Day 8 transmitter and the robot's ESP32, then first manual drives.

| Item | Qty | Spec | Status |
|---|---|---|---|
| Robot ESP32 as ESP-NOW receiver | — | | 🔁 Day 4 |
| VL53L1X time-of-flight distance sensor | 1 | I2C, plus XSHUT and interrupt lines to the ESP32 — front proximity safety (slows the motors, rather than a hard stop) | ✅ ⚠️ breakout model, confirm build day |
| Floor / corridor space, obstacle course, carpet | — | Drive tests | ✅ |

---

### Days 11–12 — A Sense of Direction

| Item | Qty | Spec | Status |
|---|---|---|---|
| BNO055 absolute orientation sensor (IMU) | 1 | I2C, bottom deck, away from motor wiring, own filtered supply tap | 🟡 ⚠️ breakout model |
| I2C wiring (SDA / SCL / VCC / GND) | — | To the robot ESP32 | 🟡 ⚠️ colors |

💡 **Two sensors, one I2C bus.** The BNO055 and VL53L1X share the bus, so their addresses must differ. Defaults are 0x28 (BNO055) and 0x29 (VL53L1X) — but the BNO055's ADR pin can move it to 0x29, so make sure ADR stays low.

---

### Day 13 — Installing the Onboard Computer & Eyes

| Item | Qty | Spec | Status |
|---|---|---|---|
| Raspberry Pi 4 | 1 | Top deck, powered by the Day 3 Pi buck | 🟡 ⚠️ RAM size |
| microSD card | 1 | OS | 🟡 ⚠️ size |
| Pi camera module | 1 | Wide-angle, front-facing on top of the mast | 🟡 ⚠️ model |
| Camera ribbon cable | 1 | Through the Day 1 mast camera hole | 🟡 ⚠️ length |
| 3D-printed camera bracket | 1 | Mounts on the mast cap | 🟡 |
| Pi mounting hardware | — | Standoffs / screws | 🟡 ⚠️ |
| Pi 4 cooling (heatsink / fan) | — | | ⚠️ confirm if used |
| Data-only USB cable, ESP32 ↔ Pi | 1 | 5 V (red) wire cut | 🟡 ⚠️ confirm build day |

💡 **Why cut the red wire?** The robot's ESP32 already has its own regulated supply. A normal USB cable would also connect the Pi's 5 V to it, so two supplies would fight over one rail. Cutting only the 5 V wire keeps the data link and removes the conflict.

---

## CHAPTER 3 — THE MIND

### Days 14–16 — Streaming Eyes to a Thinking Mind

| Item | Qty | Spec | Status |
|---|---|---|---|
| Off-board GPU server ("Monster") | 1 | Intel i9, 32 GB RAM, NVIDIA RTX 4080 — local LLM and vision-language model for ZoMa Brain | 🟡 |
| Wi-Fi network | — | Pi ↔ server streaming | 🟡 |

Software only otherwise — video streaming, and the local LLM/vision-language model stack on the server (ZoMa Brain's conversational AI). **This does not include ROS 2 or Nav2** — autonomous SLAM navigation is Season 2 work, not part of this 20-day build; see [Reserved for Season 2](#reserved-for-season-2-not-needed-for-the-20-day-build) below.

---

### Days 17–19 — Teaching ZoMa to Talk and Listen

| Item | Qty | Spec | Status |
|---|---|---|---|
| USB speaker | 1 | Direct to Pi 4 | 🟡 ⚠️ model |
| Microphone array | 1 | Onboard | 🟡 ⚠️ model / interface |

---

### Day 20 — The Final AI Control Station

| Item | Qty | Spec | Status |
|---|---|---|---|
| ZoMa Brain LED ring | 1 | SparkFun LuMini 2" ring, 40× APA102 LEDs, driven from the Pi's hardware SPI — shows listening / thinking / speaking | 🟡 proposed, pending bench test |
| Bulk capacitor at the ring's power pads | 1 | 470–1000 µF | 🟡 ⚠️ value |
| 5 V supply branch for the ring | 1 | Separate from the Pi's supply | 🟡 ⚠️ regulator |
| 3D-printed ring bracket | 1 | 5–8 mm lip for an optional diffuser | 🟡 |

💡 **Why APA102 instead of WS2812 on the Pi.** WS2812 LEDs need a single data line with microsecond-exact timing, which a Linux computer can't guarantee while it's busy with other work. APA102 uses a separate clock line (SPI), so small timing hiccups don't corrupt the colors. It also dims smoothly and flickers less on camera.

💡 **Budget the current.** Each LED can draw up to ~60 mA at full white, so 40 LEDs could pull ~2.4 A. Either size the supply for that or cap the brightness in software.

---

## Reserved for Season 2 (not needed for the 20-day build)

| Item | Notes |
|---|---|
| ROS 2 + Nav2 (autonomous navigation) | Full SLAM/Nav2 stack — lidar-only ICP mapping and path planning. Not implemented yet; this build's Pi and server software stops at streaming, voice, and conversational AI |
| Lidar | Required for the planned lidar-only SLAM. UBEC branch installed on Day 3; mast slots cut on Day 1 |
| New mast with arm | Replaces the current mast |
| 16-channel PWM servo driver board | For the arm; deck space and a dedicated power branch are already reserved |
| Second battery | Same footprint as the first; deck space already reserved |

---

## Still to Confirm

- [ ] All screw, standoff and bearing sizes
- [ ] Front omniwheel count (1 or 2)
- [ ] Branch wire colors (motors / ESP32 / Pi / lidar) and wire gauge
- [ ] Pi 4 buck converter model
- [ ] Mast panel dimensions
- [ ] Capacitor voltage ratings; Day 5 DRV8833 capacitor value
- [ ] Battery connector type; transmitter LiPo capacity
- [ ] Day 7: ticks per wheel revolution and effective wheel diameter
- [ ] Build days for the VL53L1X and the data-only USB cable
- [ ] Models for Day 9–20 parts (ToF breakout, IMU breakout, camera, speaker, mic)
- [ ] 3D design files for all printed parts — add them to [`mechanical/3d_design/`](../mechanical/3d_design/) as they're finalized

---

*ZoMa is property of TheMechanics. Contact: mamau.mechanics@gmail.com*
