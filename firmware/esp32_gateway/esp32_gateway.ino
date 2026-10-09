/*
 * Ghost_Alert ESP32 gateway (design v1)
 * Receives LoRa packets and forwards them to the backend:
 *   POST BACKEND_URL {gateway_id, received_at, clock_ok, rssi, snr, payload_hex}
 * Jobs: radio CRC check, ignore non-Ghost_Alert packets, drop copies,
 *       stamp receive time (NTP), queue packets while Wi-Fi/backend is down.
 */
#include <SPI.h>
#include <LoRa.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <time.h>
#include <sys/time.h>
#include "secrets.h"

// ---- Radio settings: MUST be identical on every node ----
const long    LORA_FREQ = 433920000;  // 433.92 MHz, inside Sri Lanka's 433.05-434.79 MHz band
const int     LORA_SF   = 9;
const long    LORA_BW   = 125000;
const int     LORA_CR   = 5;          // coding rate 4/5
const uint8_t LORA_SYNC = 0x12;       // private network (LoRaWAN uses 0x34)

// ---- Ra-02 wiring ----
const int PIN_SCK = 18, PIN_MISO = 19, PIN_MOSI = 23, PIN_NSS = 5, PIN_RST = 14, PIN_DIO0 = 26;

const int MAX_PKT = 64, QUEUE_SIZE = 40, DEDUP_SIZE = 16;

struct Entry {
  uint8_t  data[MAX_PKT];
  uint8_t  len;
  int16_t  rssi;
  float    snr;
  uint32_t rxMillis;
  int64_t  rxEpochMs;   // 0 = clock was not synced when the packet arrived
};
Entry queueBuf[QUEUE_SIZE];
int qHead = 0, qCount = 0;
uint32_t nextSendAt = 0, backoffMs = 1000, lastWifiTry = 0;

struct Seen { uint16_t radio, boot, counter; };
Seen seen[DEDUP_SIZE];
int seenNext = 0;

// ---------------- time ----------------
bool clockOk() { return time(nullptr) > 1700000000; }   // after Nov 2023 = synced

int64_t nowEpochMs() {
  struct timeval tv; gettimeofday(&tv, nullptr);
  return (int64_t)tv.tv_sec * 1000 + tv.tv_usec / 1000;
}

void formatIso(int64_t ms, char *out, size_t n) {
  time_t s = ms / 1000; struct tm t; gmtime_r(&s, &t);
  snprintf(out, n, "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ", t.tm_year + 1900, t.tm_mon + 1,
           t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec, (int)(ms % 1000));
}

// ---------------- queue ----------------
void enqueue(const uint8_t *data, int len, int rssi, float snr) {
  if (qCount == QUEUE_SIZE) {                  // full: drop the oldest
    qHead = (qHead + 1) % QUEUE_SIZE; qCount--;
    Serial.println("[queue] full - oldest packet dropped");
  }
  Entry &e = queueBuf[(qHead + qCount) % QUEUE_SIZE];
  memcpy(e.data, data, len); e.len = len; e.rssi = rssi; e.snr = snr;
  e.rxMillis = millis(); e.rxEpochMs = clockOk() ? nowEpochMs() : 0;
  qCount++;
}

void dequeue() { qHead = (qHead + 1) % QUEUE_SIZE; qCount--; }

// ---------------- copies ----------------
bool alreadySeen(uint16_t r, uint16_t b, uint16_t c) {
  for (int i = 0; i < DEDUP_SIZE; i++)
    if (seen[i].radio == r && seen[i].boot == b && seen[i].counter == c) return true;
  seen[seenNext] = {r, b, c};
  seenNext = (seenNext + 1) % DEDUP_SIZE;
  return false;
}

// ---------------- LoRa ----------------
void receiveLoRa() {
  int size = LoRa.parsePacket();               // 0 = nothing (or CRC failed: radio dropped it)
  if (size == 0) return;
  uint8_t buf[MAX_PKT]; int n = 0;
  while (LoRa.available()) { int b = LoRa.read(); if (n < MAX_PKT) buf[n++] = b; }
  int rssi = LoRa.packetRssi(); float snr = LoRa.packetSnr();

  if (size > MAX_PKT || n < 11 || (buf[0] >> 4) != 1) {
    Serial.printf("[lora] ignored %d-byte packet (not Ghost_Alert)\n", size);
    return;
  }
  uint16_t radio = buf[1] | (buf[2] << 8);
  uint16_t boot  = buf[3] | (buf[4] << 8);
  uint16_t ctr   = buf[5] | (buf[6] << 8);
  if (alreadySeen(radio, boot, ctr)) {
    Serial.printf("[lora] copy dropped radio=%u counter=%u\n", radio, ctr);
    return;
  }
  Serial.printf("[lora] radio=%u type=%u boot=%u counter=%u len=%d rssi=%d snr=%.1f\n",
                radio, buf[0] & 0x0F, boot, ctr, n, rssi, snr);
  enqueue(buf, n, rssi, snr);
}

// ---------------- HTTP ----------------
int postOne(Entry &e) {
  char hex[2 * MAX_PKT + 1];
  for (int i = 0; i < e.len; i++) sprintf(hex + 2 * i, "%02x", e.data[i]);
  hex[2 * e.len] = 0;

  if (e.rxEpochMs == 0 && clockOk())           // clock got synced after the packet arrived
    e.rxEpochMs = nowEpochMs() - (int64_t)(millis() - e.rxMillis);

  char timePart[64] = "";
  bool clockGood = true;
  if (e.rxEpochMs > 0) {
    char iso[32]; formatIso(e.rxEpochMs, iso, sizeof iso);
    snprintf(timePart, sizeof timePart, "\"received_at\":\"%s\",", iso);
  } else if (millis() - e.rxMillis > 5000) {
    clockGood = false;                         // old packet and no real time: backend keeps it out of PCHA
  }                                            // else fresh packet: backend uses its own time

  char body[400];
  snprintf(body, sizeof body,
           "{\"gateway_id\":\"%s\",%s\"clock_ok\":%s,\"rssi\":%d,\"snr\":%.1f,\"payload_hex\":\"%s\"}",
           GATEWAY_ID, timePart, clockGood ? "true" : "false", e.rssi, e.snr, hex);

  HTTPClient http;
  http.begin(BACKEND_URL);
  http.setTimeout(5000);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Gateway-Key", GATEWAY_KEY);
  int code = http.POST((uint8_t *)body, strlen(body));
  String reply = code > 0 ? http.getString() : http.errorToString(code);
  http.end();
  Serial.printf("[http] %d %s\n", code, reply.c_str());
  return code;
}

void sendQueued() {
  if (qCount == 0 || (int32_t)(millis() - nextSendAt) < 0) return;
  if (WiFi.status() != WL_CONNECTED) return;
  int code = postOne(queueBuf[qHead]);
  if (code >= 200 && code < 300) {
    dequeue(); backoffMs = 1000;
  } else if (code == 400 || code == 401 || code == 422) {
    Serial.println("[http] rejected by backend - packet dropped (check key / format)");
    dequeue();
  } else {
    Serial.printf("[http] will retry in %lu ms (%d queued)\n", (unsigned long)backoffMs, qCount);
    nextSendAt = millis() + backoffMs;
    backoffMs = backoffMs * 2 > 60000 ? 60000 : backoffMs * 2;
  }
}

// ---------------- Wi-Fi ----------------
void keepWifi() {
  if (WiFi.status() == WL_CONNECTED || millis() - lastWifiTry < 10000) return;
  lastWifiTry = millis();
  Serial.println("[wifi] reconnecting...");
  WiFi.disconnect();
  WiFi.begin(WIFI_SSID, WIFI_PASS);
}

void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println("\nGhost_Alert ESP32 gateway");

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  lastWifiTry = millis();
  for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) delay(250);
  Serial.printf("[wifi] %s  IP=%s\n", WiFi.status() == WL_CONNECTED ? "connected" : "NOT connected yet",
                WiFi.localIP().toString().c_str());

  configTime(0, 0, "pool.ntp.org", "time.google.com");   // UTC
  for (int i = 0; i < 20 && !clockOk(); i++) delay(250);
  char iso[32]; formatIso(nowEpochMs(), iso, sizeof iso);
  Serial.printf("[time] %s  %s\n", clockOk() ? "synced" : "NOT synced yet", iso);

  SPI.begin(PIN_SCK, PIN_MISO, PIN_MOSI, PIN_NSS);
  LoRa.setPins(PIN_NSS, PIN_RST, PIN_DIO0);
  if (!LoRa.begin(LORA_FREQ)) {
    Serial.println("[lora] START FAILED - check wiring and 3.3V");
    while (true) delay(1000);
  }
  LoRa.setSpreadingFactor(LORA_SF);
  LoRa.setSignalBandwidth(LORA_BW);
  LoRa.setCodingRate4(LORA_CR);
  LoRa.setSyncWord(LORA_SYNC);
  LoRa.enableCrc();
  Serial.printf("[lora] listening on %.2f MHz SF%d BW%ldk\n", LORA_FREQ / 1e6, LORA_SF, LORA_BW / 1000);

  // Self-test: a fake boot packet from radio 65000. The backend should answer "unknown_node".
  uint8_t t[14] = {0x11, 0xE8, 0xFD, 1, 0, 1, 0, 1, 1, 1, 0, 0, 0, 0};
  enqueue(t, sizeof t, 0, 0);
}

void loop() {
  receiveLoRa();
  keepWifi();
  sendQueued();
}