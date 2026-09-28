// ZoMa TX firmware — PS5 controller input handling.
// Property of TheMechanics. Contact: mamau.mechanics@gmail.com
//
// Manages PS5 pad pairing/connection state, reads stick/trigger/button
// input, and normalizes it into a ControllerInput ready to send over
// ESP-NOW.

#include "ps5_handler.h"
#include "espnow_tx.h"
#include <ps5Controller.h>
#include <Ticker.h>

#define LED_BUILTIN 2

static bool lastBoostState = false;
static bool wasConnected = false;

// Hardware-timer based blink for the onboard LED, independent of loop()'s
// cadence.
Ticker ledTicker;
volatile bool ledState = false;

void toggleLED() {
  ledState = !ledState;
  digitalWrite(LED_BUILTIN, ledState);
}

// Deadzone applied to both sticks -- rx/ry feed future accessories (e.g.
// camera pan/tilt) and get the same noise floor as the drive stick.
static const int16_t STICK_DEADZONE = 8;

static int16_t applyDeadzone(int16_t value) {
  return (abs(value) < STICK_DEADZONE) ? 0 : value;
}

// The PS5 pad's left stick Y axis reads negative when pushed forward. Sign
// convention is normalized here, at the hardware boundary, so everything
// downstream (and the wire format) uses positive throttle = forward.
//
// This is load-bearing for ESP-NOW wire compatibility: both boards must be
// flashed with matching firmware, since ESP-NOW copies raw bytes with no
// schema negotiation.
static const int16_t THROTTLE_AXIS_SIGN = -1;

// ps5.ly is an int8_t, so its most negative value is -128 while its most
// positive is +127. Negating -128 in 8-bit space overflows, so the
// arithmetic happens in int and the result is clamped back into -128..127,
// the range ControllerInput and ControlPacket both document.
static int16_t normaliseThrottle(int16_t rawLy) {
  return (int16_t)constrain(THROTTLE_AXIS_SIGN * (int)rawLy, -128, 127);
}

// Packs every held digital button into one bitmask. Uses held state
// (`ps5.square`), not pressed/released edge events, since the receiver
// wants "is it down right now".
static uint32_t readButtonMask() {
  uint32_t mask = 0;
  if (ps5.up)       mask |= BTN_UP;
  if (ps5.down)     mask |= BTN_DOWN;
  if (ps5.left)     mask |= BTN_LEFT;
  if (ps5.right)    mask |= BTN_RIGHT;
  if (ps5.cross)    mask |= BTN_CROSS;
  if (ps5.circle)   mask |= BTN_CIRCLE;
  if (ps5.square)   mask |= BTN_SQUARE;
  if (ps5.triangle) mask |= BTN_TRIANGLE;
  if (ps5.l1)       mask |= BTN_L1;
  if (ps5.r1)       mask |= BTN_R1;
  if (ps5.l3)       mask |= BTN_L3;
  if (ps5.r3)       mask |= BTN_R3;
  if (ps5.share)    mask |= BTN_SHARE;
  if (ps5.options)  mask |= BTN_OPTIONS;
  if (ps5.ps_btn)   mask |= BTN_PS;
  if (ps5.touchpad) mask |= BTN_TOUCHPAD;
  if (ps5.mute)     mask |= BTN_MUTE;
  return mask;
}

void initPS5Controller() {
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, LOW); // LED off while the boot process runs

  ps5.attachOnDisconnect([]() {
    ControlPacket stopPacket = {0, 0, 0, 0, 0, 0, false, 0};
    sendControlPacket(stopPacket);

    ledTicker.attach_ms(50, toggleLED);

    lastBoostState = false;
    wasConnected = false;
  });

  ps5.begin(); // starts Bluetooth scanning/listening

  ledTicker.attach_ms(50, toggleLED);
}

ControllerInput readPS5Controller() {
  ControllerInput input = {0, 0, 0, 0, 0, 0, false, 0, false};

  if (ps5.isConnected()) {
    input.connected = true;
    input.throttle  = normaliseThrottle(applyDeadzone(ps5.ly));
    input.steering  = applyDeadzone(ps5.lx);
    input.rx        = applyDeadzone(ps5.rx);
    input.ry        = applyDeadzone(ps5.ry);
    input.l2        = ps5.l2;
    input.r2        = ps5.r2;
    input.boost     = (bool)ps5.cross;
    input.buttons   = readButtonMask();

    if (!wasConnected) {
      ledTicker.detach();
      digitalWrite(LED_BUILTIN, HIGH); // solid on when connected
      ps5.lightbar(0, 0, 255).send();  // solid blue
      wasConnected = true;
      lastBoostState = false;
    }

    // Options + Mute = software e-stop. Zeroes every axis, not just drive,
    // since rx/ry/l2/r2 feed real hardware too.
    if (ps5.options || ps5.mute) {
      input.throttle = 0;
      input.steering = 0;
      input.rx       = 0;
      input.ry       = 0;
      input.l2       = 0;
      input.r2       = 0;
      input.boost    = false;
    }

    if (input.boost != lastBoostState) {
      if (input.boost) {
        ps5.lightbar(0, 255, 0).send(); // green while boost is held
      } else {
        ps5.lightbar(0, 0, 255).send(); // solid blue when released
      }
      lastBoostState = input.boost;
    }

  } else {
    // While disconnected, ledTicker handles the blink entirely in the
    // background; nothing to do here.
    if (wasConnected) {
      wasConnected = false;
      lastBoostState = false;
      ledTicker.attach_ms(50, toggleLED); // resume blinking if connection drops
    }
  }

  return input;
}
