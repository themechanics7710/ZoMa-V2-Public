// ZoMa TX firmware — status LED ring interface.
// Property of TheMechanics. Contact: mamau.mechanics@gmail.com
//
// Drives the WS2812B status ring that shows the controller's Bluetooth pad
// link and ESP-NOW drive link state.

#pragma once

// Drives the WS2812B LED ring (pins::LED_RING_DATA) to give a visual readout
// of what esp32_tx is doing. Renders as a linear ladder: BT searching (blue
// spin) -> BT connected, ESP-NOW not yet confirmed (green breathe) -> both
// connected (amber breathe). BOOTING/ERROR are whole-ring overrides for
// states where link state isn't meaningful yet or something is broken.
namespace led_status {

// Whole-ring overrides -- take priority over the BT/ESP-NOW ladder below.
enum class Status {
  BOOTING, // white spinner -- firmware just started, links not up yet
  ERROR,   // fast red blink -- e.g. ESP-NOW failed to initialize
};

// Per-link state, tracked independently for BT and ESP-NOW.
enum class LinkState {
  SEARCHING, // not yet linked
  CONNECTED, // linked
};

// Initializes the LED strip. Call once from setup().
void begin();

// Switches to a whole-ring override (BOOTING/ERROR). Cheap to call repeatedly.
void set(Status status);

// Sets the BT link state. Also clears any active whole-ring override --
// once real link state is being reported, it supersedes BOOTING. Cheap to
// call repeatedly with the same value (the animation only resets on an
// actual change).
void setBt(LinkState state);

// Sets the ESP-NOW link state. Same semantics as setBt().
void setEspNow(LinkState state);

// Advances the current animation and composes one full frame (override, or
// the BT/ESP-NOW ladder), then pushes it to the strip. Call every loop()
// iteration -- internally throttled and non-blocking (no delay()), safe to
// call as often as you like.
void tick();

} // namespace led_status
