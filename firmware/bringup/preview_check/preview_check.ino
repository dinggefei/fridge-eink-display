#include <Arduino.h>
#include <SPI.h>

#include "preview_frame.h"

namespace {

constexpr int kBusyPin = 9;
constexpr int kResetPin = 7;
constexpr int kDcPin = 8;
constexpr int kCsPin = 10;
constexpr int kSckPin = 12;
constexpr int kMosiPin = 11;

constexpr uint16_t kWidth = 800;
constexpr uint16_t kHeight = 480;
constexpr uint32_t kExpectedFrameBytes =
    static_cast<uint32_t>(kWidth) * kHeight / 4;
constexpr uint32_t kBusyTimeoutMs = 60000;

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

  writeCommand(0x04);
  return waitUntilIdle("power on");
}

void sendPreviewFrame() {
  writeCommand(0x10);
  digitalWrite(kCsPin, LOW);
  digitalWrite(kDcPin, HIGH);
  for (size_t index = 0; index < kPreviewFrameSize; ++index) {
    SPI.transfer(pgm_read_byte(&kPreviewFrame[index]));
  }
  digitalWrite(kCsPin, HIGH);
}

bool refreshPanel() {
  writeCommand(0x12);
  writeData(0x00);
  return waitUntilIdle("full refresh");
}

bool sleepPanel() {
  writeCommand(0x02);
  writeData(0x00);
  if (!waitUntilIdle("power off")) {
    return false;
  }
  writeCommand(0x07);
  writeData(0xA5);
  return true;
}

void finishWithFailure() {
  SPI.endTransaction();
  Serial.println("RESULT: FAIL");
}

}  // namespace

void setup() {
  Serial.begin(115200);
  delay(2000);

  Serial.println();
  Serial.println("=== Refrigerator preview check ===");

  if (kPreviewFrameSize != kExpectedFrameBytes) {
    Serial.printf("ERROR: frame is %u bytes, expected %lu\n",
                  static_cast<unsigned int>(kPreviewFrameSize),
                  static_cast<unsigned long>(kExpectedFrameBytes));
    Serial.println("RESULT: FAIL");
    return;
  }

  pinMode(kBusyPin, INPUT);
  pinMode(kResetPin, OUTPUT);
  pinMode(kDcPin, OUTPUT);
  pinMode(kCsPin, OUTPUT);
  digitalWrite(kResetPin, HIGH);
  digitalWrite(kDcPin, HIGH);
  digitalWrite(kCsPin, HIGH);

  SPI.begin(kSckPin, -1, kMosiPin, kCsPin);
  SPI.beginTransaction(panelSpi);

  Serial.println("1/4 Initializing GDEM075F53...");
  if (!initializePanel()) {
    finishWithFailure();
    return;
  }

  Serial.printf("2/4 Sending preview frame: %u bytes...\n",
                static_cast<unsigned int>(kPreviewFrameSize));
  sendPreviewFrame();

  Serial.println("3/4 Refreshing; do not disconnect power...");
  if (!refreshPanel()) {
    finishWithFailure();
    return;
  }

  Serial.println("4/4 Entering panel sleep...");
  if (!sleepPanel()) {
    finishWithFailure();
    return;
  }

  SPI.endTransaction();
  Serial.println("RESULT: PASS");
}

void loop() {
  delay(1000);
}
