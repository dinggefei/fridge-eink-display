#include <Arduino.h>
#include <WiFi.h>

namespace {

const char* encryptionName(wifi_auth_mode_t mode) {
  switch (mode) {
    case WIFI_AUTH_OPEN:
      return "OPEN";
    case WIFI_AUTH_WEP:
      return "WEP";
    case WIFI_AUTH_WPA_PSK:
      return "WPA";
    case WIFI_AUTH_WPA2_PSK:
      return "WPA2";
    case WIFI_AUTH_WPA_WPA2_PSK:
      return "WPA/WPA2";
    case WIFI_AUTH_WPA2_ENTERPRISE:
      return "WPA2-ENT";
    case WIFI_AUTH_WPA3_PSK:
      return "WPA3";
    case WIFI_AUTH_WPA2_WPA3_PSK:
      return "WPA2/WPA3";
    default:
      return "UNKNOWN";
  }
}

bool scanOnce() {
  Serial.println("Scanning 2.4 GHz Wi-Fi networks...");
  const int count = WiFi.scanNetworks(false, true);

  if (count < 0) {
    Serial.printf("Scan error: %d\n", count);
    return false;
  }
  if (count == 0) {
    Serial.println("No networks found.");
    return false;
  }

  Serial.printf("Found %d network(s):\n", count);
  Serial.println("# | RSSI | CH | SECURITY | SSID");
  for (int index = 0; index < count; ++index) {
    Serial.printf(
        "%d | %d dBm | %d | %s | %s\n",
        index + 1,
        WiFi.RSSI(index),
        WiFi.channel(index),
        encryptionName(WiFi.encryptionType(index)),
        WiFi.SSID(index).isEmpty() ? "<hidden>" : WiFi.SSID(index).c_str());
  }

  WiFi.scanDelete();
  return true;
}

}  // namespace

void setup() {
  Serial.begin(115200);
  delay(2000);

  Serial.println();
  Serial.println("=== RefrigeratorFoodManagement Wi-Fi scan ===");
  Serial.printf("Wi-Fi MAC: %s\n", WiFi.macAddress().c_str());

  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  delay(500);

  bool passed = scanOnce();
  if (!passed) {
    Serial.println("Retrying once in 2 seconds...");
    delay(2000);
    passed = scanOnce();
  }

  Serial.printf("RESULT: %s\n", passed ? "PASS" : "FAIL");
  WiFi.mode(WIFI_OFF);
}

void loop() {
  delay(1000);
}
