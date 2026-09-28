// ZoMa TX firmware — debug logging macros.
// Property of TheMechanics. Contact: mamau.mechanics@gmail.com
//
// Serial debug output wrappers. TX has no build-time debug/deploy split;
// Bluetooth Classic and ESP-NOW don't reserve UART0, so Serial is always
// available for logging.

#pragma once

#include <Arduino.h>

#define DBG_BEGIN(baud) Serial.begin(baud)
#define DBG_PRINT(...) Serial.print(__VA_ARGS__)
#define DBG_PRINTLN(...) Serial.println(__VA_ARGS__)
#define DBG_PRINTF(...) Serial.printf(__VA_ARGS__)
