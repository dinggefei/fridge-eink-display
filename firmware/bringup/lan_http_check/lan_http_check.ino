#include <Arduino.h>
#include <HTTPClient.h>
#include <WiFi.h>

#include "../wifi_connect/secrets.h"
#include "server_config.h"

namespace {

constexpr uint32_t kConnectTimeoutMs = 30000;
constexpr uint32_t kHttpTimeoutMs = 10000;

bool connectWifi() {
  WiFi.persistent(false);
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(kWifiSsid, kWifiPassword);

  Serial.print("Connecting to Wi-Fi");
  const uint32_t startedAt = millis();
  while (WiFi.status() != WL_CONNECTED) {
    if (millis() - startedAt >= kConnectTimeoutMs) {
      Serial.println();
      Serial.printf("ERROR: Wi-Fi connection timeout, status=%d\n",
                    static_cast<int>(WiFi.status()));
      return false;
    }
    Serial.print(".");
    delay(500);
  }
  Serial.println();
  return true;
}

bool checkBackend() {
  const String url = String(kBackendBaseUrl) + "/health";
  WiFiClient client;
  HTTPClient http;

  Serial.printf("GET %s\n", url.c_str());
  http.setConnectTimeout(kHttpTimeoutMs);
  http.setTimeout(kHttpTimeoutMs);

  if (!http.begin(client, url)) {
    Serial.println("ERROR: HTTP client initialization failed.");
    return false;
  }

  const int statusCode = http.GET();
  const String responseBody = statusCode > 0 ? http.getString() : "";
  http.end();

  Serial.printf("HTTP status : %d\n", statusCode);
  if (!responseBody.isEmpty()) {
    Serial.printf("Response    : %s\n", responseBody.c_str());
  }

  if (statusCode != HTTP_CODE_OK) {
    Serial.printf("ERROR: request failed: %s\n",
                  HTTPClient::errorToString(statusCode).c_str());
    return false;
  }

  if (responseBody.indexOf("\"status\":\"ok\"") < 0) {
    Serial.println("ERROR: unexpected response body.");
    return false;
  }

  return true;
}

}  // namespace

void setup() {
  Serial.begin(115200);
  delay(2000);

  Serial.println();
  Serial.println("=== RefrigeratorFoodManagement LAN HTTP check ===");

  if (!connectWifi()) {
    Serial.println("RESULT: FAIL");
    return;
  }

  Serial.printf("ESP32 IPv4 : %s\n", WiFi.localIP().toString().c_str());
  Serial.printf("Mac server : %s\n", kBackendBaseUrl);

  if (!checkBackend()) {
    Serial.println("RESULT: FAIL");
    return;
  }

  Serial.println("RESULT: PASS");
}

void loop() {
  delay(1000);
}
