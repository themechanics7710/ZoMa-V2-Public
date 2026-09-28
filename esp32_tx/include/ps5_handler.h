// ZoMa TX firmware — PS5 controller input interface.
// Property of TheMechanics. Contact: mamau.mechanics@gmail.com
//
// Declares the normalized controller input snapshot and the functions that
// initialize PS5 pairing and read the current pad state.

#ifndef PS5_HANDLER_H
#define PS5_HANDLER_H

#include <Arduino.h>

struct ControllerInput {
  int16_t  throttle;  // Left stick Y, -128..127, positive = forward
  int16_t  steering;  // Left stick X, -128..127
  int16_t  rx;         // Right stick X, -128..127
  int16_t  ry;         // Right stick Y, -128..127
  uint8_t  l2;          // Left trigger analog, 0..255
  uint8_t  r2;          // Right trigger analog, 0..255
  bool     boost;       // Cross button state
  uint32_t buttons;     // Bitmask -- see ButtonBit in espnow_tx.h
  bool     connected;
};

void initPS5Controller();
ControllerInput readPS5Controller();

#endif
