// ZoMa RX firmware — BNO055 IMU implementation.
// Property of TheMechanics. Contact: mamau.mechanics@gmail.com
//
// Reads yaw/pitch/roll (fast path) and quaternion/gyro/linear-acceleration
// (slow path) from the BNO055 in IMUPLUS mode, with glitch rejection and
// brownout/silent-reset recovery.

#include "bno055.h"

#include <Wire.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_BNO055.h>
#include <utility/imumaths.h>

#include "debug_macros.h"
#include "pins.h"

namespace bno055 {
namespace {

// Default I2C address 0x28 (0x29 if the ADR pin is pulled high instead of left
// floating/low). The "55" is just an arbitrary sensor ID the library tags its
// reports with.
Adafruit_BNO055 bno = Adafruit_BNO055(55, 0x28);

// Cached last-read values -- update() writes these, everything else (yawDegrees(),
// log(), the ROS-facing getters below) reads them, so the I2C bus only gets hit at
// READ_INTERVAL_MS instead of once per call site.
float cachedYaw = 0.0f, cachedPitch = 0.0f, cachedRoll = 0.0f;
uint8_t cachedSysCal = 0, cachedGyroCal = 0, cachedAccelCal = 0, cachedMagCal = 0;

// Quaternion: native sensor-fusion output, cached as-is (already unit normalized, no
// conversion needed).
float cachedQuatW = 1.0f, cachedQuatX = 0.0f, cachedQuatY = 0.0f, cachedQuatZ = 0.0f;

// Angular velocity: cached ALREADY CONVERTED to rad/s AND low-pass filtered -- see the
// EMA_ALPHA_GYRO note above refreshExtras() for why filtering is applied. The BNO055's
// default UNIT_SEL register reports gyroscope data in degrees/sec, not rad/s --
// accelerometer/linear-accel outputs are already in the SI units ROS expects (m/s^2)
// by that same default, so only the gyro needs an explicit conversion here.
// sensor_msgs/Imu requires rad/s per REP-103; get this wrong and every downstream
// angular-velocity consumer (EKF, Nav2) silently gets numbers ~57x too large.
float cachedGyroX = 0.0f, cachedGyroY = 0.0f, cachedGyroZ = 0.0f;

// Linear acceleration: BNO055's VECTOR_LINEARACCEL output, m/s^2, gravity already
// subtracted by the sensor's fusion, ALSO low-pass filtered for the same reason as
// gyro below. No unit conversion needed (raw accelerometer output would still include
// the ~9.8 m/s^2 gravity vector, which is NOT what sensor_msgs/Imu.linear_acceleration
// means -- the sensor's own fusion already handles that part).
float cachedAccelX = 0.0f, cachedAccelY = 0.0f, cachedAccelZ = 0.0f;

// 50Hz read rate -- fast enough for a heading-hold control loop without flooding
// the I2C bus on every 10ms main-loop tick.
constexpr unsigned long READ_INTERVAL_MS = 20;
unsigned long lastReadMillis = 0;

// BNO055 data doesn't need to print every 10ms main-loop tick -- that would scroll
// the monitor unreadably fast. 150ms is fast enough to see live movement while
// turning the robot by hand on the bench.
constexpr unsigned long LOG_INTERVAL_MS = 150;
unsigned long lastLogMillis = 0;

// ---- BROWNOUT / SILENT-RESET RECOVERY ----
// The BNO055 only loses gyro calibration like a rug pulled out from under it when it
// actually power-on-resets -- it doesn't drift back down gradually. If it was
// previously calibrated (peakGyroCal >= 1) and suddenly reads gyroCal==0 with every
// axis pegged at exactly 0.0, that's a reset, most likely from a brief supply
// brownout or motor-switching noise on a shared rail. Decoupling the supply is the
// real fix; this is a software safety net so it recovers on its own instead of
// staying dead until the board is power-cycled.
uint8_t peakGyroCal = 0;
unsigned long lastRecoveryAttemptMillis = 0;
constexpr unsigned long RECOVERY_RETRY_INTERVAL_MS = 1000; // don't hammer bno.begin()

// One-shot flag consumed via consumeResetFlag() -- lets callers outside this module
// (e.g. heading-hold in main.cpp) know their previously-latched yaw target now
// refers to a reference frame that no longer exists, since IMUPLUS yaw is relative
// to whatever the sensor's internal state was at the moment it was (re)initialized.
bool hadReset = false;

// ---- YAW GLITCH REJECTION ----
// Rare, self-recovering events can make yaw jump to a wrong value for one or a few
// reads, which would otherwise cause heading-hold to see a huge apparent error and
// slam its correction. A real physical rotation faster than
// MAX_YAW_JUMP_DEG_PER_TICK in a single ~20ms update() tick isn't plausible for
// this robot -- anything bigger is treated as a corrupted read and rejected,
// keeping the prior tick's cached values instead. Generous on purpose: only meant
// to catch garbage reads, never meant to limit legitimate fast turns.
// MAX_CONSECUTIVE_REJECTS keeps this from freezing yaw forever if the "jump" turns
// out to be real and sustained -- after that many consecutive rejections, the
// sensor is trusted again rather than ignored indefinitely.
constexpr float MAX_YAW_JUMP_DEG_PER_TICK = 60.0f;
constexpr uint8_t MAX_CONSECUTIVE_REJECTS = 5;

bool haveValidYaw = false;
uint8_t consecutiveRejects = 0;

// Shortest signed angular difference a-b, wrapped to [-180,180) -- used only to
// sanity-check yaw jumps below.
float yawDelta(float a, float b) {
  return fmodf(a - b + 540.0f, 360.0f) - 180.0f;
}

// ---- GYRO/ACCEL LOW-PASS FILTERING ----
// While stationary, all three gyro axes sit near the sensor's own quantization
// floor; once the drive motors are active, all three axes see roughly equal-
// magnitude noise -- not concentrated in the yaw axis the way real rotation from
// straight driving would be. That pattern is motor-driver interference coupling
// into the sensor, not real motion, consistent with sharing a supply rail with
// the motor driver. Decoupling that rail is the real fix; this filter is a
// stopgap that reduces how much of that noise reaches downstream consumers.
//
// Simple exponential moving average (EMA): filtered = filtered*(1-a) + raw*a.
// Chosen over a heavier filter (moving-average window, IIR biquad, etc.) for its
// O(1) memory/compute and simplicity. Applied ONLY here in refreshExtras(), never
// in update() -- that function is deliberately still a single, minimal,
// unfiltered I2C read on the heading-hold control loop's fast path; filtering
// adds processing that measurably delays fresh yaw reaching that loop, so it
// stays decoupled here on the slower path instead.
//
// Alpha (smoothing factor): lower = more smoothing but more lag, higher = less
// smoothing but more noise passes through. Tune per rig: lower it if a filtered
// signal downstream is still oscillating, raise it if response feels sluggish.
constexpr float EMA_ALPHA_GYRO = 0.2f;
constexpr float EMA_ALPHA_ACCEL = 0.2f;

float filteredGyroX = 0.0f, filteredGyroY = 0.0f, filteredGyroZ = 0.0f;
float filteredAccelX = 0.0f, filteredAccelY = 0.0f, filteredAccelZ = 0.0f;
bool gyroFilterPrimed = false;  // avoids a slow ramp-up from 0 on first sample
bool accelFilterPrimed = false;

} // namespace

bool begin() {
  Wire.begin(pins::IMU_SDA, pins::IMU_SCL);

  if (!bno.begin()) {
    DBG_PRINTF("BNO055: Not detected -- check wiring (VIN=3V3, GND, SDA=%d, SCL=%d)\n",
               pins::IMU_SDA, pins::IMU_SCL);
    return false;
  }

  delay(1000); // Let the sensor's own boot self-test finish

  bno.setExtCrystalUse(true); // BNO055 has its own crystal; using it instead of the
                               // internal RC oscillator meaningfully improves accuracy

  // Drop the magnetometer out of the fusion -- IMUPLUS fuses gyro + accelerometer
  // only, giving a relative (not compass-true) heading that's immune to motor
  // magnetic interference.
  bno.setMode(OPERATION_MODE_IMUPLUS);

  DBG_PRINTLN("BNO055: Initialized (IMUPLUS mode -- relative yaw, no magnetometer)");
  return true;
}

void update() {
  if (millis() - lastReadMillis < READ_INTERVAL_MS) {
    return;
  }
  lastReadMillis = millis();

  // Euler angles in degrees. Axis order per Adafruit's library:
  //   x = heading/yaw (relative heading in IMUPLUS mode, 0-360)
  //   y = roll        (tips left/right)
  //   z = pitch       (tips nose up/down)
  // ...as seen by the SENSOR's own axes. The BNO055 is mounted rotated 90 degrees
  // in the horizontal plane relative to that assumption, so y/z are swapped below
  // to get roll/pitch labeled correctly for this robot's body frame. Yaw is
  // unaffected -- it's the vertical axis, which the horizontal-plane rotation
  // doesn't move. NOTE: this swap only fixes the human-readable Euler values read
  // here; getQuat()/VECTOR_GYROSCOPE/VECTOR_LINEARACCEL below still report in the
  // sensor's native (rotated) frame and aren't yet remapped -- fine while nothing
  // consumes them, but needs the same correction (ideally via the BNO055's own
  // axis-remap registers) before any of that feeds /imu/data or a tilt check.
  imu::Vector<3> euler = bno.getVector(Adafruit_BNO055::VECTOR_EULER);
  float rawYaw = euler.x();
  float rawRoll = euler.z();
  float rawPitch = euler.y();

  // Reject an implausible single-tick yaw jump -- see MAX_YAW_JUMP_DEG_PER_TICK's
  // comment above. The whole Euler vector comes from one I2C burst read, so if yaw
  // looks corrupted, treat roll/pitch from the same read as suspect too and keep
  // last tick's values for all three rather than just yaw.
  bool acceptSample = true;
  if (haveValidYaw) {
    float jump = fabsf(yawDelta(rawYaw, cachedYaw));
    if (jump > MAX_YAW_JUMP_DEG_PER_TICK && consecutiveRejects < MAX_CONSECUTIVE_REJECTS) {
      acceptSample = false;
      consecutiveRejects++;
      DBG_PRINTF("BNO055: rejected implausible yaw jump (%.1f -> %.1f, delta=%.1f) -- likely I2C/noise glitch\n",
                 cachedYaw, rawYaw, jump);
    }
  }

  if (acceptSample) {
    consecutiveRejects = 0;
    haveValidYaw = true;
    cachedYaw = rawYaw;
    cachedRoll = rawRoll;
    cachedPitch = rawPitch;
  }
  // else: cachedYaw/cachedRoll/cachedPitch simply keep their prior values this tick.

  bno.getCalibration(&cachedSysCal, &cachedGyroCal, &cachedAccelCal, &cachedMagCal);

  if (cachedGyroCal > peakGyroCal) {
    peakGyroCal = cachedGyroCal;
  }

  bool looksReset = (peakGyroCal >= 1 && cachedGyroCal == 0 && cachedYaw == 0.0f &&
                      cachedPitch == 0.0f && cachedRoll == 0.0f);

  if (looksReset && millis() - lastRecoveryAttemptMillis > RECOVERY_RETRY_INTERVAL_MS) {
    lastRecoveryAttemptMillis = millis();
    DBG_PRINTLN("BNO055: Looks like it reset (motor noise?) -- reinitializing...");
    if (bno.begin()) {
      bno.setExtCrystalUse(true);
      bno.setMode(OPERATION_MODE_IMUPLUS);
      peakGyroCal = 0; // let it re-climb fresh as it recalibrates
      haveValidYaw = false; // new reference frame -- next read is trusted unconditionally
      consecutiveRejects = 0;
      hadReset = true;
      DBG_PRINTLN("BNO055: Recovered");
    }
  }
}

void refreshExtras() {
  // Quaternion -- native fusion output, already unit-normalized. Preferred over
  // re-deriving a quaternion from the cached Euler angles, since the sensor's own
  // quaternion avoids gimbal-lock and Euler->quaternion conversion error. NOT filtered
  // here -- it's the sensor's own internal fusion output (already smoothed by the
  // BNO055's onboard filtering).
  imu::Quaternion q = bno.getQuat();
  cachedQuatW = q.w();
  cachedQuatX = q.x();
  cachedQuatY = q.y();
  cachedQuatZ = q.z();

  // Gyroscope -- native output is degrees/sec (default UNIT_SEL), so convert to rad/s
  // here, once, at the caching boundary -- every consumer of angularVelocity() then
  // gets correct SI units without needing to know about this sensor-specific quirk.
  // Then EMA-filtered -- see the EMA_ALPHA_GYRO comment above for why.
  imu::Vector<3> gyro = bno.getVector(Adafruit_BNO055::VECTOR_GYROSCOPE);
  const float GYRO_DEG_TO_RAD = PI / 180.0f;
  float rawGyroX = gyro.x() * GYRO_DEG_TO_RAD;
  float rawGyroY = gyro.y() * GYRO_DEG_TO_RAD;
  float rawGyroZ = gyro.z() * GYRO_DEG_TO_RAD;

  if (!gyroFilterPrimed) {
    // First sample: seed the filter directly rather than starting from 0.0f, which
    // would otherwise take several EMA_ALPHA_GYRO-weighted cycles to "catch up" to the
    // real value and would show up as a fake ramp on every boot.
    filteredGyroX = rawGyroX;
    filteredGyroY = rawGyroY;
    filteredGyroZ = rawGyroZ;
    gyroFilterPrimed = true;
  } else {
    filteredGyroX += EMA_ALPHA_GYRO * (rawGyroX - filteredGyroX);
    filteredGyroY += EMA_ALPHA_GYRO * (rawGyroY - filteredGyroY);
    filteredGyroZ += EMA_ALPHA_GYRO * (rawGyroZ - filteredGyroZ);
  }
  cachedGyroX = filteredGyroX;
  cachedGyroY = filteredGyroY;
  cachedGyroZ = filteredGyroZ;

  // Linear acceleration -- already m/s^2, gravity-compensated by the sensor's fusion.
  // No unit conversion needed, but same EMA filtering applied as gyro above, same
  // motor-noise reasoning.
  imu::Vector<3> linAccel = bno.getVector(Adafruit_BNO055::VECTOR_LINEARACCEL);
  float rawAccelX = linAccel.x();
  float rawAccelY = linAccel.y();
  float rawAccelZ = linAccel.z();

  if (!accelFilterPrimed) {
    filteredAccelX = rawAccelX;
    filteredAccelY = rawAccelY;
    filteredAccelZ = rawAccelZ;
    accelFilterPrimed = true;
  } else {
    filteredAccelX += EMA_ALPHA_ACCEL * (rawAccelX - filteredAccelX);
    filteredAccelY += EMA_ALPHA_ACCEL * (rawAccelY - filteredAccelY);
    filteredAccelZ += EMA_ALPHA_ACCEL * (rawAccelZ - filteredAccelZ);
  }
  cachedAccelX = filteredAccelX;
  cachedAccelY = filteredAccelY;
  cachedAccelZ = filteredAccelZ;
}

float yawDegrees() {
  return cachedYaw;
}

bool consumeResetFlag() {
  bool result = hadReset;
  hadReset = false;
  return result;
}

void quaternion(float& w, float& x, float& y, float& z) {
  w = cachedQuatW;
  x = cachedQuatX;
  y = cachedQuatY;
  z = cachedQuatZ;
}

void angularVelocity(float& x, float& y, float& z) {
  x = cachedGyroX;
  y = cachedGyroY;
  z = cachedGyroZ;
}

void linearAcceleration(float& x, float& y, float& z) {
  x = cachedAccelX;
  y = cachedAccelY;
  z = cachedAccelZ;
}

void log() {
  if (millis() - lastLogMillis < LOG_INTERVAL_MS) {
    return;
  }
  lastLogMillis = millis();

  DBG_PRINTF("IMU -> Yaw:%7.2f  Pitch:%7.2f  Roll:%7.2f  | Cal(sys/gyro/acc/mag): %d/%d/%d/%d\n",
             cachedYaw, cachedPitch, cachedRoll, cachedSysCal, cachedGyroCal,
             cachedAccelCal, cachedMagCal);
}

} // namespace bno055
