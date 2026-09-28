// ZoMa RX firmware — drive motor control interface.
// Property of TheMechanics. Contact: mamau.mechanics@gmail.com
//
// Public API for driving the left/right DRV8833 motor channels.

#pragma once

#include <cstdint>

// DRV8833 motor control via LEDC PWM (5kHz/8-bit, one channel per IN pin).
namespace motors {

void begin();

// Signed duty cycle: positive drives forward, negative reverse, magnitude 0-255.
// One IN pin is driven with the PWM duty and the other held low, per DRV8833
// drive/brake truth table.
void setRight(int16_t duty);
void setLeft(int16_t duty);

void stop();

} // namespace motors
