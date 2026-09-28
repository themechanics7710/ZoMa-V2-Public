// ZoMa RX firmware — DRV8833 motor driver implementation (LEDC PWM).
// Property of TheMechanics. Contact: mamau.mechanics@gmail.com
//
// Drives the left/right DRV8833 IN pin pairs via LEDC PWM, with a compile-time
// split between the Arduino core 2.x and 3.x LEDC APIs.

#include "motors.h"

#include <Arduino.h>

#include "pins.h"

namespace {

constexpr uint32_t PWM_FREQ_HZ = 5000;
constexpr uint8_t PWM_RES_BITS = 8;

int16_t clampDuty(int16_t duty) {
  if (duty > 255) return 255;
  if (duty < -255) return -255;
  return duty;
}

// debug_bench builds against the latest espressif32 platform (Arduino core 3.x),
// while deploy_ros stays pinned to espressif32@6.5.0 (core 2.x). The LEDC API is
// pin-based on core 3.x and channel-based on core 2.x, so both are handled here
// rather than assuming one.
//
// Startup-glitch fix (both branches): attaching a pin to the LEDC peripheral can
// leave it in an undefined output state for a brief moment before the first
// write. Forcing the pin LOW via digitalWrite before attaching, and writing 0
// duty immediately after, closes that window for each pin individually as it's
// set up.
#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3

void attachIn(uint8_t pin) {
  pinMode(pin, OUTPUT);
  digitalWrite(pin, LOW);
  ledcAttach(pin, PWM_FREQ_HZ, PWM_RES_BITS);
  ledcWrite(pin, 0);
}

void writeIn(uint8_t pin, uint32_t duty) { ledcWrite(pin, duty); }

#else

constexpr uint8_t CH_RIGHT_IN1 = 0;
constexpr uint8_t CH_RIGHT_IN2 = 1;
constexpr uint8_t CH_LEFT_IN3 = 2;
constexpr uint8_t CH_LEFT_IN4 = 3;

uint8_t channelFor(uint8_t pin) {
  switch (pin) {
    case pins::RIGHT_IN1: return CH_RIGHT_IN1;
    case pins::RIGHT_IN2: return CH_RIGHT_IN2;
    case pins::LEFT_IN3: return CH_LEFT_IN3;
    default: return CH_LEFT_IN4; // pins::LEFT_IN4
  }
}

void attachIn(uint8_t pin) {
  pinMode(pin, OUTPUT);
  digitalWrite(pin, LOW);
  uint8_t ch = channelFor(pin);
  ledcSetup(ch, PWM_FREQ_HZ, PWM_RES_BITS);
  ledcAttachPin(pin, ch);
  ledcWrite(ch, 0);
}

void writeIn(uint8_t pin, uint32_t duty) { ledcWrite(channelFor(pin), duty); }

#endif

// One IN pin carries the PWM duty, the other is held low, per DRV8833 drive truth table.
void driveChannelPair(uint8_t pinForward, uint8_t pinReverse, int16_t duty) {
  duty = clampDuty(duty);
  if (duty >= 0) {
    writeIn(pinForward, duty);
    writeIn(pinReverse, 0);
  } else {
    writeIn(pinForward, 0);
    writeIn(pinReverse, -duty);
  }
}

} // namespace

void motors::begin() {
  attachIn(pins::RIGHT_IN1);
  attachIn(pins::RIGHT_IN2);
  attachIn(pins::LEFT_IN3);
  attachIn(pins::LEFT_IN4);
  stop(); // redundant now that each pin zeroes itself on attach -- kept as a safety net
}

void motors::setRight(int16_t duty) { driveChannelPair(pins::RIGHT_IN1, pins::RIGHT_IN2, duty); }

void motors::setLeft(int16_t duty) { driveChannelPair(pins::LEFT_IN3, pins::LEFT_IN4, duty); }

void motors::stop() {
  writeIn(pins::RIGHT_IN1, 0);
  writeIn(pins::RIGHT_IN2, 0);
  writeIn(pins::LEFT_IN3, 0);
  writeIn(pins::LEFT_IN4, 0);
}
