// ZoMa RX firmware — wheel encoder implementation (ESP32 PCNT hardware counters).
// Property of TheMechanics. Contact: mamau.mechanics@gmail.com
//
// x4 quadrature decoding for the left/right wheel encoders, with two PCNT
// driver API implementations selected at compile time by ESP-IDF version.

#include "encoders.h"

#include "esp_idf_version.h"
#include "pins.h"

// debug_bench builds on the latest espressif32 platform (ESP-IDF 5.x), where the
// legacy driver/pcnt.h API used by deploy_ros's pinned platform (espressif32@6.5.0,
// ESP-IDF 4.4.x) is deprecated in favor of driver/pulse_cnt.h. Both are implemented
// here so encoder reading works on whichever core each environment builds against.
#if ESP_IDF_VERSION >= ESP_IDF_VERSION_VAL(5, 0, 0)

#include "driver/pulse_cnt.h"

namespace {

constexpr int COUNT_LIMIT = 30000;

pcnt_unit_handle_t rightUnit = nullptr;
pcnt_unit_handle_t leftUnit = nullptr;

// Full (x4) quadrature decoding: each channel counts edges of one phase, using the
// other phase's level to pick count-up vs count-down.
pcnt_unit_handle_t makeQuadratureUnit(gpio_num_t pinA, gpio_num_t pinB) {
  pcnt_unit_handle_t unit = nullptr;
  pcnt_unit_config_t unitConfig = {};
  unitConfig.low_limit = -COUNT_LIMIT;
  unitConfig.high_limit = COUNT_LIMIT;
  pcnt_new_unit(&unitConfig, &unit);

  pcnt_glitch_filter_config_t filterConfig = {};
  filterConfig.max_glitch_ns = 1250;
  pcnt_unit_set_glitch_filter(unit, &filterConfig);

  pcnt_chan_config_t chanAConfig = {};
  chanAConfig.edge_gpio_num = pinA;
  chanAConfig.level_gpio_num = pinB;
  pcnt_channel_handle_t chanA = nullptr;
  pcnt_new_channel(unit, &chanAConfig, &chanA);
  pcnt_channel_set_edge_action(chanA, PCNT_CHANNEL_EDGE_ACTION_DECREASE,
                                PCNT_CHANNEL_EDGE_ACTION_INCREASE);
  pcnt_channel_set_level_action(chanA, PCNT_CHANNEL_LEVEL_ACTION_KEEP,
                                 PCNT_CHANNEL_LEVEL_ACTION_INVERSE);

  pcnt_chan_config_t chanBConfig = {};
  chanBConfig.edge_gpio_num = pinB;
  chanBConfig.level_gpio_num = pinA;
  pcnt_channel_handle_t chanB = nullptr;
  pcnt_new_channel(unit, &chanBConfig, &chanB);
  pcnt_channel_set_edge_action(chanB, PCNT_CHANNEL_EDGE_ACTION_INCREASE,
                                PCNT_CHANNEL_EDGE_ACTION_DECREASE);
  pcnt_channel_set_level_action(chanB, PCNT_CHANNEL_LEVEL_ACTION_KEEP,
                                 PCNT_CHANNEL_LEVEL_ACTION_INVERSE);

  pcnt_unit_enable(unit);
  pcnt_unit_clear_count(unit);
  pcnt_unit_start(unit);
  return unit;
}

} // namespace

void encoders::begin() {
  rightUnit = makeQuadratureUnit(static_cast<gpio_num_t>(pins::RIGHT_ENC_A),
                                  static_cast<gpio_num_t>(pins::RIGHT_ENC_B));
  leftUnit = makeQuadratureUnit(static_cast<gpio_num_t>(pins::LEFT_ENC_A),
                                 static_cast<gpio_num_t>(pins::LEFT_ENC_B));
}

int32_t encoders::rightCount() {
  int count = 0;
  pcnt_unit_get_count(rightUnit, &count);
  return count;
}

int32_t encoders::leftCount() {
  int count = 0;
  pcnt_unit_get_count(leftUnit, &count);
  return -count;
}

#else

#include "driver/pcnt.h"

namespace {

void configureQuadratureUnit(pcnt_unit_t unit, gpio_num_t pinA, gpio_num_t pinB) {
  pcnt_config_t chanA = {};
  chanA.pulse_gpio_num = pinA;
  chanA.ctrl_gpio_num = pinB;
  chanA.channel = PCNT_CHANNEL_0;
  chanA.unit = unit;
  chanA.pos_mode = PCNT_COUNT_INC;
  chanA.neg_mode = PCNT_COUNT_DEC;
  chanA.lctrl_mode = PCNT_MODE_REVERSE;
  chanA.hctrl_mode = PCNT_MODE_KEEP;
  chanA.counter_h_lim = 30000;
  chanA.counter_l_lim = -30000;
  pcnt_unit_config(&chanA);

  pcnt_config_t chanB = {};
  chanB.pulse_gpio_num = pinB;
  chanB.ctrl_gpio_num = pinA;
  chanB.channel = PCNT_CHANNEL_1;
  chanB.unit = unit;
  chanB.pos_mode = PCNT_COUNT_INC;
  chanB.neg_mode = PCNT_COUNT_DEC;
  chanB.lctrl_mode = PCNT_MODE_KEEP;
  chanB.hctrl_mode = PCNT_MODE_REVERSE;
  chanB.counter_h_lim = 30000;
  chanB.counter_l_lim = -30000;
  pcnt_unit_config(&chanB);

  pcnt_set_filter_value(unit, 100); // ~1.25us glitch filter at 80MHz APB clock
  pcnt_filter_enable(unit);

  pcnt_counter_pause(unit);
  pcnt_counter_clear(unit);
  pcnt_counter_resume(unit);
}

} // namespace

void encoders::begin() {
  configureQuadratureUnit(PCNT_UNIT_0, static_cast<gpio_num_t>(pins::RIGHT_ENC_A),
                           static_cast<gpio_num_t>(pins::RIGHT_ENC_B));
  configureQuadratureUnit(PCNT_UNIT_1, static_cast<gpio_num_t>(pins::LEFT_ENC_A),
                           static_cast<gpio_num_t>(pins::LEFT_ENC_B));
}

int32_t encoders::rightCount() {
  int16_t count = 0;
  pcnt_get_counter_value(PCNT_UNIT_0, &count);
  return count;
}

int32_t encoders::leftCount() {
  int16_t count = 0;
  pcnt_get_counter_value(PCNT_UNIT_1, &count);
  return -count;
}

#endif
