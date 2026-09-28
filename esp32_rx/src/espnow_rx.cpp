// ZoMa RX firmware — ESP-NOW receive link implementation.
// Property of TheMechanics. Contact: mamau.mechanics@gmail.com
//
// Receives ControlPacket frames from esp32_tx over ESP-NOW and exposes the
// latest packet plus link-timeout tracking to the rest of the firmware.

#include "espnow_rx.h"

#include <WiFi.h>
#include <cstdint>
#include <cstring>
#include <esp_now.h>
#include <esp_wifi.h>

#include "debug_macros.h"

namespace espnow_rx {

namespace {

// Fixed ESP-NOW channel -- must match esp32_tx. Both sides must agree on a
// channel for ESP-NOW to deliver anything.
constexpr uint8_t ESPNOW_CHANNEL = 1;

volatile ControlPacket latestPacket = {};
volatile uint32_t lastPacketMillis = 0;
volatile bool hasNewPacket = false;

void onDataRecv(const uint8_t* mac_addr, const uint8_t* data, int len) {
  (void)mac_addr;
  if (len != sizeof(ControlPacket)) return;
  memcpy((void*)&latestPacket, data, sizeof(ControlPacket));
  lastPacketMillis = millis();
  hasNewPacket = true;
}

} // namespace

bool begin() {
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();

  esp_wifi_set_channel(ESPNOW_CHANNEL, WIFI_SECOND_CHAN_NONE);

  // Raw IDF call, not WiFi.setSleep(false): modem sleep does not reliably
  // disable via the Arduino wrapper on a WIFI_STA that never associates to an
  // AP (RX never does -- it only needs the radio for ESP-NOW). The underlying
  // IDF call is what's required for consistent ESP-NOW receive.
  esp_wifi_set_ps(WIFI_PS_NONE);

  if (esp_now_init() != ESP_OK) {
    DBG_PRINTLN("[ZoMa RX][ESP-NOW] init failed");
    return false;
  }

  esp_now_register_recv_cb(onDataRecv);

  DBG_PRINTLN("[ZoMa RX][ESP-NOW] initialized, waiting for packets");
  return true;
}

bool getLatestPacket(ControlPacket& out) {
  if (!hasNewPacket) return false;
  noInterrupts();
  out = *const_cast<ControlPacket*>(&latestPacket);
  hasNewPacket = false;
  interrupts();
  return true;
}

uint32_t msSinceLastPacket() {
  if (lastPacketMillis == 0) return UINT32_MAX;
  return millis() - lastPacketMillis;
}

} // namespace espnow_rx
