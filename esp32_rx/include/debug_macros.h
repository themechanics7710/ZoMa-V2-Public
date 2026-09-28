// ZoMa RX firmware — build-mode-gated debug print macros.
// Property of TheMechanics. Contact: mamau.mechanics@gmail.com
//
// Wraps Serial output so it exists only in the debug_bench build; deploy_ros
// compiles every DBG_* call to nothing, since UART0 there belongs to micro-ROS.

#pragma once

// debug_bench: plain Serial output for bench testing over USB.
// deploy_ros:  Serial/UART0 belongs to micro-ROS — these compile to nothing.
#if defined(DEBUG_BENCH)
  #include <Arduino.h>
  #define DBG_BEGIN(baud) Serial.begin(baud)
  #define DBG_PRINT(...) Serial.print(__VA_ARGS__)
  #define DBG_PRINTLN(...) Serial.println(__VA_ARGS__)
  #define DBG_PRINTF(...) Serial.printf(__VA_ARGS__)
#else
  #define DBG_BEGIN(baud)
  #define DBG_PRINT(...)
  #define DBG_PRINTLN(...)
  #define DBG_PRINTF(...)
#endif
