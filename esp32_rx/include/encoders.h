// ZoMa RX firmware — wheel encoder interface.
// Property of TheMechanics. Contact: mamau.mechanics@gmail.com
//
// Public API for reading left/right wheel encoder tick counts.

#pragma once

#include <cstdint>

// Wheel encoder reading via ESP32 PCNT hardware counters, x4 quadrature decoding.
namespace encoders {

void begin();

int32_t rightCount();
int32_t leftCount();

} // namespace encoders
