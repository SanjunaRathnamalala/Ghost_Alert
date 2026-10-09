/*
 * Ghost_Alert landslide node: Pro Mini 3.3V/8MHz + Ra-02 + ADXL362 + capacitive soil sensor.
 *
 * - Soil sensor is powered (from a pin) only while reading.
 * - Every SAMPLE_S: one soil reading. Every 5 readings: one heartbeat packet
 *   (averaged accel x/y/z, the 5 soil readings, battery, temperature, flags).
 * - Between readings: deep sleep. The ADXL362 wakes the node on movement
 *   -> a motion "burst" packet (at most one per 30 s), sent twice.
 */
#include "ga_node.h"

// ======== settings ========
#define NODE_RADIO_ID 1          // GA-LS-001 in the database
#define FW_VERSION    1
#define DEMO_MODE     1          // 1 = fast (reading every 8 s, heartbeat every 40 s); 0 = field timing

#if DEMO_MODE
  #define SAMPLE_S  8
  #define JITTER_S  2
#else
  #define SAMPLE_S  60
  #define JITTER_S  10             // random delay before each heartbeat (decision 2.11)
#endif
#define BURST_MIN_GAP_S 30
#define ACT_THRESH_MG   50       // movement that wakes the node (about 3 degrees of tilt)

// ======== pins ========
#define PIN_ADXL_CS   8
#define PIN_ADXL_INT  2          // ADXL362 INT1
#define PIN_SOIL_PWR  7          // soil sensor VCC (powered only while reading)
#define PIN_SOIL      A0         // soil sensor AOUT
#define PIN_BATT      -1         // A1 if a 1M+1M battery divider is fitted, else -1

// ======== ADXL362 (raw SPI registers) ========
SPISettings adxlSpi(1000000, MSBFIRST, SPI_MODE0);
bool accelOk = false;

uint8_t adxlRead(uint8_t reg) {
  SPI.beginTransaction(adxlSpi);
  digitalWrite(PIN_ADXL_CS, LOW);
  SPI.transfer(0x0B); SPI.transfer(reg);
  uint8_t v = SPI.transfer(0);
  digitalWrite(PIN_ADXL_CS, HIGH);
  SPI.endTransaction();
  return v;
}

void adxlWrite(uint8_t reg, uint8_t v) {
  SPI.beginTransaction(adxlSpi);
  digitalWrite(PIN_ADXL_CS, LOW);
  SPI.transfer(0x0A); SPI.transfer(reg); SPI.transfer(v);
  digitalWrite(PIN_ADXL_CS, HIGH);
  SPI.endTransaction();
}

void adxlReadXYZ(int16_t &x, int16_t &y, int16_t &z) {   // mg (1 mg/LSB at +-2 g)
  uint8_t b[6];
  SPI.beginTransaction(adxlSpi);
  digitalWrite(PIN_ADXL_CS, LOW);
  SPI.transfer(0x0B); SPI.transfer(0x0E);
  for (uint8_t i = 0; i < 6; i++) b[i] = SPI.transfer(0);
  digitalWrite(PIN_ADXL_CS, HIGH);
  SPI.endTransaction();
  x = (int16_t)(b[0] | (b[1] << 8));
  y = (int16_t)(b[2] | (b[3] << 8));
  z = (int16_t)(b[4] | (b[5] << 8));
}

int16_t adxlTemp10() {                 // 0.1 degC, uncalibrated (typ. 350 LSB at 25 C, 0.065 C/LSB)
  int16_t raw = (int16_t)(adxlRead(0x14) | (adxlRead(0x15) << 8));
  return (int16_t)(250 + (raw - 350) * 0.65f);
}

void adxlArm() {                       // take a new reference position for movement detection
  adxlWrite(0x27, 0x00);
  adxlWrite(0x27, 0x03);               // activity enabled, referenced mode
  adxlRead(0x0B);                      // reading STATUS clears the interrupt
}

bool adxlInit() {
  adxlWrite(0x1F, 0x52);               // soft reset
  delay(10);
  if (adxlRead(0x00) != 0xAD || adxlRead(0x02) != 0xF2) return false;
  adxlWrite(0x2C, 0x11);               // +-2 g, half bandwidth, 25 Hz
  adxlWrite(0x20, ACT_THRESH_MG & 0xFF);
  adxlWrite(0x21, ACT_THRESH_MG >> 8);
  adxlWrite(0x22, 2);                  // movement must last 2 samples
  adxlWrite(0x2A, 0x10);               // activity -> INT1, active high
  adxlWrite(0x2D, 0x12);               // measurement mode, low noise
  delay(200);
  adxlArm();
  return true;
}

// Average n samples (25 Hz) -> tenths of mg. Averaging lowers the noise (decision: tilt noise).
void adxlAverage10(uint8_t n, int16_t &ax, int16_t &ay, int16_t &az) {
  long sx = 0, sy = 0, sz = 0;
  for (uint8_t i = 0; i < n; i++) {
    int16_t x, y, z;
    adxlReadXYZ(x, y, z);
    sx += x; sy += y; sz += z;
    delay(40);
  }
  ax = (int16_t)lroundf(sx * 10.0f / n);
  ay = (int16_t)lroundf(sy * 10.0f / n);
  az = (int16_t)lroundf(sz * 10.0f / n);
}

float tiltDeg(int16_t ax, int16_t ay, int16_t az) {   // for the serial printout only
  float mag = sqrtf((float)ax * ax + (float)ay * ay + (float)az * az);
  return mag > 0 ? degrees(acosf(az / mag)) : 0;
}

// ======== soil ========
uint16_t readSoil(uint8_t &flags) {
  digitalWrite(PIN_SOIL_PWR, HIGH);
  delay(400);                          // let the sensor output settle
  analogRead(PIN_SOIL);                // dummy read
  uint32_t s = 0;
  for (uint8_t i = 0; i < 8; i++) { s += analogRead(PIN_SOIL); delay(2); }
  digitalWrite(PIN_SOIL_PWR, LOW);
  uint16_t raw = s / 8;
  if (raw < 20 || raw > 1010) flags |= FLAG_SOIL_ERROR;   // unplugged / shorted
  Serial.print(F("[soil] raw=")); Serial.println(raw);
  return raw;
}

// ======== state ========
uint16_t soil[5];
uint8_t soilIdx = 0, soilFlags = 0;
int16_t lastAx = 0, lastAy = 0, lastAz = 10000;       // last resting position (tenths of mg)
bool burstSent = false;
uint32_t lastBurstAt = 0, nextSampleAt = 0;

void sendHeartbeat() {
  HeartbeatBody b;
  uint8_t flags = soilFlags;
  if (accelOk) {
    adxlAverage10(16, b.ax, b.ay, b.az);
    b.temp10 = adxlTemp10();
    lastAx = b.ax; lastAy = b.ay; lastAz = b.az;
  } else {
    b.ax = b.ay = b.az = 0; b.temp10 = 0;
    flags |= FLAG_ACCEL_ERROR;
  }
  memcpy(b.m, soil, sizeof soil);
  b.battMv = gaReadBatteryMv(PIN_BATT);
  if (PIN_BATT >= 0 && b.battMv < 3400) flags |= FLAG_BATT_LOW;
  b.flags = flags;
  Serial.print(F("[hb] tilt=")); Serial.print(tiltDeg(b.ax, b.ay, b.az), 3);
  Serial.print(F(" deg  temp=")); Serial.print(b.temp10 / 10.0, 1);
  Serial.print(F(" C  batt=")); Serial.print(b.battMv);
  Serial.print(F(" mV  flags=")); Serial.println(flags);
  gaSend(T_HEARTBEAT, &b, sizeof b, false);
}

void handleMotion() {
  // Watch the movement for 3 s and find its size and length.
  uint16_t peak = 0, moving = 0;
  for (uint8_t i = 0; i < 75; i++) {
    int16_t x, y, z;
    adxlReadXYZ(x, y, z);
    uint16_t dx = abs(x - lastAx / 10), dy = abs(y - lastAy / 10), dz = abs(z - lastAz / 10);
    uint16_t d = max(dx, max(dy, dz));
    if (d > peak) peak = d;
    if (d > ACT_THRESH_MG) moving++;
    delay(40);
  }
  BurstBody b;
  adxlAverage10(8, b.ax, b.ay, b.az);   // position after the movement
  b.peakMg = peak;
  b.durationS = (uint8_t)min(255, (moving * 40 + 999) / 1000);
  b.flags = 0;
  Serial.print(F("[motion] peak=")); Serial.print(peak);
  Serial.print(F(" mg  tilt now=")); Serial.println(tiltDeg(b.ax, b.ay, b.az), 3);
  if (!burstSent || gUptimeS - lastBurstAt >= BURST_MIN_GAP_S) {
    gaSend(T_BURST, &b, sizeof b, true);
    burstSent = true;
    lastBurstAt = gUptimeS;
  } else {
    Serial.println(F("[motion] not sent (less than 30 s since the last burst)"));
  }
  lastAx = b.ax; lastAy = b.ay; lastAz = b.az;
  adxlArm();
}

void setup() {
  pinMode(PIN_ADXL_CS, OUTPUT);  digitalWrite(PIN_ADXL_CS, HIGH);   // both chip selects HIGH
  pinMode(PIN_LORA_NSS, OUTPUT); digitalWrite(PIN_LORA_NSS, HIGH);  // before any SPI traffic
  pinMode(PIN_SOIL_PWR, OUTPUT); digitalWrite(PIN_SOIL_PWR, LOW);
  pinMode(PIN_ADXL_INT, INPUT);
  Serial.begin(9600);
  Serial.println(F("\nGhost_Alert landslide node"));

  gaLoadIdentity(NODE_RADIO_ID);
  Serial.print(F("radio ID=")); Serial.print(gRadio);
  Serial.print(F(" boot=")); Serial.print(gBoot);
  Serial.print(F(" reset reason=")); Serial.println(gResetReason);
  randomSeed(analogRead(A3) ^ (gBoot << 4) ^ gRadio);

  SPI.begin();
  accelOk = adxlInit();
  Serial.println(accelOk ? F("[adxl] OK") : F("[adxl] NOT FOUND - check wiring"));

  if (!gaLoraBegin()) {
    Serial.println(F("[lora] START FAILED - check wiring"));
    while (true) {}
  }
  Serial.println(F("[lora] OK 433.92 MHz SF9"));

  gaSendBoot(FW_VERSION, 1);           // node type 1 = landslide
  if (accelOk) {
    adxlAverage10(16, lastAx, lastAy, lastAz);
    gaEnablePinWake(PIN_ADXL_INT);
  }
  nextSampleAt = gUptimeS;
}

void loop() {
  if (gPinWake) {
    gPinWake = false;
    if (accelOk && digitalRead(PIN_ADXL_INT) == HIGH) handleMotion();
  }

  if (gUptimeS >= nextSampleAt) {
    if (soilIdx == 4) gaSleepSeconds(random(0, JITTER_S + 1));   // jitter before the heartbeat
    soil[soilIdx++] = readSoil(soilFlags);
    if (soilIdx == 5) {
      sendHeartbeat();
      soilIdx = 0;
      soilFlags = 0;
    }
    nextSampleAt += SAMPLE_S;
    if (nextSampleAt < gUptimeS) nextSampleAt = gUptimeS + SAMPLE_S;
  }

  if (nextSampleAt > gUptimeS) gaSleepSeconds(nextSampleAt - gUptimeS);
}