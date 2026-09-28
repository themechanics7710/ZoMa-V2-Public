// ZoMa TX firmware — entry point.
// Property of TheMechanics. Contact: mamau.mechanics@gmail.com
//
// Wires together PS5 pad input, the ESP-NOW drive link to the RX board, and
// the status LED ring, and runs the main transmit loop.

#include <Arduino.h>
#include <WiFi.h>

#include "espnow_tx.h"
#include "led_status.h"
#include "ps5_handler.h"

// Replace with your ESP32 RX board's MAC address (read it via
// WiFi.macAddress() on the RX board).
const uint8_t CAR_RECEIVER_MAC[] = {0x00, 0x00, 0x00, 0x00, 0x00, 0x00};

namespace {

// LED ring runs on its own FreeRTOS task, independent of loop()'s cadence --
// PS5 pad polling can block for multi-second stretches while searching for a
// connection, so tick() is driven from a dedicated task rather than from
// loop() to keep the ring animating smoothly regardless.
void ledTask(void*) {
  for (;;) {
    led_status::tick();
    vTaskDelay(pdMS_TO_TICKS(30)); // matches led_status's own frame interval
  }
}

// ESP-NOW link state is derived from sendControlPacket()'s own send result,
// debounced over a short window so a single dropped send doesn't flicker the
// ring. The main loop only sends while the pad is connected, so this
// correctly ages out to SEARCHING on its own once nothing has been sent
// successfully for a while.
constexpr uint32_t ESPNOW_UP_WINDOW_MS = 300;
bool everEspNowOk = false;
uint32_t lastEspNowOkMs = 0;

void noteEspNowSendResult(bool ok) {
  if (ok) {
    everEspNowOk = true;
    lastEspNowOkMs = millis();
  }
}

led_status::LinkState currentEspNowState() {
  if (!everEspNowOk) return led_status::LinkState::SEARCHING;
  return (millis() - lastEspNowOkMs) < ESPNOW_UP_WINDOW_MS ? led_status::LinkState::CONNECTED
                                                             : led_status::LinkState::SEARCHING;
}

} // namespace

void setup() {
  Serial.begin(115200);

  Serial.println("\n==========================================");
  Serial.println("   ESP32 CONTROLLER TRANSMITTER MODULE    ");
  Serial.println("==========================================");

  led_status::begin(); // ring starts on Status::BOOTING

  xTaskCreatePinnedToCore(ledTask, "led_ring", 4096, nullptr, 1, nullptr, 1);

  initPS5Controller();
  Serial.println("PS5 Bluetooth Subsystem Initialized.");

  WiFi.mode(WIFI_STA);
  Serial.print("This board's MAC: ");
  Serial.println(WiFi.macAddress());

  if (!initESPNowTransmitter(CAR_RECEIVER_MAC)) {
    Serial.println("Fatal: ESP-NOW failed to initialize!");
    led_status::set(led_status::Status::ERROR);
  }

  Serial.println("Waiting for PS5 Controller connection...");
}

void loop() {
  ControllerInput input = readPS5Controller();

  led_status::setBt(input.connected ? led_status::LinkState::CONNECTED
                                     : led_status::LinkState::SEARCHING);

  if (input.connected) {
    ControlPacket packet;
    packet.throttle = input.throttle;
    packet.steering = input.steering;
    packet.rx       = input.rx;
    packet.ry       = input.ry;
    packet.l2       = input.l2;
    packet.r2       = input.r2;
    packet.boost    = input.boost;
    packet.buttons  = input.buttons;

    sendControlPacket(packet);
    noteEspNowSendResult(lastSendWasAcked());

    Serial.printf("TX -> Thr:%4d Str:%4d | Rx:%4d Ry:%4d | L2:%3d R2:%3d | Boost:%d | Btns:0x%05lX\n",
                  packet.throttle, packet.steering,
                  packet.rx, packet.ry,
                  packet.l2, packet.r2,
                  packet.boost, (unsigned long)packet.buttons);

    led_status::setEspNow(currentEspNowState());

    vTaskDelay(pdMS_TO_TICKS(20)); // ~50Hz transmit loop
  } else {
    static unsigned long lastLog = 0;
    if (millis() - lastLog > 3000) {
      Serial.println("Waiting for PS5 Controller connection!!");
      lastLog = millis();
    }

    led_status::setEspNow(currentEspNowState());

    vTaskDelay(pdMS_TO_TICKS(100));
  }
}
