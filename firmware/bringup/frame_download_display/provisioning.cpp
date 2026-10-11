#include "provisioning.h"

#include <BLE2902.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <HTTPClient.h>
#include <NetworkClientSecure.h>
#include <Preferences.h>
#include <SHA2Builder.h>
#include <WiFi.h>
#include <esp_system.h>
#include <mbedtls/base64.h>
#include <mbedtls/gcm.h>
#include <mbedtls/md.h>
#include <time.h>

#include "device_secrets.h"
#include "tls_roots.h"

namespace {

constexpr char kServiceUuid[] = "7b9e0001-5f34-4f6f-9f46-7d4c8a1e0001";
constexpr char kDeviceCodeUuid[] = "7b9e0002-5f34-4f6f-9f46-7d4c8a1e0001";
constexpr char kChallengeUuid[] = "7b9e0003-5f34-4f6f-9f46-7d4c8a1e0001";
constexpr char kCommandUuid[] = "7b9e0004-5f34-4f6f-9f46-7d4c8a1e0001";
constexpr char kStatusUuid[] = "7b9e0005-5f34-4f6f-9f46-7d4c8a1e0001";
constexpr char kPreferencesNamespace[] = "rfm-config";
constexpr char kKeyContext[] = "rfm-provisioning-key-v1";
constexpr size_t kMaximumEnvelopeLength = 2048;
constexpr uint32_t kWifiTimeoutMs = 30000;
constexpr uint32_t kProvisioningTimeoutMs = 10UL * 60UL * 1000UL;

struct ReceiverState {
  String encryptedPayload;
  String expectedSha256;
  size_t expectedChunks = 0;
  size_t nextChunk = 0;
  bool ready = false;
};

ReceiverState receiver;
String challengeHex;
BLECharacteristic* statusCharacteristic = nullptr;

void setStatus(const char* value) {
  if (statusCharacteristic == nullptr) {
    return;
  }
  statusCharacteristic->setValue(value);
  statusCharacteristic->notify();
}

void resetReceiver(size_t expectedChunks) {
  receiver.encryptedPayload = "";
  receiver.encryptedPayload.reserve(kMaximumEnvelopeLength);
  receiver.expectedSha256 = "";
  receiver.expectedSha256.reserve(64);
  receiver.expectedChunks = expectedChunks;
  receiver.nextChunk = 0;
  receiver.ready = false;
}

bool parseUnsigned(const String& raw, size_t& value) {
  if (raw.isEmpty()) {
    return false;
  }
  size_t parsed = 0;
  for (size_t index = 0; index < raw.length(); ++index) {
    if (!isDigit(raw[index])) {
      return false;
    }
    parsed = parsed * 10 + static_cast<size_t>(raw[index] - '0');
    if (parsed > 512) {
      return false;
    }
  }
  value = parsed;
  return true;
}

class CommandCallbacks : public BLECharacteristicCallbacks {
 public:
  void onWrite(BLECharacteristic* characteristic) override {
    const String command = characteristic->getValue();
    if (command.startsWith("B|")) {
      size_t count = 0;
      if (!parseUnsigned(command.substring(2), count) || count == 0) {
        setStatus("ERROR:BEGIN");
        return;
      }
      resetReceiver(count);
      setStatus("RECEIVING");
      return;
    }
    if (command.startsWith("D|")) {
      const int separator = command.indexOf('|', 2);
      if (separator < 0 || receiver.expectedChunks == 0) {
        setStatus("ERROR:CHUNK");
        return;
      }
      size_t index = 0;
      if (!parseUnsigned(command.substring(2, separator), index) ||
          index != receiver.nextChunk ||
          receiver.encryptedPayload.length() +
                  command.length() - separator - 1 >
              kMaximumEnvelopeLength) {
        setStatus("ERROR:ORDER");
        return;
      }
      receiver.encryptedPayload += command.substring(separator + 1);
      ++receiver.nextChunk;
      return;
    }
    if (command.startsWith("H|")) {
      const int separator = command.indexOf('|', 2);
      size_t index = 0;
      if (separator < 0 ||
          !parseUnsigned(command.substring(2, separator), index) ||
          index > 3 || command.length() - separator - 1 != 16 ||
          index * 16 != receiver.expectedSha256.length()) {
        setStatus("ERROR:HASH");
        return;
      }
      receiver.expectedSha256 += command.substring(separator + 1);
      return;
    }
    if (command == "E") {
      if (receiver.nextChunk != receiver.expectedChunks ||
          receiver.expectedSha256.length() != 64) {
        setStatus("ERROR:INCOMPLETE");
        return;
      }
      SHA256Builder sha256;
      sha256.begin();
      sha256.add(
          reinterpret_cast<const uint8_t*>(
              receiver.encryptedPayload.c_str()),
          receiver.encryptedPayload.length());
      sha256.calculate();
      if (!sha256.toString().equalsIgnoreCase(receiver.expectedSha256)) {
        setStatus("ERROR:SHA256");
        return;
      }
      receiver.ready = true;
      setStatus("PROCESSING");
    }
  }
};

String createChallenge() {
  char output[33];
  for (size_t index = 0; index < 16; ++index) {
    snprintf(
        output + index * 2,
        3,
        "%02x",
        static_cast<unsigned int>(esp_random() & 0xff));
  }
  output[32] = '\0';
  return String(output);
}

bool decodeBase64Url(const String& encoded, uint8_t*& raw, size_t& rawLength) {
  String padded = encoded;
  padded.replace('-', '+');
  padded.replace('_', '/');
  while (padded.length() % 4 != 0) {
    padded += '=';
  }
  size_t capacity = padded.length() * 3 / 4 + 4;
  raw = static_cast<uint8_t*>(malloc(capacity));
  if (raw == nullptr) {
    return false;
  }
  const int result = mbedtls_base64_decode(
      raw,
      capacity,
      &rawLength,
      reinterpret_cast<const unsigned char*>(padded.c_str()),
      padded.length());
  if (result != 0) {
    free(raw);
    raw = nullptr;
    return false;
  }
  return true;
}

bool deriveProvisioningKey(uint8_t key[32]) {
  const mbedtls_md_info_t* info =
      mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
  if (info == nullptr) {
    return false;
  }
  return mbedtls_md_hmac(
             info,
             reinterpret_cast<const unsigned char*>(kDeviceSecret),
             strlen(kDeviceSecret),
             reinterpret_cast<const unsigned char*>(kKeyContext),
             strlen(kKeyContext),
             key) == 0;
}

uint16_t readUint16(const uint8_t* raw) {
  return (static_cast<uint16_t>(raw[0]) << 8) | raw[1];
}

uint32_t readUint32(const uint8_t* raw) {
  return (static_cast<uint32_t>(raw[0]) << 24) |
         (static_cast<uint32_t>(raw[1]) << 16) |
         (static_cast<uint32_t>(raw[2]) << 8) | raw[3];
}

bool readField(
    const uint8_t* raw,
    size_t rawLength,
    size_t& offset,
    String& value) {
  if (offset + 2 > rawLength) {
    return false;
  }
  const uint16_t length = readUint16(raw + offset);
  offset += 2;
  if (offset + length > rawLength) {
    return false;
  }
  value = "";
  value.reserve(length);
  for (size_t index = 0; index < length; ++index) {
    value += static_cast<char>(raw[offset + index]);
  }
  offset += length;
  return true;
}

struct DecryptedPayload {
  uint32_t expiresAt = 0;
  String sessionId;
  String bindingToken;
  DeviceRuntimeConfig config;
};

bool decryptPayload(DecryptedPayload& output) {
  uint8_t* envelope = nullptr;
  size_t envelopeLength = 0;
  if (!decodeBase64Url(
          receiver.encryptedPayload,
          envelope,
          envelopeLength) ||
      envelopeLength < 1 + 12 + 16 || envelope[0] != 1) {
    return false;
  }
  const size_t cipherLength = envelopeLength - 1 - 12 - 16;
  uint8_t* plaintext = static_cast<uint8_t*>(malloc(cipherLength));
  if (plaintext == nullptr) {
    free(envelope);
    return false;
  }
  uint8_t key[32];
  if (!deriveProvisioningKey(key)) {
    free(plaintext);
    free(envelope);
    return false;
  }
  const String aad = String(kDeviceCode) + "\n" + challengeHex;
  mbedtls_gcm_context context;
  mbedtls_gcm_init(&context);
  int result = mbedtls_gcm_setkey(
      &context,
      MBEDTLS_CIPHER_ID_AES,
      key,
      sizeof(key) * 8);
  if (result == 0) {
    result = mbedtls_gcm_auth_decrypt(
        &context,
        cipherLength,
        envelope + 1,
        12,
        reinterpret_cast<const unsigned char*>(aad.c_str()),
        aad.length(),
        envelope + envelopeLength - 16,
        16,
        envelope + 13,
        plaintext);
  }
  mbedtls_gcm_free(&context);
  memset(key, 0, sizeof(key));
  free(envelope);
  if (result != 0 || cipherLength < 8 ||
      memcmp(plaintext, "RFM1", 4) != 0) {
    free(plaintext);
    return false;
  }
  output.expiresAt = readUint32(plaintext + 4);
  size_t offset = 8;
  const bool parsed =
      readField(plaintext, cipherLength, offset, output.sessionId) &&
      readField(plaintext, cipherLength, offset, output.bindingToken) &&
      readField(plaintext, cipherLength, offset, output.config.apiBaseUrl) &&
      readField(plaintext, cipherLength, offset, output.config.wifiSsid) &&
      readField(plaintext, cipherLength, offset, output.config.wifiPassword) &&
      offset == cipherLength;
  memset(plaintext, 0, cipherLength);
  free(plaintext);
  return parsed && !output.sessionId.isEmpty() &&
         !output.bindingToken.isEmpty() &&
         !output.config.apiBaseUrl.isEmpty() &&
         !output.config.wifiSsid.isEmpty();
}

bool connectProvisionedWifi(const DeviceRuntimeConfig& config) {
  WiFi.persistent(false);
  WiFi.mode(WIFI_AP_STA);
  WiFi.begin(config.wifiSsid.c_str(), config.wifiPassword.c_str());
  const uint32_t startedAt = millis();
  while (WiFi.status() != WL_CONNECTED) {
    if (millis() - startedAt >= kWifiTimeoutMs) {
      return false;
    }
    delay(250);
  }
  return true;
}

bool synchronizeProvisioningClock() {
  if (time(nullptr) >= 1700000000) {
    return true;
  }
  configTime(
      0,
      0,
      "ntp.aliyun.com",
      "ntp.tencent.com",
      "pool.ntp.org");
  const uint32_t startedAt = millis();
  while (time(nullptr) < 1700000000) {
    if (millis() - startedAt >= 30000) {
      return false;
    }
    delay(250);
  }
  return true;
}

bool completeBinding(const DecryptedPayload& payload) {
  const String url =
      payload.config.apiBaseUrl + "/v1/devices/" + kDeviceCode +
      "/provisioning/complete";
  WiFiClient plainClient;
  NetworkClientSecure secureClient;
  NetworkClient* client = &plainClient;
  if (url.startsWith("https://")) {
    secureClient.setCACert(kIsrgRootX1);
    client = &secureClient;
  }
  HTTPClient http;
  http.setConnectTimeout(10000);
  http.setTimeout(10000);
  if (!http.begin(*client, url)) {
    return false;
  }
  http.addHeader("Content-Type", "application/json");
  const String body =
      String("{\"session_id\":\"") + payload.sessionId +
      "\",\"binding_token\":\"" + payload.bindingToken + "\"}";
  const int statusCode = http.POST(body);
  http.end();
  return statusCode >= 200 && statusCode < 300;
}

}  // namespace

bool loadDeviceRuntimeConfig(DeviceRuntimeConfig& config) {
  Preferences preferences;
  if (!preferences.begin(kPreferencesNamespace, true)) {
    return false;
  }
  config.wifiSsid = preferences.getString("ssid", "");
  config.wifiPassword = preferences.getString("password", "");
  config.apiBaseUrl = preferences.getString("api", "");
  preferences.end();
  return !config.wifiSsid.isEmpty() && !config.apiBaseUrl.isEmpty();
}

bool saveDeviceRuntimeConfig(const DeviceRuntimeConfig& config) {
  Preferences preferences;
  if (!preferences.begin(kPreferencesNamespace, false)) {
    return false;
  }
  const bool savedSsid =
      preferences.putString("ssid", config.wifiSsid) > 0;
  preferences.putString("password", config.wifiPassword);
  const bool savedApi =
      preferences.putString("api", config.apiBaseUrl) > 0;
  preferences.end();
  return savedSsid && savedApi;
}

void clearDeviceRuntimeConfig() {
  Preferences preferences;
  if (preferences.begin(kPreferencesNamespace, false)) {
    preferences.clear();
    preferences.end();
  }
}

bool runBleProvisioning(DeviceRuntimeConfig& config) {
  resetReceiver(0);
  challengeHex = createChallenge();
  const String advertisedName =
      String("RFM-") + String(kDeviceCode).substring(
          max(0, static_cast<int>(strlen(kDeviceCode)) - 6));
  if (!BLEDevice::init(advertisedName.c_str())) {
    Serial.println("ERROR: BLE initialization failed.");
    return false;
  }
  BLEServer* server = BLEDevice::createServer();
  server->advertiseOnDisconnect(true);
  BLEService* service = server->createService(kServiceUuid);
  BLECharacteristic* code = service->createCharacteristic(
      kDeviceCodeUuid,
      BLECharacteristic::PROPERTY_READ);
  BLECharacteristic* challenge = service->createCharacteristic(
      kChallengeUuid,
      BLECharacteristic::PROPERTY_READ);
  BLECharacteristic* command = service->createCharacteristic(
      kCommandUuid,
      BLECharacteristic::PROPERTY_WRITE);
  statusCharacteristic = service->createCharacteristic(
      kStatusUuid,
      BLECharacteristic::PROPERTY_READ |
          BLECharacteristic::PROPERTY_NOTIFY);
  statusCharacteristic->addDescriptor(new BLE2902());
  code->setValue(kDeviceCode);
  challenge->setValue(challengeHex.c_str());
  statusCharacteristic->setValue("READY");
  command->setCallbacks(new CommandCallbacks());
  service->start();
  BLEAdvertising* advertising = BLEDevice::getAdvertising();
  advertising->addServiceUUID(kServiceUuid);
  advertising->setScanResponse(true);
  advertising->setMinPreferred(0x06);
  advertising->setMaxPreferred(0x12);
  BLEDevice::startAdvertising();
  Serial.printf("BLE provisioning ready: %s\n", advertisedName.c_str());

  const uint32_t startedAt = millis();
  bool succeeded = false;
  while (millis() - startedAt < kProvisioningTimeoutMs) {
    if (!receiver.ready) {
      delay(50);
      continue;
    }
    receiver.ready = false;
    DecryptedPayload payload;
    if (!decryptPayload(payload)) {
      setStatus("ERROR:DECRYPT");
      continue;
    }
    setStatus("CONNECTING_WIFI");
    if (!connectProvisionedWifi(payload.config)) {
      setStatus("ERROR:WIFI");
      continue;
    }
    if (!synchronizeProvisioningClock() ||
        static_cast<uint32_t>(time(nullptr)) > payload.expiresAt) {
      setStatus("ERROR:TIME");
      continue;
    }
    setStatus("BINDING");
    if (!completeBinding(payload)) {
      setStatus("ERROR:BACKEND");
      continue;
    }
    if (!saveDeviceRuntimeConfig(payload.config)) {
      setStatus("ERROR:STORAGE");
      continue;
    }
    config = payload.config;
    setStatus("COMPLETED");
    delay(500);
    succeeded = true;
    break;
  }
  BLEDevice::stopAdvertising();
  // Keep the controller memory allocated so setup() can start a new BLE
  // provisioning attempt after a timeout. Passing true here releases the
  // memory permanently until the next hardware reset.
  BLEDevice::deinit(false);
  statusCharacteristic = nullptr;
  return succeeded;
}
