// ZoMa TX firmware — GPIO pin assignments.
// Property of TheMechanics. Contact: mamau.mechanics@gmail.com
//
// Central definition of the pins this board's peripherals are wired to.

#pragma once

#include <cstdint>

namespace pins {

// WS2812B 12-LED status ring, data-in pin. GPIO32 is not a strapping pin,
// not UART0, and not input-only, making it safe for driving an output like
// this.
// Wiring best practice (not enforced in code): a ~300-500ohm series resistor
// on this data line, and a large (~1000uF) capacitor across the ring's
// 5V/GND right at the ring, both standard WS2812 recommendations against
// signal ringing and inrush current on power-up.
constexpr uint8_t LED_RING_DATA = 32;
constexpr uint16_t LED_RING_COUNT = 12;

} // namespace pins
