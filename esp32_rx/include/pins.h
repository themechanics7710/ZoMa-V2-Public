// ZoMa RX firmware — GPIO pin assignments for esp32_rx.
// Property of TheMechanics. Contact: mamau.mechanics@gmail.com
//
// Central pin map for the DRV8833 motor driver, wheel encoders, and BNO055 IMU.
// Keep this as the single source of truth for esp32_rx's wiring.

#pragma once

#include <cstdint>

namespace pins {

// DRV8833 motor driver — PWM 5kHz/8-bit, one LEDC channel per IN pin.
// Right motor
constexpr uint8_t RIGHT_IN1 = 27;
constexpr uint8_t RIGHT_IN2 = 26;
// Left motor
constexpr uint8_t LEFT_IN3 = 32;
constexpr uint8_t LEFT_IN4 = 33;

// Wheel encoders (PCNT hardware counters, x4 quadrature decoding)
// Right motor — PCNT unit 0
constexpr uint8_t RIGHT_ENC_A = 35; // C1 / Green
constexpr uint8_t RIGHT_ENC_B = 34; // C2 / Yellow
// Left motor — PCNT unit 1
constexpr uint8_t LEFT_ENC_A = 18; // C1 / Green
constexpr uint8_t LEFT_ENC_B = 19; // C2 / Yellow

// BNO055 IMU (I2C) — the ESP32's default I2C pins.
constexpr uint8_t IMU_SDA = 21;
constexpr uint8_t IMU_SCL = 22;

} // namespace pins
