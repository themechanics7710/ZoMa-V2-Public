// ZoMa TX firmware — ESP-NOW transmitter.
// Property of TheMechanics. Contact: mamau.mechanics@gmail.com
//
// Initializes the ESP-NOW link to the RX board and sends control packets
// over it.

#include "espnow_tx.h"
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>

static uint8_t targetMac[6];
static esp_now_peer_info_t peerInfo;
static volatile bool lastSendAcked = false;

void OnDataSent(const uint8_t *mac_addr, esp_now_send_status_t status) {
  lastSendAcked = (status == ESP_NOW_SEND_SUCCESS);
}

bool initESPNowTransmitter(const uint8_t* receiverMac) {
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();

  // Fixed Wi-Fi channel for Bluetooth + ESP-NOW coexistence.
  esp_wifi_set_channel(1, WIFI_SECOND_CHAN_NONE);

  if (esp_now_init() != ESP_OK) {
    Serial.println("ESP-NOW: Init failed");
    return false;
  }

  esp_now_register_send_cb(OnDataSent);

  memcpy(targetMac, receiverMac, 6);
  memcpy(peerInfo.peer_addr, receiverMac, 6);
  peerInfo.channel = 1; // must match the receiver's channel
  peerInfo.encrypt = false;

  if (esp_now_add_peer(&peerInfo) != ESP_OK) {
    Serial.println("ESP-NOW: Failed to add receiver peer");
    return false;
  }

  Serial.println("ESP-NOW: Transmitter initialized on Channel 1");
  return true;
}

bool sendControlPacket(const ControlPacket& packet) {
  esp_err_t result = esp_now_send(targetMac, (uint8_t *)&packet, sizeof(packet));
  return (result == ESP_OK);
}

bool lastSendWasAcked() {
  return lastSendAcked;
}
