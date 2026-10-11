#include <Arduino.h>

void setup() {
  Serial.begin(115200);
  delay(2000);

  const uint32_t flash_mb = ESP.getFlashChipSize() / (1024U * 1024U);
  const uint32_t psram_mb = ESP.getPsramSize() / (1024U * 1024U);

  Serial.println();
  Serial.println("=== FridgeEInkDisplay board check ===");
  Serial.printf("Chip model : %s\n", ESP.getChipModel());
  Serial.printf("Chip cores : %u\n", ESP.getChipCores());
  Serial.printf("CPU freq   : %u MHz\n", ESP.getCpuFreqMHz());
  Serial.printf("Flash      : %u MB\n", flash_mb);
  Serial.printf("PSRAM      : %u MB\n", psram_mb);
  Serial.printf("Free heap  : %u bytes\n", ESP.getFreeHeap());

  const bool passed =
      String(ESP.getChipModel()).startsWith("ESP32-S3") &&
      flash_mb == 16 &&
      psram_mb == 8;

  Serial.printf("RESULT     : %s\n", passed ? "PASS" : "FAIL");
}

void loop() {
  delay(1000);
}
