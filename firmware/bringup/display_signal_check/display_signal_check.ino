#include <Arduino.h>

// RefrigeratorFoodManagement DESPI-C02 signal-line diagnostic.
// Disconnect the e-paper FPC before running this sketch. The sketch drives
// each ESP32-to-DESPI control/data line LOW and HIGH slowly so that the voltage
// can be checked directly at the matching DESPI-C02 header pin.

namespace {

struct SignalLine {
  const char* name;
  int gpio;
};

constexpr SignalLine kSignalLines[] = {
    {"RES", 7},
    {"D/C", 8},
    {"CS", 10},
    {"SCK", 12},
    {"SDI", 11},
};

constexpr uint32_t kStateDurationMs = 4000;

void setAllLow() {
  for (const SignalLine& line : kSignalLines) {
    digitalWrite(line.gpio, LOW);
  }
}

void testLine(const SignalLine& line) {
  setAllLow();
  Serial.printf("MEASURE DESPI %-3s -> GND: LOW, expected 0-0.2 V\n",
                line.name);
  delay(kStateDurationMs);

  digitalWrite(line.gpio, HIGH);
  Serial.printf("MEASURE DESPI %-3s -> GND: HIGH, expected 3.1-3.3 V\n",
                line.name);
  delay(kStateDurationMs);

  digitalWrite(line.gpio, LOW);
}

}  // namespace

void setup() {
  Serial.begin(115200);
  delay(2000);

  Serial.println();
  Serial.println("=== DESPI-C02 signal-line check ===");
  Serial.println("The e-paper FPC must be disconnected for this test.");
  Serial.println("Keep the DESPI-C02 jumper wires and 3.3 V power connected.");

  for (const SignalLine& line : kSignalLines) {
    pinMode(line.gpio, OUTPUT);
  }
  setAllLow();
}

void loop() {
  Serial.println();
  Serial.println("Starting one RES/D-C/CS/SCK/SDI measurement cycle.");
  for (const SignalLine& line : kSignalLines) {
    testLine(line);
  }
  Serial.println("Cycle complete; repeating in 5 seconds.");
  setAllLow();
  delay(5000);
}
