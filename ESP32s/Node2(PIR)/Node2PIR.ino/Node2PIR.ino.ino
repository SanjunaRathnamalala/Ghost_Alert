#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

// --- Configuration ---
const char* ssid = "Sanjuna";
const char* password = "ssssssss";
const char* serverUrl = "http://172.20.10.3:8000/api/v1/telemetry";

const String hardwareId = "TEST_NODE_456";

// --- Hardware Pins & Timing ---
const int pirPin = 13; 
int pirState = LOW;

unsigned long lastTransmitTime = 0;          // Stores the last time we sent a packet
const unsigned long transmitInterval = 2000; // 2000 milliseconds (2 seconds)

void setup() {
  Serial.begin(115200);
  pinMode(pirPin, INPUT);

  // Connect to Wi-Fi
  Serial.print("Connecting to WiFi");
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi Connected!");
  
  Serial.println("Calibrating PIR sensor...");
  delay(15000); 
  Serial.println("Calibration complete. Node active.");
}

void loop() {
  pirState = digitalRead(pirPin);

  // If motion is currently happening (Pin is HIGH)
  if (pirState == HIGH) {
    
    // Check if 2 seconds have passed since the last transmission
    if (millis() - lastTransmitTime >= transmitInterval) {
      Serial.println("Motion active! Transmitting alert...");
      
      if (WiFi.status() == WL_CONNECTED) {
        HTTPClient http;
        http.begin(serverUrl);
        http.addHeader("Content-Type", "application/json");

        StaticJsonDocument<256> doc;
        doc["hardware_id"] = hardwareId;
        doc["moisture_pct"] = 0.0;
        doc["accel_x"] = 0.0;
        doc["accel_y"] = 0.0;
        doc["accel_z"] = 0.0;
        doc["tilt_variance"] = 0.0;
        doc["battery_volts"] = 9.0;
        doc["rssi"] = WiFi.RSSI();
        doc["pir_trigger"] = 1; // Explicitly flag the PIR event

        String requestBody;
        serializeJson(doc, requestBody);

        int httpResponseCode = http.POST(requestBody);
        Serial.print("HTTP Code: ");
        Serial.println(httpResponseCode);

        http.end();
      }
      
      // Reset the timer mark to the current time
      lastTransmitTime = millis(); 
    }
  } 
  else {
    // Optional: If the PIR is LOW, we can reset the timer slightly so that 
    // the very next time it goes HIGH, it transmits instantly without waiting.
    lastTransmitTime = 0; 
  }

  // Small delay to prevent the loop from thrashing the CPU
  delay(50); 
}