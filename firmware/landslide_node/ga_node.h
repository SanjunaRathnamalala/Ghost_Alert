// ga_node.h - shared code for Ghost_Alert nodes (Pro Mini 3.3V / 8 MHz + Ra-02).
// Keep this file IDENTICAL in landslide_node/ and pir_node/.
#pragma once
#include <Arduino.h>
#include <SPI.h>
#include <LoRa.h>
#include <EEPROM.h>
#include <avr/sleep.h>
#include <avr/wdt.h>
#include <avr/interrupt.h>

// ---------------- radio: MUST match the ESP32 gateway ----------------
#define LORA_FREQ    433920000L
#define LORA_SF      9
#define LORA_BW      125000L
#define LORA_CR      5
#define LORA_SYNC    0x12
#define LORA_TX_DBM  10            // bench value (lower current peaks); field: up to 17

#define PIN_LORA_NSS  10
#define PIN_LORA_RST  9
#define PIN_LORA_DIO0 3            // wired but not needed (sending is polled)

// ---------------- packet format (backend app/packets.py) ----------------
#define PKT_VERSION 1
enum { T_BOOT = 1, T_HEARTBEAT = 2, T_BURST = 3, T_PIR_EVENT = 4, T_PIR_HEARTBEAT = 5 };
#define FLAG_SOIL_ERROR  0x01
#define FLAG_ACCEL_ERROR 0x02
#define FLAG_BATT_LOW    0x04
#define SEAL_LEN 4

struct __attribute__((packed)) Header { uint8_t verType; uint16_t radio, boot, counter; };
struct __attribute__((packed)) BootBody { uint8_t fw, resetReason, nodeType; };
struct __attribute__((packed)) HeartbeatBody {
  int16_t ax, ay, az;              // tenths of mg
  uint16_t m[5];                   // 5 raw soil ADC readings, oldest first
  uint16_t battMv;
  int16_t temp10;                  // 0.1 degC
  uint8_t flags;
};
struct __attribute__((packed)) BurstBody { int16_t ax, ay, az; uint16_t peakMg; uint8_t durationS, flags; };
struct __attribute__((packed)) PirEventBody { uint8_t triggers; uint16_t battMv; uint8_t flags; };
struct __attribute__((packed)) PirHeartbeatBody { uint16_t triggers; uint16_t battMv; uint8_t flags; };

static_assert(sizeof(Header) == 7, "header must be 7 bytes");
static_assert(sizeof(HeartbeatBody) == 21, "heartbeat body must be 21 bytes");
static_assert(sizeof(BurstBody) == 10, "burst body must be 10 bytes");
static_assert(sizeof(PirEventBody) == 4, "pir event body must be 4 bytes");
static_assert(sizeof(PirHeartbeatBody) == 5, "pir heartbeat body must be 5 bytes");
static_assert(sizeof(BootBody) == 3, "boot body must be 3 bytes");

// ---------------- reset reason (read before the bootloader/core clears it) ----------------
uint8_t gResetReason __attribute__((section(".noinit")));
void gaSaveMcusr(void) __attribute__((naked, used, section(".init3")));
void gaSaveMcusr(void) { gResetReason = MCUSR; MCUSR = 0; wdt_disable(); }

// ---------------- identity: radio ID + boot number in EEPROM (decision 1.6) ----------------
#define ID_MAGIC 0x47
struct __attribute__((packed)) Identity { uint8_t magic; uint16_t radio; uint16_t boot; };
uint16_t gRadio = 0, gBoot = 0, gCounter = 0;

void gaLoadIdentity(uint16_t radioId) {
  Identity id;
  EEPROM.get(0, id);
  if (id.magic != ID_MAGIC) { id.magic = ID_MAGIC; id.boot = 0; }
  id.radio = radioId;              // prototype: the sketch sets the ID (a setup program comes later)
  id.boot++;
  if (id.boot == 0) id.boot = 1;
  EEPROM.put(0, id);               // put() only writes bytes that changed
  gRadio = id.radio;
  gBoot = id.boot;
}

uint16_t gaNextCounter() {
  if (gCounter == 0xFFFF) {        // counter wrapped: start a new "boot" so (boot, counter) still grows
    Identity id; EEPROM.get(0, id);
    id.boot++; EEPROM.put(0, id);
    gBoot = id.boot; gCounter = 0;
  }
  return ++gCounter;
}

// ---------------- sleep (watchdog timer + pin-change wake) ----------------
volatile bool gPinWake = false;
uint32_t gUptimeS = 0;             // seconds, counted from completed sleeps (approximate)

ISR(WDT_vect) {}
ISR(PCINT2_vect) { gPinWake = true; }

void gaEnablePinWake(uint8_t pin) {          // pins D0..D7 only
  PCMSK2 |= _BV(pin);
  PCIFR = _BV(PCIF2);
  PCICR |= _BV(PCIE2);
}

static void gaWdtArm(uint8_t bits) {
  cli();
  wdt_reset();
  MCUSR &= ~_BV(WDRF);
  WDTCSR = _BV(WDCE) | _BV(WDE);
  WDTCSR = _BV(WDIE) | bits;                 // interrupt only, never a reset
  sei();
}

static void gaPowerDown() {
  ADCSRA &= ~_BV(ADEN);
  set_sleep_mode(SLEEP_MODE_PWR_DOWN);
  cli();
  if (!gPinWake) {                           // never sleep with a wake-up already pending
    sleep_enable();
    sleep_bod_disable();
    sei();
    sleep_cpu();
    sleep_disable();
  }
  sei();
  ADCSRA |= _BV(ADEN);
}

// Sleep for `seconds`. Returns true if a pin change woke the node early.
bool gaSleepSeconds(uint32_t seconds) {
  Serial.flush();
  while (seconds > 0) {
    uint8_t step, bits;
    if (seconds >= 8)      { step = 8; bits = _BV(WDP3) | _BV(WDP0); }
    else if (seconds >= 4) { step = 4; bits = _BV(WDP3); }
    else if (seconds >= 2) { step = 2; bits = _BV(WDP2) | _BV(WDP1) | _BV(WDP0); }
    else                   { step = 1; bits = _BV(WDP2) | _BV(WDP1); }
    gaWdtArm(bits);
    gaPowerDown();
    wdt_disable();
    if (gPinWake) return true;
    gUptimeS += step;
    seconds -= step;
  }
  return false;
}

// ---------------- supply voltage (no extra parts: 1.1 V bandgap vs AVcc) ----------------
uint16_t gaReadVccMv() {
  ADMUX = _BV(REFS0) | _BV(MUX3) | _BV(MUX2) | _BV(MUX1);
  delay(2);
  ADCSRA |= _BV(ADSC);
  while (bit_is_set(ADCSRA, ADSC)) {}
  uint16_t r = ADC;
  return r ? (uint16_t)(1126400UL / r) : 0;  // approximate: bandgap is 1.1 V +-10 %
}

// Battery: through a 1M + 1M divider on battPin, or the supply voltage if battPin < 0.
uint16_t gaReadBatteryMv(int8_t battPin) {
  uint16_t vcc = gaReadVccMv();
  if (battPin < 0) return vcc;
  analogRead(battPin);                       // dummy read after changing the reference
  uint32_t s = 0;
  for (uint8_t i = 0; i < 4; i++) s += analogRead(battPin);
  return (uint16_t)((s / 4) * (uint32_t)vcc / 1023UL * 2UL);
}

// ---------------- LoRa ----------------
bool gaLoraBegin() {
  pinMode(PIN_LORA_NSS, OUTPUT);
  digitalWrite(PIN_LORA_NSS, HIGH);
  LoRa.setPins(PIN_LORA_NSS, PIN_LORA_RST, PIN_LORA_DIO0);
  if (!LoRa.begin(LORA_FREQ)) return false;
  LoRa.setSpreadingFactor(LORA_SF);
  LoRa.setSignalBandwidth(LORA_BW);
  LoRa.setCodingRate4(LORA_CR);
  LoRa.setSyncWord(LORA_SYNC);
  LoRa.enableCrc();
  LoRa.setTxPower(LORA_TX_DBM);
  LoRa.sleep();
  return true;
}

// Builds header + body + 4-byte seal (zeros for now), sends it once or twice (same counter).
void gaSend(uint8_t type, const void *body, uint8_t bodyLen, bool twice) {
  uint8_t buf[sizeof(Header) + 24 + SEAL_LEN];
  Header h;
  h.verType = (PKT_VERSION << 4) | type;
  h.radio = gRadio;
  h.boot = gBoot;
  h.counter = gaNextCounter();
  memcpy(buf, &h, sizeof h);
  memcpy(buf + sizeof h, body, bodyLen);
  memset(buf + sizeof h + bodyLen, 0, SEAL_LEN);
  uint8_t n = sizeof h + bodyLen + SEAL_LEN;

  for (uint8_t copy = 0; copy < (twice ? 2 : 1); copy++) {
    if (copy) delay(1500 + random(0, 1500));  // second copy a little later (decision 2.10)
    LoRa.beginPacket();
    LoRa.write(buf, n);
    LoRa.endPacket();                         // blocks until sent
  }
  LoRa.sleep();

  Serial.print(F("[tx] type=")); Serial.print(type);
  Serial.print(F(" boot=")); Serial.print(gBoot);
  Serial.print(F(" counter=")); Serial.print(h.counter);
  Serial.print(twice ? F(" (x2) ") : F(" "));
  for (uint8_t i = 0; i < n; i++) { if (buf[i] < 16) Serial.print('0'); Serial.print(buf[i], HEX); }
  Serial.println();
}

void gaSendBoot(uint8_t fwVersion, uint8_t nodeType) {
  BootBody b = { fwVersion, gResetReason, nodeType };
  gaSend(T_BOOT, &b, sizeof b, true);
}
