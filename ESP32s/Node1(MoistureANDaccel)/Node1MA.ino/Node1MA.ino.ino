#include <WiFi.h>
#include <HTTPClient.h>
#include <SPI.h>
#include <ADXL362.h>
#include <ArduinoJson.h>

// --- Configuration ---
const char* ssid = "Sanjuna";
const char* password = "ssssssss";
// Replace X.X with the local IP address of the computer running your FastAPI server
const char* serverUrl = "http://172.20.10.3:8000/api/v1/telemetry"; 

const String hardwareId = "TEST_NODE_123";

// --- Hardware Pins ---
const int soilPin = 34; // ADC1 channel for Capacitive Sensor
ADXL362 xl;

void setup() {
  Serial.begin(115200);

  // Initialize ADXL362 (CS on GPIO 5)
  xl.begin(5); 
  xl.beginMeasure(); 

  // Connect to Wi-Fi
  Serial.print("Connecting to WiFi");
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi Connected!");
}

void loop() {
  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    http.begin(serverUrl);
    http.addHeader("Content-Type", "application/json");

    // 1. Read Soil Moisture (Basic inverted mapping for prototype)
    int rawSoil = analogRead(soilPin);
    float moisturePct = map(rawSoil, 4095, 0, 0, 100); 

    // 2. Read Accelerometer
    int16_t x, y, z, t;
    xl.readXYZTData(x, y, z, t);
    float accelX = x / 1000.0;
    float accelY = y / 1000.0;
    float accelZ = z / 1000.0;
    
    // Simplified tilt variance calculation for bench testing
    float tiltVariance = abs(accelX) + abs(accelY); 

    // 3. Construct JSON Payload
    StaticJsonDocument<256> doc;
    doc["hardware_id"] = hardwareId;
    doc["moisture_pct"] = moisturePct;
    doc["accel_x"] = accelX;
    doc["accel_y"] = accelY;
    doc["accel_z"] = accelZ;
    doc["tilt_variance"] = tiltVariance;
    doc["battery_volts"] = 9.0; // Hardcoded for your 9V battery test
    doc["rssi"] = WiFi.RSSI();

    String requestBody;
    serializeJson(doc, requestBody);

    // 4. Send POST Request
    int httpResponseCode = http.POST(requestBody);
    Serial.print("HTTP Code: ");
    Serial.println(httpResponseCode);
    Serial.println("Payload: " + requestBody);

    http.end();
  }

  // Delay before the next transmission loop
  delay(5000); 
}