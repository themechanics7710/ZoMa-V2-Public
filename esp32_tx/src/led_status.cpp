// ZoMa TX firmware — status LED ring driver.
// Property of TheMechanics. Contact: mamau.mechanics@gmail.com
//
// Renders the BOOTING/ERROR overrides and the BT/ESP-NOW link-state ladder
// onto the WS2812B ring, throttled to a fixed frame interval.

#include "led_status.h"

#include <Adafruit_NeoPixel.h>
#include <Arduino.h>
#include <cmath>

#include "pins.h"

namespace led_status {

namespace {

Adafruit_NeoPixel strip(pins::LED_RING_COUNT, pins::LED_RING_DATA, NEO_GRB + NEO_KHZ800);

constexpr uint32_t FRAME_INTERVAL_MS = 30;

// Chase tail length for the full-ring spin animations. Must be meaningfully
// less than LED_RING_COUNT for a genuine dark gap to exist -- if the tail
// were >= the pixel count, every pixel would stay lit and the animation
// would read as a soft gradient rather than a moving comet.
constexpr float CHASE_TAIL_LEN = 12.0f;

constexpr uint8_t BLUE_R = 0, BLUE_G = 80, BLUE_B = 255;
constexpr uint8_t GREEN_R = 0, GREEN_G = 200, GREEN_B = 0;
constexpr uint8_t AMBER_R = 200, AMBER_G = 160, AMBER_B = 0;

bool overrideActive = true; // begin() leaves the ring at BOOTING until setBt/setEspNow is first called
Status overrideStatus = Status::BOOTING;
uint32_t overrideAnimStartMs = 0;

LinkState btState = LinkState::SEARCHING;
LinkState espNowState = LinkState::SEARCHING;
uint32_t btAnimStartMs = 0; // resets each time btState changes, to restart the blue spin's phase

uint32_t lastFrameMs = 0;

// Render helpers -- whole-ring only, don't call strip.show(). tick()
// composes exactly one of these per frame and shows it exactly once.

void renderSolid(uint8_t r, uint8_t g, uint8_t b) {
  for (uint16_t i = 0; i < pins::LED_RING_COUNT; i++) {
    strip.setPixelColor(i, strip.Color(r, g, b));
  }
}

void renderBreathe(uint8_t r, uint8_t g, uint8_t b, uint32_t periodMs) {
  float phase = fmodf(static_cast<float>(millis()), static_cast<float>(periodMs)) / periodMs;
  // Ranges 0.30..1.00, not 0..1 -- stays clearly "on" the whole cycle, no
  // dip toward black, so it reads as a calm pulse rather than a blink.
  float level = 0.65f + 0.35f * sinf(phase * 2.0f * PI);
  for (uint16_t i = 0; i < pins::LED_RING_COUNT; i++) {
    strip.setPixelColor(i, strip.Color(static_cast<uint8_t>(r * level),
                                        static_cast<uint8_t>(g * level),
                                        static_cast<uint8_t>(b * level)));
  }
}

void renderChase(uint8_t r, uint8_t g, uint8_t b, uint32_t periodMs, float tailLength,
                  uint32_t animStartMs) {
  uint32_t elapsed = millis() - animStartMs;
  // Continuous position around the ring, 0.0 .. LED_RING_COUNT, wrapping smoothly.
  float headPos = fmodf(static_cast<float>(elapsed) / periodMs * pins::LED_RING_COUNT,
                         static_cast<float>(pins::LED_RING_COUNT));

  for (uint16_t i = 0; i < pins::LED_RING_COUNT; i++) {
    float dist = headPos - i;
    if (dist < 0) dist += pins::LED_RING_COUNT; // wrap backwards around the ring

    float level = (dist < tailLength) ? (1.0f - dist / tailLength) : 0.0f;
    strip.setPixelColor(i, strip.Color(static_cast<uint8_t>(r * level),
                                        static_cast<uint8_t>(g * level),
                                        static_cast<uint8_t>(b * level)));
  }
}

void renderBlink(uint8_t r, uint8_t g, uint8_t b, uint32_t periodMs, uint32_t animStartMs) {
  bool on = ((millis() - animStartMs) / periodMs) % 2 == 0;
  if (on) {
    renderSolid(r, g, b);
  } else {
    renderSolid(0, 0, 0);
  }
}

} // namespace

void begin() {
  strip.begin();
  strip.setBrightness(60); // 0-255 -- kept modest; 12 LEDs at full brightness draw ~700mA
  strip.show();
  overrideAnimStartMs = millis();
}

void set(Status status) {
  overrideActive = true;
  overrideStatus = status;
  overrideAnimStartMs = millis();
  lastFrameMs = 0; // force an immediate redraw on the next tick()
}

void setBt(LinkState state) {
  if (state != btState) {
    btState = state;
    btAnimStartMs = millis(); // fresh sweep each time searching (re)starts
  }
  overrideActive = false;
}

void setEspNow(LinkState state) {
  espNowState = state; // no animation of its own -- only selects which
                        // ladder state tick() renders below
  overrideActive = false;
}

void tick() {
  uint32_t now = millis();
  if (now - lastFrameMs < FRAME_INTERVAL_MS) return;
  lastFrameMs = now;

  if (overrideActive) {
    switch (overrideStatus) {
      case Status::BOOTING:
        renderChase(255, 255, 255, 800, CHASE_TAIL_LEN, overrideAnimStartMs);
        break;
      case Status::ERROR:
        renderBlink(255, 0, 0, 300, overrideAnimStartMs);
        break;
    }
    strip.show();
    return;
  }

  // Linear ladder: BT down -> spinning blue (full ring). BT up, ESP-NOW not
  // confirmed -> breathing green. Both up -> breathing amber. BT down with
  // ESP-NOW confirmed can't happen in this firmware -- ESP-NOW only ever
  // sends while the pad is connected.
  if (btState == LinkState::SEARCHING) {
    renderChase(BLUE_R, BLUE_G, BLUE_B, 800, CHASE_TAIL_LEN, btAnimStartMs);
  } else if (espNowState != LinkState::CONNECTED) {
    renderBreathe(GREEN_R, GREEN_G, GREEN_B, 2500);
  } else {
    renderBreathe(AMBER_R, AMBER_G, AMBER_B, 2500);
  }
  strip.show();
}

} // namespace led_status
