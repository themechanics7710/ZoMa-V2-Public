// ZoMa RX firmware — main entry point: drive mode + calibration/bench tests.
// Property of TheMechanics. Contact: mamau.mechanics@gmail.com
//
// Selects one of several build-time modes (drive mode or a numbered calibration
// test) via CAL_TEST, and implements each mode's setup()/loop().

#include <Arduino.h>
#include <Preferences.h>
#include <WiFi.h>
#include <math.h>

#include "bno055.h"
#include "debug_macros.h"
#include "encoders.h"
#include "espnow_rx.h"
#include "motors.h"
#include "pins.h"

// ============================================================================
// CALIBRATION MODE SELECT — override via a `-D CAL_TEST=n` PlatformIO build flag
// (see platformio.ini's cal_test_1..cal_test_5 environments), or leave unset for
// the default:
//   0 = DRIVE MODE (default, no flag needed) — ESP-NOW receive -> deadzone/sign/
//       e-stop processing -> arcade kinematics -> motors, running continuously.
//       debug_bench and deploy_ros both build with no CAL_TEST flag, so both
//       default to drive mode.
//   1 = CAL TEST 1: straight-line trim test (visual — tape line on the floor)
//   2 = CAL TEST 2: distance/encoder calibration (drive untethered, measure tape)
//   3 = CAL TEST 3: live encoder read, no motor drive
//   4 = bench test: forward/pause/reverse/pause, logging encoder deltas
//   5 = CAL TEST 5: BNO055 bring-up — live yaw/pitch/roll serial log, no motor
//       drive.
// ============================================================================
#ifndef CAL_TEST
#define CAL_TEST 0
#endif

namespace {


constexpr uint32_t SERIAL_BAUD = 115200;
constexpr int16_t TEST_DUTY = 210; // ~82% of 255, safe bench-test speed

// ---- Trim ----
// Independently scales each side's duty. Start 1.00 / 1.00 for the first Test 1 run.
// If the robot curves toward the right, the right side is under-driven relative to
// the left (or the left is over-driven) — nudge in ~0.02 steps and pick one
// convention (e.g. always correct the weaker side upward) so results stay comparable
// between attempts. Reflash after each change; log the final values once settled.
constexpr float RIGHT_TRIM = 1.00f;
constexpr float LEFT_TRIM  = 1.0097f;

constexpr uint32_t CAL_DRIVE_MS = 4000; // both cal tests: 4s drive, per the test plan

// Test 2 only: set true for exactly one flash to clear a previously saved result
// and force a fresh drive on next boot. Set back to false and reflash again before
// the real run — otherwise every subsequent reset re-clears and re-drives.
constexpr bool CAL2_FORCE_RESET = false;

int16_t trimmedDuty(int16_t base, float trim) {
  return static_cast<int16_t>(base * trim);
}

} // namespace

// ============================================================================
#if CAL_TEST == 1
// CAL TEST 1 — straight-line trim test
// ============================================================================
namespace {
uint32_t driveStartMs = 0;
bool stopped = false;
} // namespace

void setup() {
  DBG_BEGIN(SERIAL_BAUD);
  delay(200); // let the USB serial monitor attach before the first prints
  DBG_PRINTLN();
  DBG_PRINTLN("[ZoMa RX] CAL TEST 1 -- straight-line trim test");
  DBG_PRINTF("[CAL1] trims: right=%.2f left=%.2f  base duty=%d\n", RIGHT_TRIM, LEFT_TRIM, TEST_DUTY);
  DBG_PRINTLN("[CAL1] place robot on the tape line, drive starts immediately on boot/reset");

  motors::begin();

  driveStartMs = millis();
  motors::setRight(trimmedDuty(TEST_DUTY, RIGHT_TRIM));
  motors::setLeft(trimmedDuty(TEST_DUTY, LEFT_TRIM));
}

void loop() {
  if (!stopped && millis() - driveStartMs >= CAL_DRIVE_MS) {
    motors::stop();
    stopped = true;
    DBG_PRINTLN("[CAL1] done -- check drift against the tape line, adjust RIGHT_TRIM/LEFT_TRIM, reflash and repeat");
  }
}

// ============================================================================
// ============================================================================
#elif CAL_TEST == 2
// CAL TEST 2 -- distance / encoder calibration test
// ============================================================================
namespace {
Preferences prefs;
int32_t rStart = 0, lStart = 0;
int32_t savedRightTicks = 0, savedLeftTicks = 0;
bool driveDone = false;
uint32_t driveStartMs = 0;
uint32_t lastPrintMs = 0;

constexpr uint32_t PRE_DRIVE_DELAY_MS = 30000; // time to unplug USB and place the robot
} // namespace

void setup() {
  DBG_BEGIN(SERIAL_BAUD);
  delay(200);
  DBG_PRINTLN();
  DBG_PRINTLN("[ZoMa RX] CAL TEST 2 -- distance/encoder calibration");

  prefs.begin("cal2", false); // NVS namespace "cal2", read/write

  if (CAL2_FORCE_RESET) {
    prefs.clear();
    DBG_PRINTLN("[CAL2] CAL2_FORCE_RESET=true -- cleared saved result.");
    DBG_PRINTLN("[CAL2] Set CAL2_FORCE_RESET back to false and reflash before the drive will start on the next boot.");
    motors::begin(); // keep motors silenced
    driveDone = true; // do NOT drive on the same boot that clears -- stops here
    return;
  }

  bool haveSavedResult = prefs.getBool("done", false);

  if (haveSavedResult) {
    // A result from a previous untethered run is already on flash (it survives the
    // reset that happens when USB gets replugged) -- report it, don't drive again.
    savedRightTicks = prefs.getInt("rTicks", 0);
    savedLeftTicks = prefs.getInt("lTicks", 0);
    DBG_PRINTLN("[CAL2] found a saved result from a previous run -- reporting it, not driving again.");
    DBG_PRINTLN("[CAL2] to run a fresh test: set CAL2_FORCE_RESET=true, reflash once, then set it back to false and reflash again.");
    motors::begin();
    driveDone = true;
    return;
  }

  DBG_PRINTF("[CAL2] trims: right=%.2f left=%.2f  base duty=%d\n", RIGHT_TRIM, LEFT_TRIM, TEST_DUTY);
  DBG_PRINTF("[CAL2] %lu ms until drive starts -- unplug USB and place the robot now.\n",
             static_cast<unsigned long>(PRE_DRIVE_DELAY_MS));

  motors::begin();
  encoders::begin();

  // Countdown, printed once per second, while USB is still connected (or not --
  // this runs regardless, the prints just won't be seen if already unplugged).
  for (uint32_t remaining = PRE_DRIVE_DELAY_MS; remaining > 0; remaining -= 1000) {
    DBG_PRINTF("[CAL2] starting in %lu s...\n", static_cast<unsigned long>(remaining / 1000));
    delay(1000);
  }

  DBG_PRINTLN("[CAL2] mark start position now -- driving.");

  rStart = encoders::rightCount();
  lStart = encoders::leftCount();

  driveStartMs = millis();
  motors::setRight(trimmedDuty(TEST_DUTY, RIGHT_TRIM));
  motors::setLeft(trimmedDuty(TEST_DUTY, LEFT_TRIM));
}

void loop() {
  if (!driveDone) {
    if (millis() - driveStartMs >= CAL_DRIVE_MS) {
      motors::stop();

      int32_t rEnd = encoders::rightCount();
      int32_t lEnd = encoders::leftCount();
      savedRightTicks = rEnd - rStart;
      savedLeftTicks = lEnd - lStart;

      prefs.putInt("rTicks", savedRightTicks);
      prefs.putInt("lTicks", savedLeftTicks);
      prefs.putBool("done", true);

      driveDone = true;
      DBG_PRINTLN("[CAL2] drive complete, result saved to flash -- safe to replug USB now");
    }
    return;
  }

  if (millis() - lastPrintMs >= 1000) {
    lastPrintMs = millis();
    DBG_PRINTF("[CAL2 RESULT] right ticks=%ld  left ticks=%ld  -- measure tape distance (mm), divide by ticks for ticks/mm\n",
               static_cast<long>(savedRightTicks), static_cast<long>(savedLeftTicks));
  }
}
// ============================================================================

// ============================================================================
#elif CAL_TEST == 3
// CAL TEST 3 -- live encoder read, no motor drive. Spin a wheel by hand and
// watch the counts change in real time. Useful to confirm each encoder responds
// correctly, in the expected direction, before trusting a full drive test.
// ============================================================================
namespace {
uint32_t lastPrintMs = 0;
} // namespace

void setup() {
  DBG_BEGIN(SERIAL_BAUD);
  delay(200);
  DBG_PRINTLN();
  DBG_PRINTLN("[ZoMa RX] CAL TEST 3 -- live encoder read (no motor drive)");
  DBG_PRINTLN("[CAL3] spin a wheel by hand, watch counts change below");

  motors::begin(); // keeps motors silenced, no drive commanded
  encoders::begin();
}

void loop() {
  if (millis() - lastPrintMs >= 200) {
    lastPrintMs = millis();
    DBG_PRINTF("[CAL3] right=%ld  left=%ld\n",
               static_cast<long>(encoders::rightCount()),
               static_cast<long>(encoders::leftCount()));
  }
}

#elif CAL_TEST == 4
// CAL_TEST == 4 -- bench test: forward/pause/reverse/pause, logging encoder deltas
// ============================================================================
namespace {

constexpr uint32_t PHASE_DURATION_MS = 5000;
constexpr uint32_t PAUSE_DURATION_MS = 2000;
constexpr uint32_t LOG_INTERVAL_MS = 500;

enum class Phase { FORWARD, PAUSE1, REVERSE, PAUSE2, DONE };

Phase phase = Phase::FORWARD;
uint32_t phaseStartMs = 0;
uint32_t lastLogMs = 0;
int32_t rightAtPhaseStart = 0;
int32_t leftAtPhaseStart = 0;

const char* phaseName(Phase p) {
  switch (p) {
    case Phase::FORWARD: return "FORWARD";
    case Phase::PAUSE1: return "PAUSE";
    case Phase::REVERSE: return "REVERSE";
    case Phase::PAUSE2: return "PAUSE";
    case Phase::DONE: return "DONE";
  }
  return "?";
}

void enterPhase(Phase p) {
  phase = p;
  phaseStartMs = millis();
  rightAtPhaseStart = encoders::rightCount();
  leftAtPhaseStart = encoders::leftCount();

  switch (p) {
    case Phase::FORWARD:
      motors::setRight(TEST_DUTY);
      motors::setLeft(TEST_DUTY);
      break;
    case Phase::REVERSE:
      motors::setRight(-TEST_DUTY);
      motors::setLeft(-TEST_DUTY);
      break;
    case Phase::PAUSE1:
    case Phase::PAUSE2:
    case Phase::DONE:
      motors::stop();
      break;
  }

  DBG_PRINTLN();
  DBG_PRINTF("[ZoMa Brain RX] entering phase: %s\n", phaseName(p));
}

void logStatus() {
  int32_t right = encoders::rightCount();
  int32_t left = encoders::leftCount();
  DBG_PRINTF("[%s] t=%lums right=%ld (d=%ld) left=%ld (d=%ld)\n", phaseName(phase),
             static_cast<unsigned long>(millis() - phaseStartMs), static_cast<long>(right),
             static_cast<long>(right - rightAtPhaseStart), static_cast<long>(left),
             static_cast<long>(left - leftAtPhaseStart));
}

} // namespace

void setup() {
  DBG_BEGIN(SERIAL_BAUD);
  delay(200);
  DBG_PRINTLN("[ZoMa Brain RX] motor + encoder bench test starting");

  motors::begin();
  encoders::begin();

  enterPhase(Phase::FORWARD);
}

void loop() {
  uint32_t now = millis();
  uint32_t elapsed = now - phaseStartMs;

  if (phase != Phase::DONE && now - lastLogMs >= LOG_INTERVAL_MS) {
    logStatus();
    lastLogMs = now;
  }

  switch (phase) {
    case Phase::FORWARD:
      if (elapsed >= PHASE_DURATION_MS) enterPhase(Phase::PAUSE1);
      break;
    case Phase::PAUSE1:
      if (elapsed >= PAUSE_DURATION_MS) enterPhase(Phase::REVERSE);
      break;
    case Phase::REVERSE:
      if (elapsed >= PHASE_DURATION_MS) enterPhase(Phase::PAUSE2);
      break;
    case Phase::PAUSE2:
      if (elapsed >= PAUSE_DURATION_MS) enterPhase(Phase::DONE);
      break;
    case Phase::DONE:
      break;
  }
}

// ============================================================================
#elif CAL_TEST == 5
// CAL TEST 5 -- BNO055 bring-up: live yaw/pitch/roll serial log, no motor drive.
// Bench procedure: place ZoMa flat on the bench, confirm yaw/pitch/roll all read
// ~0, then turn it by hand ~90 degrees and confirm yaw tracks to ~90 (+/- a few
// degrees). IMUPLUS mode (see bno055.cpp) gives a RELATIVE heading, not a compass
// bearing, so yaw@boot is always ~0 by construction -- that's expected, not a
// coincidence.
// ============================================================================
void setup() {
  DBG_BEGIN(SERIAL_BAUD);
  delay(200);
  DBG_PRINTLN();
  DBG_PRINTLN("[ZoMa RX] CAL TEST 5 -- BNO055 bring-up (no motor drive)");

  motors::begin(); // keeps motors silenced, no drive commanded

  if (!bno055::begin()) {
    DBG_PRINTF("[CAL5] BNO055 not detected -- check wiring (VIN=3V3, GND, SDA=%d, SCL=%d)\n",
               pins::IMU_SDA, pins::IMU_SCL);
  } else {
    DBG_PRINTLN("[CAL5] BNO055 ready -- place flat, confirm ~0/0/0, then turn by hand");
  }
}

void loop() {
  bno055::update();
  bno055::log();
}

// ============================================================================
#else
// CAL_TEST == 0 -- DRIVE MODE (default)
//   ESP-NOW receive -> input arbitration -> arcade kinematics -> motors,
//   running continuously. Watchdog and e-stop override unconditionally.
//
// INPUT MODEL (GT7-style):
//   - Left stick: proportional throttle/steering.
//   - R2/L2: adaptive 0-100% power, forward (R2) / reverse (L2), independent
//     of D-pad state. Both engage heading-hold, latched to yaw at the moment
//     either trigger is first pressed -- same behavior as D-pad Up/Down.
//   - D-pad: fixed-magnitude crawl (DPAD_MAGNITUDE). Up/Down drive straight
//     with heading-hold latched to the yaw at the moment the button is first
//     pressed; Left/Right turn freely, not locked to any heading.
//   - Priority when multiple are active at once: stick > R2/L2 > D-pad. Only
//     one source drives the motors on any given tick.
//   - Safety interlock: if R2 and L2 are both pressed at the same time, ALL
//     trigger-driven power is withheld until at least one of them is fully
//     released (back to raw 0) -- not just back under its deadzone.
// ============================================================================
namespace {

using espnow_rx::ControlPacket;

constexpr int16_t STICK_DEADZONE = 8;
constexpr uint8_t TRIGGER_DEADZONE = 8; // same reasoning as STICK_DEADZONE, R2/L2 side

// Bench-tunable. TX sends at ~50Hz (20ms), so 300ms is ~15 missed packets before
// the watchdog trips -- generous margin against a single dropped frame, tight
// enough that a real link loss (TX powered off / out of range) stops the robot
// quickly. Re-tune on the bench if this feels too twitchy or too slow to react.
constexpr uint32_t RECEIVE_TIMEOUT_MS = 300;

constexpr uint32_t LOG_INTERVAL_MS = 200; // throttle serial so it doesn't flood

// E-stop buttons: Options or Share, either one alone trips it -- OR semantics,
// since requiring a precise simultaneous double-press is the wrong trade-off
// for a safety stop.
constexpr uint32_t ESTOP_BUTTON_MASK = espnow_rx::BTN_OPTIONS | espnow_rx::BTN_SHARE;

int16_t applyDeadzone(int16_t value) {
  return (abs(value) < STICK_DEADZONE) ? 0 : value;
}

ControlPacket lastKnownPacket = {};
bool haveKnownPacket = false;
uint32_t lastLogMs = 0;
int16_t prevOutL = 0;
int16_t prevOutR = 0;
int16_t lastOutL = 0;
int16_t lastOutR = 0;

// Reuses RIGHT_TRIM/LEFT_TRIM and trimmedDuty() from the CAL_TEST 1/2 code above
// (same physical motors/gearbox, same file) -- do not introduce a second,
// divergent pair of trim constants here.
constexpr int16_t MOTOR_MIN_PWM = 40; // minimum duty to defeat static friction

// Slew-rate limit on mixAndDrive()'s output, in duty counts per ~20ms call (TX's
// send rate). MOTOR_DECEL_STEP (heading toward zero, or already reversing but not
// yet past it) stays large so stopping/braking is still snappy. MOTOR_ACCEL_STEP
// (pushing further into the CURRENT direction, or past zero into a new one) is the
// slow one -- this is what stops a hard stick flick from instantly reversing the
// DRV8833 H-bridge at full duty (a "plugging" event: full-current braking-then-
// reversing, which is the whine/stall). Bench-tune both by feel, same as
// RIGHT_TRIM/LEFT_TRIM above.
constexpr int16_t MOTOR_ACCEL_STEP = 15;
constexpr int16_t MOTOR_DECEL_STEP = 80; // ~3 calls (~64ms) to bring full duty to 0

// Retreating = heading toward zero, still reversing (opposite sign from prev,
// hasn't crossed yet), or literally zero -- the fast case, MOTOR_DECEL_STEP.
// Anything else (growing further in the current direction, or freshly pushing
// off in a new direction after crossing zero) is acceleration, capped at the
// slower MOTOR_ACCEL_STEP.
int16_t rateLimitOutput(int16_t target, int16_t prev) {
  bool retreating = (target == 0) ||
                     (prev != 0 && ((target > 0) != (prev > 0))) ||
                     (prev != 0 && (target > 0) == (prev > 0) && abs(target) < abs(prev));
  int16_t maxStep = retreating ? MOTOR_DECEL_STEP : MOTOR_ACCEL_STEP;

  int16_t delta = target - prev;
  if (delta > maxStep) delta = maxStep;
  if (delta < -maxStep) delta = -maxStep;
  return prev + delta;
}

// ---- D-PAD: FIXED-MAGNITUDE CRAWL ----
// R2/L2 are independent throttle inputs (see TRIGGER section below), so D-pad
// just always commands this one fixed magnitude. Bench-tuned: gives a
// sensitive/responsive crawl that reliably breaks static friction immediately.
// Same raw -128..127 throttle/steering scale mixAndDrive() works in (doubled to
// -255..255 in its own hardware-scaling step), NOT raw PWM duty.
constexpr int16_t DPAD_MAGNITUDE = 100;

// ---- R2/L2: ADAPTIVE GT7-STYLE THROTTLE/BRAKE ----
// R2 = forward, L2 = reverse, each independently proportional 0..255 raw ->
// 0..MAX_TRIGGER_MAGNITUDE (100%) in the same pre-doubling scale D-pad/stick
// use. No fixed floor here (unlike D-pad) -- true adaptive-from-zero feel;
// the stiction floor downstream in mixAndDrive() already handles "too small
// to actually move" uniformly for every input source.
constexpr int16_t MAX_TRIGGER_MAGNITUDE = 127; // 100% -- same ceiling as full stick deflection

int16_t triggerMagnitude(uint8_t raw) {
  return static_cast<int16_t>((static_cast<int32_t>(raw) * MAX_TRIGGER_MAGNITUDE) / 255);
}

// Both-triggers safety interlock -- latched, not just an instantaneous check:
// once both R2 and L2 read pressed (above TRIGGER_DEADZONE) in the same tick,
// ALL trigger-driven power is withheld until at least one of them reads back
// to a literal raw 0 (fully let go, not just back under the deadzone).
bool triggersBlocked = false;

// ---- HEADING HOLD (D-pad straight AND R2/L2 -- everything straight/reverse) ----
// A P-controller keyed off bno055::yawDegrees() (read after bno055::update()
// each tick). Both D-pad Up/Down and R2/L2 latch a target yaw on first press and
// steer to hold it; D-pad Left/Right (turning) deliberately never engages it,
// since a turn means the heading is supposed to change.
constexpr float HEADING_HOLD_KP = 3.0f;
constexpr int16_t HEADING_HOLD_MAX_CORRECTION = 60;

// Deadband around the P-controller's zero-error point, to avoid chatter right at
// the boundary. Raise it if heading-hold chatters/hunts, lower it if it feels
// loose on long straight drives.
constexpr float HEADING_HOLD_DEADBAND_DEG = 1.0f;

bool headingHoldActive = false;
float headingHoldTargetYaw = 0.0f;

// Shortest signed angular difference target-current, wrapped to [-180,180).
float angleError(float target, float current) {
  return fmodf(target - current + 540.0f, 360.0f) - 180.0f;
}

// Called whenever the watchdog/e-stop path forces motors::stop() directly
// (bypassing mixAndDrive) -- resets the slew-rate ramp memory, heading-hold,
// and the trigger interlock, so resuming afterward starts clean instead of
// carrying stale state across a disconnect or e-stop.
void resetDriveRamp() {
  prevOutL = 0;
  prevOutR = 0;
  headingHoldActive = false;
  triggersBlocked = false;
}

void mixAndDrive(int16_t throttle, int16_t steering) {
  // 1. DIRECTION TOGGLES
  // Throttle sign is already corrected once, at the REP-103-style convention
  // fixup in loop() below, so no further negation is needed here.
  float drive = (float)-throttle;
  // Steering matches TX's real LX axis directly.
  float turn = (float)steering;

  // 2. Standard Arcade Mix
  float leftF  = drive + turn;
  float rightF = drive - turn;

  // 3. Hardware Scaling and Right-Side Motor Inversion
  int16_t outL = (int16_t)constrain(leftF  * 2.0f, -255.0f, 255.0f);
  int16_t outR = (int16_t)constrain(rightF * 2.0f, -255.0f, 255.0f); // negated: corrects right wheel wiring

  // 4. Stiction floor (stateless: clamps any nonzero output up to the floor)
  if (outL > 0 && outL < MOTOR_MIN_PWM)        outL = MOTOR_MIN_PWM;
  else if (outL < 0 && outL > -MOTOR_MIN_PWM)  outL = -MOTOR_MIN_PWM;

  if (outR > 0 && outR < MOTOR_MIN_PWM)       outR = MOTOR_MIN_PWM;
  else if (outR < 0 && outR > -MOTOR_MIN_PWM) outR = -MOTOR_MIN_PWM;

  // 5. Trim
  outL = trimmedDuty(outL, LEFT_TRIM);
  outR = trimmedDuty(outR, RIGHT_TRIM);

  // 6. Slew-rate limit -- see the MOTOR_ACCEL_STEP/MOTOR_DECEL_STEP comment above.
  outL = rateLimitOutput(outL, prevOutL);
  outR = rateLimitOutput(outR, prevOutR);
  prevOutL = outL;
  prevOutR = outR;

  lastOutL = outL;
  lastOutR = outR;

  motors::setLeft(outL);
  motors::setRight(outR);
}

void logDriveState(int16_t rawThrottle, int16_t rawSteering, int16_t throttle, int16_t steering,
                    bool linkUp, const char* source) {
  if (millis() - lastLogMs < LOG_INTERVAL_MS) return;
  lastLogMs = millis();
  // Right stick (rx/ry) omitted -- not wired into drive output.
  DBG_PRINTF("[DRIVE] link=%s src=%-6s ms_since_pkt=%lu | LX raw=%4d filt=%4d LY raw=%4d filt=%4d | "
             "R2=%3d L2=%3d blocked=%d | thr=%4d str=%4d | outL=%4d outR=%4d | yaw=%6.1f\n",
             linkUp ? "UP" : "DOWN", source, static_cast<unsigned long>(espnow_rx::msSinceLastPacket()),
             rawSteering, applyDeadzone(rawSteering), rawThrottle, applyDeadzone(rawThrottle),
             lastKnownPacket.r2, lastKnownPacket.l2, triggersBlocked ? 1 : 0, throttle, steering,
             lastOutL, lastOutR, bno055::yawDegrees());
}

} // namespace

void setup() {
  DBG_BEGIN(SERIAL_BAUD);
  delay(200);
  DBG_PRINTLN();
  DBG_PRINTLN("==================================================");
  DBG_PRINTLN("   ZoMa  R X   -- drive receiver (motors + ESP-NOW recv)");
  DBG_PRINTF( "   This board's MAC: %s\n", WiFi.macAddress().c_str());
  DBG_PRINTLN("==================================================");
  DBG_PRINTLN("[ZoMa RX] drive mode -- stick > R2/L2 > D-pad priority, arcade kinematics");

  motors::begin();
  encoders::begin();

  if (!espnow_rx::begin()) {
    DBG_PRINTLN("[ZoMa RX] Fatal: ESP-NOW failed to initialize -- no drive commands will arrive");
  }

  if (!bno055::begin()) {
    DBG_PRINTLN("[ZoMa RX] Warning: BNO055 not detected -- heading-hold disabled, "
                "drive continues without it");
  }
}

void loop() {
  ControlPacket packet;
  if (espnow_rx::getLatestPacket(packet)) {
    lastKnownPacket = packet;
    haveKnownPacket = true;
  }

  // Feeds bno055::yawDegrees() for heading-hold below. Single minimal I2C
  // transaction, rate-limited internally to ~50Hz -- see bno055.cpp/.h for why
  // this must stay the only sensor read on this fast path.
  bno055::update();

  bool linkUp = haveKnownPacket && espnow_rx::msSinceLastPacket() <= RECEIVE_TIMEOUT_MS;

  int16_t rawThrottle = 0;
  int16_t rawSteering = 0;
  int16_t throttle = 0;
  int16_t steering = 0;
  bool estopActive = false;
  const char* source = "IDLE";

  if (linkUp) {
    rawThrottle = lastKnownPacket.throttle;
    rawSteering = lastKnownPacket.steering;

    int16_t filteredThrottle = applyDeadzone(rawThrottle);
    int16_t filteredSteering = applyDeadzone(rawSteering);
    bool stickActive = (filteredThrottle != 0) || (filteredSteering != 0);

    // Trigger interlock -- checked every tick regardless of which priority
    // branch ends up driving, so a stale block clears even while the stick or
    // D-pad is what's actually being used at the moment.
    bool r2Pressed = lastKnownPacket.r2 > TRIGGER_DEADZONE;
    bool l2Pressed = lastKnownPacket.l2 > TRIGGER_DEADZONE;
    if (lastKnownPacket.r2 == 0 || lastKnownPacket.l2 == 0) {
      triggersBlocked = false;
    }
    if (r2Pressed && l2Pressed) {
      triggersBlocked = true;
    }
    bool triggersActive = (r2Pressed || l2Pressed) && !triggersBlocked;

    bool dpadActive = (lastKnownPacket.buttons &
                        (espnow_rx::BTN_UP | espnow_rx::BTN_DOWN | espnow_rx::BTN_LEFT |
                         espnow_rx::BTN_RIGHT)) != 0;
    bool dpadForward = (lastKnownPacket.buttons & (espnow_rx::BTN_UP | espnow_rx::BTN_DOWN)) != 0;
    bool dpadTurning = (lastKnownPacket.buttons & (espnow_rx::BTN_LEFT | espnow_rx::BTN_RIGHT)) != 0;

    // ---- PRIORITY 1: left stick ----
    if (stickActive) {
      source = "STICK";
      // Throttle sign convention: positive = forward (REP-103-style, matching
      // the project's odometry work). The PS5 stick's Y axis reads negative
      // when pushed forward/up; TX sends it raw and un-negated (dumb pass-
      // through), so the negation happens here, once, at the RX boundary.
      throttle = static_cast<int16_t>(-filteredThrottle);
      // Steering sign not flipped -- independent of the throttle sign on this
      // wiring.
      steering = filteredSteering;
      headingHoldActive = false;

    // ---- PRIORITY 2: R2/L2 -- adaptive forward/reverse, GT7-style, with
    // heading-hold identical to D-pad Up/Down. ----
    } else if (triggersActive) {
      source = "TRIG";

      float currentYaw = bno055::yawDegrees();
      if (!headingHoldActive) {
        // Latches the instant R2 or L2 first crosses the deadzone -- releasing
        // and re-pressing re-targets to wherever the robot is now facing.
        headingHoldTargetYaw = currentYaw;
        headingHoldActive = true;
      }
      float error = angleError(headingHoldTargetYaw, currentYaw);
      // Deadband -- see HEADING_HOLD_DEADBAND_DEG's comment above. Correction
      // stays exactly 0 (not just small) inside the deadband.
      int16_t correction = 0;
      if (fabsf(error) > HEADING_HOLD_DEADBAND_DEG) {
        correction = static_cast<int16_t>(constrain(error * HEADING_HOLD_KP,
                                           (float)-HEADING_HOLD_MAX_CORRECTION,
                                           (float)HEADING_HOLD_MAX_CORRECTION));
      }
      steering = correction;

      if (r2Pressed) {
        // Sign matches D-pad's BTN_UP below -- both are "forward" through the
        // exact same mixAndDrive(), so they share the same empirical sign.
        throttle = -triggerMagnitude(lastKnownPacket.r2);
      } else { // l2Pressed
        throttle =  triggerMagnitude(lastKnownPacket.l2);
      }

      // Rate-limited diagnostic print of heading-hold tracking while R2/L2 drive.
      static uint32_t lastHoldDebugMsTrig = 0;
      if (millis() - lastHoldDebugMsTrig > 150) {
        lastHoldDebugMsTrig = millis();
        DBG_PRINTF("[HOLD-TRIG] target=%6.1f current=%6.1f error=%6.1f correction=%4d\n",
                   headingHoldTargetYaw, currentYaw, error, correction);
      }

    // ---- PRIORITY 3: D-pad -- fixed magnitude, heading-hold on straight. ----
    } else if (dpadActive) {
      source = "DPAD";
      throttle = 0;
      steering = 0;
      // BTN_UP/DOWN are net-negated once by mixAndDrive()'s internal
      // `-throttle` -- this sign is empirical, bench-confirmed.
      if (lastKnownPacket.buttons & espnow_rx::BTN_UP)    throttle = -DPAD_MAGNITUDE;
      if (lastKnownPacket.buttons & espnow_rx::BTN_DOWN)  throttle =  DPAD_MAGNITUDE;
      if (lastKnownPacket.buttons & espnow_rx::BTN_LEFT)  steering = -DPAD_MAGNITUDE;
      if (lastKnownPacket.buttons & espnow_rx::BTN_RIGHT) steering =  DPAD_MAGNITUDE;

      bool wantHeadingHold = dpadForward && !dpadTurning;
      if (wantHeadingHold) {
        float currentYaw = bno055::yawDegrees();
        if (!headingHoldActive) {
          // Latches the instant BTN_UP/BTN_DOWN is first pressed -- not a
          // fixed reference heading, so releasing and re-pressing the D-pad
          // re-targets to wherever the robot is now facing.
          headingHoldTargetYaw = currentYaw;
          headingHoldActive = true;
        }
        float error = angleError(headingHoldTargetYaw, currentYaw);
        int16_t correction = 0;
        if (fabsf(error) > HEADING_HOLD_DEADBAND_DEG) {
          correction = static_cast<int16_t>(constrain(error * HEADING_HOLD_KP,
                                             (float)-HEADING_HOLD_MAX_CORRECTION,
                                             (float)HEADING_HOLD_MAX_CORRECTION));
        }
        steering += correction;

        // Rate-limited diagnostic print of heading-hold tracking while D-pad drives.
        static uint32_t lastHoldDebugMs = 0;
        if (millis() - lastHoldDebugMs > 150) {
          lastHoldDebugMs = millis();
          DBG_PRINTF("[HOLD] target=%6.1f current=%6.1f error=%6.1f correction=%4d\n",
                     headingHoldTargetYaw, currentYaw, error, correction);
        }
      } else {
        headingHoldActive = false;
      }

    // ---- Nothing active. ----
    } else {
      headingHoldActive = false;
    }

    // RX-side e-stop check: TX no longer filters anything, so a held e-stop
    // combo in the received packet must independently zero all drive output
    // here, not just be trusted to have already been zeroed upstream.
    estopActive = (lastKnownPacket.buttons & ESTOP_BUTTON_MASK) != 0;
  } else {
    headingHoldActive = false;
  }

  // ---- Watchdog + e-stop: unconditional override, not a suggestion ----
  // No fresh packet within RECEIVE_TIMEOUT_MS, or the e-stop combo is held ->
  // motors::stop() every loop until a fresh, non-e-stopped packet arrives. When
  // the pad is centered and untouched this falls out naturally from the deadzone
  // + zero-throttle path above, but the watchdog/e-stop path here is what
  // guarantees it when the link itself is the problem.
  if (!linkUp || estopActive) {
    motors::stop();
    resetDriveRamp();
  } else {
    mixAndDrive(throttle, steering);
  }

  logDriveState(rawThrottle, rawSteering, throttle, steering, linkUp, source);

  delay(10);
}

#endif
