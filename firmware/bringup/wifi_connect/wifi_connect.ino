#include <Arduino.h>
#include <WiFi.h>

#include "secrets.h"

namespace {

constexpr uint32_t kConnectTimeoutMs = 30000;
constexpr char kSsidPlaceholder[] = "YOUR_2_4_GHZ_WIFI_NAME";
constexpr char kPasswordPlaceholder[] = "YOUR_WIFI_PASSWORD";

bool configurationReady() {
  return strcmp(kWifiSsid, kSsidPlaceholder) != 0 &&
         strcmp(kWifiPassword, kPasswordPlaceholder) != 0 &&
         strlen(kWifiSsid) > 0;
}

bool connectWifi() {
  WiFi.persistent(false);
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(kWifiSsid, kWifiPassword);

  Serial.print("Connecting");
  const uint32_t startedAt = millis();
  while (WiFi.status() != WL_CONNECTED) {
    if (millis() - startedAt >= kConnectTimeoutMs) {
      Serial.println();
      Serial.printf("ERROR: connection timeout, WiFi.status()=%d\n",
                    static_cast<int>(WiFi.status()));
      return false;
    }
    Serial.print(".");
    delay(500);
  }
  Serial.println();
  return true;
}

}  // namespace

void setup() {
  Serial.begin(115200);
  delay(2000);

  Serial.println();
  Serial.println("=== RefrigeratorFoodManagement Wi-Fi connect ===");

  if (!configurationReady()) {
    Serial.println("ERROR: edit secrets.h before uploading.");
    Serial.println("RESULT: FAIL");
    return;
  }

  if (!connectWifi()) {
    Serial.println("RESULT: FAIL");
    return;
  }

  Serial.println("Connected.");
  Serial.printf("IPv4    : %s\n", WiFi.localIP().toString().c_str());
  Serial.printf("Gateway : %s\n", WiFi.gatewayIP().toString().c_str());
  Serial.printf("DNS     : %s\n", WiFi.dnsIP().toString().c_str());
  Serial.printf("Channel : %d\n", WiFi.channel());
  Serial.printf("RSSI    : %d dBm\n", WiFi.RSSI());
  Serial.println("RESULT: PASS");
}

void loop() {
  static wl_status_t previousStatus = WL_CONNECTED;
  const wl_status_t currentStatus = WiFi.status();
  if (currentStatus != previousStatus) {
    Serial.printf("Wi-Fi status changed: %d -> %d\n",
                  static_cast<int>(previousStatus),
                  static_cast<int>(currentStatus));
    previousStatus = currentStatus;
  }
  delay(1000);
}
