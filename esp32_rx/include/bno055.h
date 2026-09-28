// ZoMa RX firmware — BNO055 IMU interface.
// Property of TheMechanics. Contact: mamau.mechanics@gmail.com
//
// Public API for the BNO055 orientation sensor: fast yaw for the drive control
// loop, plus a slower quaternion/gyro/accel path for future ROS publishing.

#pragma once

// BNO055 IMU over I2C (SDA/SCL from pins.h), driven in IMUPLUS mode (gyro +
// accelerometer fusion, no magnetometer) so yaw is a relative heading, not a
// compass bearing.
namespace bno055 {

// Initializes the sensor. Returns false if it isn't found on the bus (check
// wiring/address) -- callers should treat that as non-fatal (log a warning,
// keep running without IMU data) rather than halting.
bool begin();

// Refreshes the cached yaw/pitch/roll + calibration reading from the sensor.
// Internally rate-limited (~50Hz) so it's safe to call every loop() tick without
// hammering the I2C bus. Call this once per loop, before reading yawDegrees().
//
// Deliberately does ONLY the Euler + calibration read -- a single, minimal I2C
// transaction. A heading-hold control loop depends on yawDegrees() being fresh
// and low-latency every tick; folding the slower quaternion/gyro/linaccel reads
// in here would add blocking I2C time and measurably degrade responsiveness.
// See refreshExtras() below for where those other reads live instead.
void update();

// Returns the most recently cached yaw/heading in degrees, 0..359.99. Reflects
// whatever update() last read -- call update() once per loop before using this.

// True if the sensor was detected to have silently reset (e.g. a brief supply
// brownout) and was reinitialized since the last call to this function. Clears
// itself on read (one-shot). Any consumer relying on yaw being in a STABLE
// reference frame across calls (e.g. heading-hold's latched target) should
// treat a true return as "my old target is now meaningless, re-latch fresh"
// rather than continuing to chase a target defined before the reset.
bool consumeResetFlag();

float yawDegrees();

// ---- FOR FUTURE /imu/data PUBLISHING (not yet wired to anything) ----
// These read from a SEPARATE cache, refreshed only by refreshExtras() below -- NOT
// by update(). Call refreshExtras() once, right before reading any of these three,
// at whatever rate data is actually being consumed (e.g. a ROS publish rate)
// rather than every control-loop tick. See refreshExtras()'s comment for why.

// Does the actual I2C reads for quaternion, angular velocity, and linear
// acceleration, caching all three. Deliberately NOT folded into update() -- see
// that function's comment. These extra reads are only needed for downstream
// consumers (e.g. ROS /imu/data) that run at a much lower, decoupled rate.
void refreshExtras();

// Absolute orientation as a unit quaternion (sensor-fusion output, not derived
// from the cached Euler angles -- the BNO055 computes this natively and it's the
// numerically better representation to hand to ROS/EKF). Reflects whatever
// refreshExtras() last read.
void quaternion(float& w, float& x, float& y, float& z);

// Angular velocity in rad/s (converted from the sensor's native deg/s -- see
// bno055.cpp). Reflects whatever refreshExtras() last read.
void angularVelocity(float& x, float& y, float& z);

// Linear acceleration in m/s^2, gravity-compensated (BNO055's VECTOR_LINEARACCEL
// output, not raw accelerometer -- already excludes the ~9.8 m/s^2 gravity
// component, which is what sensor_msgs/Imu expects). Reflects whatever
// refreshExtras() last read.
void linearAcceleration(float& x, float& y, float& z);

// Prints the cached orientation + calibration state to Serial (via DBG_*) in a
// human-readable, rate-limited (~150ms) line. Safe to call every loop() tick.
void log();

} // namespace bno055
