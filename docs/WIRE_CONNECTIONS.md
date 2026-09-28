# ZoMa — Wire Connections (Quick Reference)

Flat pinout/wiring lookup table for the whole build. See
[ARCHITECTURE.md](ARCHITECTURE.md) for the rationale behind each connection.

---

## ESP32 RX ↔ Raspberry Pi 4 (micro-ROS link)

The RX board's onboard USB port connects to the Raspberry Pi with a **data-only**
USB cable (the cable's power wire is cut, so the Pi doesn't also try to power the
board). micro-ROS runs over this USB-serial connection at 921600 baud — no separate
GPIO wiring is needed for this link.

---

## IMU (BNO055, I2C) ↔ ESP32 RX

| BNO055 Pin | ESP32 Pin | Wire Color | Notes                     |
| ---------- | --------- | ---------- | ------------------------- |
| Vin        | 3V3       | Red        | Sensor logic power (3.3V) |
| GND        | GND       | Black      | Common ground             |
| SDA        | GPIO21    | Green      | I2C data line             |
| SCL        | GPIO22    | Yellow     | I2C clock line            |

---

## DRV8833 Motor Driver

### Logic Control Inputs (ESP32 RX → DRV8833)

| ESP32 RX GPIO | DRV8833 Pin | Function                                              |
| ------------- | ----------- | ------------------------------------------------------ |
| GPIO27        | IN1         | Right motor, PWM channel 1                             |
| GPIO26        | IN2         | Right motor, PWM channel 2                              |
| GPIO32        | IN3         | Left motor, PWM channel 1                               |
| GPIO33        | IN4         | Left motor, PWM channel 2                               |
| GND           | GND         | Shared ground reference (also carries LM2596 #1 OUT−)  |

*PWM: 5 kHz, 8-bit resolution, one LEDC channel per IN pin (4 channels total).*

### Power & Jumper Connections

| Source                      | Wire Color | DRV8833 Pin | Note                                                 |
| ---------------------------- | ---------- | ----------- | ----------------------------------------------------- |
| LM2596 #1 (motor rail) OUT+ | Red        | VCC         | Single combined pin — powers logic AND motor outputs |
| LM2596 #1 (motor rail) OUT− | Black      | GND         | Common ground — also receives ESP32 GND              |

- `nSLEEP`: tied high via the board's on-board J1 jumper to VCC (not GPIO-controlled).
- `nFAULT`: left unconnected.

### Motor Outputs (DRV8833 → Motors)

| Motor | Wire | Color | DRV8833 Pin |
| ----- | ---- | ----- | ----------- |
| Right | M1   | Red   | OUT1        |
| Right | M2   | White | OUT2        |
| Left  | M1   | Red   | OUT3        |
| Left  | M2   | White | OUT4        |

---

## Encoders

### Motor-Side Wiring

| Motor Pin | Wire Color (Actual) | Function                           |
| --------- | -------------------- | ----------------------------------- |
| M1        | Red                  | Motor drive power (to DRV8833 OUT) |
| GND       | Black                 | Encoder ground reference           |
| C2        | Yellow                | Encoder phase B signal             |
| C1        | Green                 | Encoder phase A signal             |
| VCC       | Blue                  | Encoder logic power (3.3V / 5V)    |
| M2        | White                 | Motor drive power (to DRV8833 OUT) |

### ESP32 RX Wiring — Encoder (Hardware Pulse Counters)

| Motor | Wire        | ESP32 GPIO | Hardware Counter Unit                      |
| ----- | ----------- | ---------- | -------------------------------------------- |
| Right | C1 (Green)  | GPIO35     | Counter unit 0, channel A (input-only pin)  |
| Right | C2 (Yellow) | GPIO34     | Counter unit 0, channel B (input-only pin)  |
| Left  | C1 (Green)  | GPIO18     | Counter unit 1, channel A                    |
| Left  | C2 (Yellow) | GPIO19     | Counter unit 1, channel B                    |

Encoders use hardware quadrature (x4) decoding — real A/B phase outputs give
direction natively, without needing to infer direction from commanded motor sign.

---

## ESP32 TX (Handheld Remote)

- **MCU:** ESP32 DevKit (Micro-USB, external IPEX/U.FL antenna connector)
- **Connectivity:** PS5 DualSense pairing over Bluetooth Classic; drive/telemetry
  link to ESP32 RX over ESP-NOW.

### Hardware & Power Components

- **Battery:** 3.7V 1000mAh 603048 LiPo (2-wire)
- **Charger:** TP4056 Type-C USB 5V 1A Li-ion charge controller with dual protection
- **Boost Converter:** DC-DC step-up converter (3.7V to 5V)
- **Status Ring:** WS2812B 5V addressable RGB LED ring, 12 LEDs, 16 mm diameter

### Power Distribution & Wiring

| Source           | Destination    | Wire Color | Function / Note                           |
| ----------------- | -------------- | ---------- | ------------------------------------------- |
| Battery (+)      | TP4056 B+      | Red        | Battery positive input                    |
| Battery (−)      | TP4056 B−      | Black      | Battery negative input                    |
| TP4056 OUT+      | Boost IN+      | Red        | Protected battery rail (via power switch) |
| TP4056 OUT−      | Boost IN−      | Black      | Common circuit ground reference           |
| Boost OUT+ (5V)  | ESP32 5V (VIN) | Red        | 5V system supply rail                     |
| Boost OUT+ (5V)  | WS2812B 5V     | Red        | 5V power rail for LED ring                |
| Boost OUT− (GND) | ESP32 GND      | Black      | Common ground                             |
| Boost OUT− (GND) | WS2812B GND    | Black      | Common ground                             |

### Status LED Ring Wiring

| WS2812B Pin  | ESP32 Pin | In-Line Component | Wire Color    | Notes                                    |
| ------------- | --------- | ------------------ | -------------- | ------------------------------------------ |
| DI (Data In) | GPIO32    | 220Ω Resistor      | Green / White | In-line damping resistor on data line     |
| 5V           | Boost OUT+ (5V) | —            | Red            | Dedicated 5V power tap                   |
| GND          | Common GND | —                  | Black          | Signal & power return path               |

GPIO32 was chosen because it's not a strapping pin, not UART0, and not input-only.

---

## Audio Subsystem (Pi 4 ↔ ReSpeaker XVF3800 ↔ Mono Speaker)

- **Host Controller:** Raspberry Pi 4
- **Voice & Audio Interface:** Seeed Studio ReSpeaker USB (XMOS XVF3800 DSP array)
- **Speaker Transducer:** Seeed Studio Mono Enclosed Speaker — 4Ω 5W (SKU: 114993346)

### Interconnects & Signal Path

| From                        | To                 | Interface / Cable    | Notes                                                                |
| ---------------------------- | ------------------ | ---------------------- | ------------------------------------------------------------------------ |
| Raspberry Pi 4              | ReSpeaker XVF3800  | USB-C to USB-A Cable | USB UAC 2.0 digital audio input/output, AEC reference, and bus power |
| ReSpeaker XVF3800 (SPK Out) | Seeed Mono Speaker | 2-pin JST (~400 mm)  | On-board Class-D audio amplifier output to mono enclosed speaker     |

### Speaker Hardware Specifications (Seeed 114993346)

- **Rated Impedance:** 4Ω ± 15%
- **Power Handling:** 5W rated (6W peak / max)
- **Frequency Range:** ~450 Hz (Fo ± 20%) to 20 kHz
- **Termination:** ~400 mm lead terminated with 2-pin JST connector

### Mechanical & Mounting Dimensions

- **Overall Footprint (L × W × H):** 70.0 mm × 31.0 mm × 16.0 mm
- **Mounting Hole Spacing (Pitch):** 63.5 mm (lengthwise center-to-center) ×
  24.5 mm (widthwise center-to-center)
- **Mounting Hole Diameter:** ~3.2 mm (clearance for standard M3 screws)

---

## Status LED Ring (APA102) ↔ Raspberry Pi 4 / 5A Buck

- **Controller / Bus:** Raspberry Pi 4 hardware SPI0 (`GPIO10` / `GPIO11`)
- **Power Source:** 5V 5A buck converter (direct parallel tap, shared with Pi 4)
- **Buffering:** 470µF electrolytic capacitor across the ring's 5V and GND pads

### Wiring Details

| Ring Pin | Connected To          | Wire Color | Function / Notes                                            |
| --------- | ---------------------- | ---------- | -------------------------------------------------------------- |
| **5V**   | 5A Buck OUT+           | Red        | 5V rail tap; 470µF cap (+) leg placed across 5V/GND          |
| **GND**  | 5A Buck OUT−           | Black      | Common power return; 470µF cap (−) leg placed across 5V/GND |
| **DI**   | Pi 4 GPIO 10 (Pin 19)  | Green      | SPI0_MOSI (direct connection, 3.3V logic)                    |
| **CI**   | Pi 4 GPIO 11 (Pin 23)  | Yellow     | SPI0_SCLK (direct connection, 3.3V clock)                    |

---

## RPLIDAR C1 ↔ Raspberry Pi 4 / UBEC 5V

*Planned wiring for the lidar unit — part of the Season 2 autonomous navigation
work (see [ARCHITECTURE.md](ARCHITECTURE.md#4-planned--autonomous-navigation-season-2)),
not installed in this build. The UBEC power branch is already wired; the lidar
unit itself is not.*

- **Interface:** Pi 4 hardware primary UART (`/dev/ttyAMA0` or `/dev/serial0`)
- **Logic Level:** 3.3V TTL compatible
- **Power Source:** Dedicated 5V UBEC (direct parallel connection)

### Wiring Details

| RPLIDAR C1 Wire / Pin    | Connected To                 | Wire Color | Function / Notes                                                                |
| -------------------------- | ------------------------------ | ---------- | ------------------------------------------------------------------------------------ |
| **VCC (5V)**             | UBEC 5V OUT+                 | Red        | Motor & core logic power (draws up to ~1.5A surge)                              |
| **GND**                  | UBEC 5V OUT− & Pi GND        | Black      | Shared common ground tied directly to UBEC OUT− and Pi 4 GND (e.g. Pin 6/9/14) |
| **TX**                   | Pi 4 GPIO 15 (Pin 10 / RXD0) | Green      | LIDAR serial data out → Pi 4 UART receive                                      |
| **RX**                   | Pi 4 GPIO 14 (Pin 8 / TXD0)  | Yellow     | Pi 4 UART transmit → LIDAR command in                                          |
| **MOTOCTR** (if present) | Pi 4 GPIO or 3V3/GND         | —          | Motor PWM speed control / enable (high or float to run)                        |

> A common ground jumper links the **UBEC OUT−** rail directly to a **Raspberry Pi 4
> GND pin** (Pin 6, 9, 14, 20, or 25), providing the reference return path for the
> GPIO 14/15 UART serial stream.

---

*ZoMa is property of TheMechanics. Contact: mamau.mechanics@gmail.com*
