// ZoMa RX firmware — ESP-NOW receive link interface and wire protocol.
// Property of TheMechanics. Contact: mamau.mechanics@gmail.com
//
// Defines the ControlPacket wire format received from esp32_tx and the public
// API for pulling the latest packet / link-timeout status.

#pragma once

#include <cstdint>

// ESP-NOW receive link from esp32_tx.
namespace espnow_rx {

// ============================================================================
// ControlPacket -- wire format for esp32_tx -> esp32_rx over ESP-NOW.
//
// *** MUST STAY BYTE-IDENTICAL WITH THE COPY IN esp32_tx/include/espnow_tx.h ***
// (field order and types). ESP-NOW copies these bytes directly between two
// independently-flashed boards -- there is no schema negotiation. If this
// struct ever changes here, make the identical change in espnow_tx.h in the
// same commit, or the two boards will silently misinterpret each other's
// packets.
//
// TX is a dumb pass-through: every field is the RAW value read from the pad,
// with no deadzone or sign normalization applied on that side. RX (this board)
// owns all interpretation -- deadzone, throttle sign convention, e-stop --
// applied immediately after unpacking, before any of these values feed drive
// kinematics.
// ============================================================================
struct __attribute__((packed)) ControlPacket {
  int16_t throttle; // Left stick Y, -128..127
  int16_t steering; // Left stick X, -128..127
  int16_t rx;       // Right stick X, -128..127
  int16_t ry;       // Right stick Y, -128..127
  uint8_t l2;       // Left trigger analog, 0..255
  uint8_t r2;       // Right trigger analog, 0..255
  uint8_t boost;    // Cross button state, kept for backward compat
  uint32_t buttons; // Bitmask -- see ButtonBit below
}; // 15 bytes total -- must match espnow_tx.h exactly, field for field

// Bitmask flags for ControlPacket.buttons. Read with (packet.buttons & BTN_X).
// Bit-for-bit copy of esp32_tx/include/espnow_tx.h's ButtonBit. BTN_MUTE is
// unused by RX but kept for byte-identical alignment with TX.
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

// Starts ESP-NOW on the fixed Wi-Fi channel esp32_tx also uses. No peer
// registration needed to receive -- ESP-NOW delivers to the recv callback
// regardless of peer list, which only matters for sending.
bool begin();

// True (and fills `out`) if a NEW packet has arrived since the last call;
// false (and `out` left untouched) otherwise. Pulls the latest packet and
// marks it consumed.
bool getLatestPacket(ControlPacket& out);

// Milliseconds since the last packet arrived. Returns UINT32_MAX if no packet
// has ever arrived.
uint32_t msSinceLastPacket();

} // namespace espnow_rx
