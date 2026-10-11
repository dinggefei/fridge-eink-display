#include <Arduino.h>
#include <SPI.h>

// FridgeEInkDisplay GDEM075F53/JD79665CA bring-up.
// Initialization sequence checked against Good Display's official
// "A32-GDEM075F53" ESP32 sample dated 2026-07-09.
//
// Wiring:
//   DESPI-C02 BUSY -> GPIO9
//   DESPI-C02 RES  -> GPIO7
//   DESPI-C02 D/C  -> GPIO8
//   DESPI-C02 CS   -> GPIO10
//   DESPI-C02 SCK  -> GPIO12
//   DESPI-C02 SDI  -> GPIO11
//   DESPI-C02 GND  -> GND
//   DESPI-C02 3.3V -> 3V3

namespace {

constexpr int kBusyPin = 9;
constexpr int kResetPin = 7;
constexpr int kDcPin = 8;
constexpr int kCsPin = 10;
constexpr int kSckPin = 12;
constexpr int kMosiPin = 11;

constexpr uint16_t kWidth = 800;
constexpr uint16_t kHeight = 480;
constexpr uint32_t kFrameBytes =
    static_cast<uint32_t>(kWidth) * kHeight / 4;
constexpr uint32_t kBusyTimeoutMs = 60000;
constexpr uint32_t kBusyAssertTimeoutMs = 3000;
constexpr uint32_t kMinimumFullRefreshMs = 5000;

// Four pixels are packed into each byte, two bits per pixel.
constexpr uint8_t kBlackByte = 0x00;
constexpr uint8_t kWhiteByte = 0x55;
constexpr uint8_t kYellowByte = 0xAA;
constexpr uint8_t kRedByte = 0xFF;

SPISettings panelSpi(4000000, MSBFIRST, SPI_MODE0);

void writeCommand(uint8_t command) {
  digitalWrite(kCsPin, LOW);
  digitalWrite(kDcPin, LOW);
  SPI.transfer(command);
  digitalWrite(kCsPin, HIGH);
}

void writeData(uint8_t data) {
  digitalWrite(kCsPin, LOW);
  digitalWrite(kDcPin, HIGH);
  SPI.transfer(data);
  digitalWrite(kCsPin, HIGH);
}

bool waitUntilIdle(const char* phase) {
  const uint32_t startedAt = millis();
  while (digitalRead(kBusyPin) == LOW) {
    if (millis() - startedAt >= kBusyTimeoutMs) {
      Serial.printf("ERROR: BUSY timeout during %s\n", phase);
      return false;
    }
    delay(10);
  }
  return true;
}

bool waitForBusyCycle(const char* phase,
                      uint32_t commandStartedAt,
                      uint32_t minimumDurationMs = 0) {
  while (digitalRead(kBusyPin) == HIGH) {
    if (millis() - commandStartedAt >= kBusyAssertTimeoutMs) {
      Serial.printf("ERROR: BUSY never asserted during %s.\n", phase);
      return false;
    }
    delay(5);
  }

  Serial.printf(
      "    BUSY asserted after %lu ms; waiting for %s to finish...\n",
      static_cast<unsigned long>(millis() - commandStartedAt),
      phase);
  if (!waitUntilIdle(phase)) {
    return false;
  }

  const uint32_t durationMs = millis() - commandStartedAt;
  Serial.printf(
      "    %s completed in %lu ms.\n",
      phase,
      static_cast<unsigned long>(durationMs));
  if (durationMs < minimumDurationMs) {
    Serial.printf(
        "ERROR: %s completed implausibly fast; expected at least %lu ms.\n",
        phase,
        static_cast<unsigned long>(minimumDurationMs));
    return false;
  }
  return true;
}

void hardwareReset() {
  delay(100);
  digitalWrite(kResetPin, LOW);
  delay(10);
  digitalWrite(kResetPin, HIGH);
  delay(10);
}

bool initializePanel() {
  hardwareReset();
  if (!waitUntilIdle("reset")) {
    return false;
  }

  writeCommand(0x4D);
  writeData(0x78);

  writeCommand(0x00);
  writeData(0x2F);
  writeData(0x29);

  writeCommand(0xE3);
  writeData(0x88);

  writeCommand(0x50);
  writeData(0x37);

  writeCommand(0x61);
  writeData(kWidth >> 8);
  writeData(kWidth & 0xFF);
  writeData(kHeight >> 8);
  writeData(kHeight & 0xFF);

  writeCommand(0x65);
  writeData(0x00);
  writeData(0x00);
  writeData(0x00);
  writeData(0x00);

  writeCommand(0xE9);
  writeData(0x01);

  writeCommand(0xF0);
  writeData(0x5F);

  writeCommand(0x30);
  writeData(0x08);

  const uint32_t commandStartedAt = millis();
  writeCommand(0x04);
  return waitForBusyCycle("power on", commandStartedAt);
}

void sendFourColorPattern() {
  writeCommand(0x10);

  // Four 200-pixel vertical bands: black, white, yellow, red.
  // Each band occupies 50 packed bytes per row.
  // Keep the byte-level CS timing identical to Good Display's official
  // GDEM075F53 Arduino example. Some controller/panel revisions do not accept
  // a complete 96,000-byte frame under one uninterrupted CS assertion.
  for (uint16_t y = 0; y < kHeight; ++y) {
    for (uint16_t i = 0; i < 50; ++i) {
      writeData(kBlackByte);
    }
    for (uint16_t i = 0; i < 50; ++i) {
      writeData(kWhiteByte);
    }
    for (uint16_t i = 0; i < 50; ++i) {
      writeData(kYellowByte);
    }
    for (uint16_t i = 0; i < 50; ++i) {
      writeData(kRedByte);
    }
  }

  Serial.printf("Frame sent: %lu bytes\n",
                static_cast<unsigned long>(kFrameBytes));
}

bool refreshPanel() {
  const uint32_t commandStartedAt = millis();
  writeCommand(0x12);
  writeData(0x00);
  return waitForBusyCycle(
      "full refresh", commandStartedAt, kMinimumFullRefreshMs);
}

bool sleepPanel() {
  const uint32_t commandStartedAt = millis();
  writeCommand(0x02);
  writeData(0x00);
  if (!waitForBusyCycle("power off", commandStartedAt)) {
    return false;
  }

  writeCommand(0x07);
  writeData(0xA5);
  return true;
}

void stopWithError() {
  Serial.println("RESULT: FAIL");
  SPI.endTransaction();
}

}  // namespace

void setup() {
  Serial.begin(115200);
  delay(2000);

  Serial.println();
  Serial.println("=== GDEM075F53 display check ===");
  Serial.println("Keep USB power connected during the whole refresh.");
  Serial.println("DESPI-C02 P3 must be set to 2.2 while power is off.");

  pinMode(kBusyPin, INPUT);
  pinMode(kResetPin, OUTPUT);
  pinMode(kDcPin, OUTPUT);
  pinMode(kCsPin, OUTPUT);
  digitalWrite(kResetPin, HIGH);
  digitalWrite(kDcPin, HIGH);
  digitalWrite(kCsPin, HIGH);

  SPI.begin(kSckPin, -1, kMosiPin, kCsPin);
  SPI.beginTransaction(panelSpi);

  Serial.println("1/4 Initializing panel...");
  if (!initializePanel()) {
    stopWithError();
    return;
  }

  Serial.println("2/4 Sending 96,000-byte four-color frame...");
  sendFourColorPattern();

  Serial.println("3/4 Refreshing; flicker is normal, wait up to 60 seconds...");
  if (!refreshPanel()) {
    stopWithError();
    return;
  }

  Serial.println("4/4 Entering panel sleep...");
  if (!sleepPanel()) {
    stopWithError();
    return;
  }

  SPI.endTransaction();
  Serial.println("RESULT: PASS");
  Serial.println("Expected image: black | white | yellow | red vertical bands.");
}

void loop() {
  delay(1000);
}
