// ZoMa TX firmware — ESP-NOW transmitter interface and wire packet format.
// Property of TheMechanics. Contact: mamau.mechanics@gmail.com
//
// Declares the control packet sent to the RX board and the functions that
// initialize the ESP-NOW link and send packets over it.

#ifndef ESPNOW_TX_H
#define ESPNOW_TX_H

#include <Arduino.h>

// Bitmask flags for ControlPacket.buttons. Read with (packet.buttons & BTN_X).
enum ButtonBit : uint32_t {
  BTN_UP       = 1UL << 0,
  BTN_DOWN     = 1UL << 1,
  BTN_LEFT     = 1UL << 2,
  BTN_RIGHT    = 1UL << 3,
  BTN_CROSS    = 1UL << 4,
  BTN_CIRCLE   = 1UL << 5,
  BTN_SQUARE   = 1UL << 6,
  BTN_TRIANGLE = 1UL << 7,
  BTN_L1       = 1UL << 8,
  BTN_R1       = 1UL << 9,
  BTN_L3       = 1UL << 10,
  BTN_R3       = 1UL << 11,
  BTN_SHARE    = 1UL << 12,
  BTN_OPTIONS  = 1UL << 13,
  BTN_PS       = 1UL << 14,
  BTN_TOUCHPAD = 1UL << 15,
  BTN_MUTE     = 1UL << 16,
};

// Packed struct with fixed-width types guarantees cross-device alignment.
// Must match the RX board's copy of this struct byte-for-byte -- ESP-NOW has
// no schema negotiation, it just copies raw bytes into the receiver's struct.
typedef struct __attribute__((packed)) {
  int16_t  throttle;  // Left stick Y, -128..127, positive = forward
  int16_t  steering;  // Left stick X, -128..127
  int16_t  rx;         // Right stick X, -128..127 (reserved, e.g. pan/camera)
  int16_t  ry;         // Right stick Y, -128..127 (reserved, e.g. tilt/camera)
  uint8_t  l2;          // Left trigger analog, 0..255
  uint8_t  r2;          // Right trigger analog, 0..255
  uint8_t  boost;       // Cross button state
  uint32_t buttons;     // Bitmask -- see ButtonBit above
} ControlPacket;         // 15 bytes total, well under ESP-NOW's 250-byte cap

bool initESPNowTransmitter(const uint8_t* receiverMac);
bool sendControlPacket(const ControlPacket& packet);

bool lastSendWasAcked();

#endif
