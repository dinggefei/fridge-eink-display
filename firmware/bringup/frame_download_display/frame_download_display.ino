#include <Arduino.h>
#include <cstring>
#include <HTTPClient.h>
#include <NetworkClientSecure.h>
#include <Preferences.h>
#include <SHA2Builder.h>
#include <SPI.h>
#include <Update.h>
#include <WiFi.h>
#include <driver/gpio.h>
#include <esp_ota_ops.h>
#include <esp_sntp.h>
#include <esp_heap_caps.h>
#include <esp_sleep.h>
#include <esp_system.h>
#include <mbedtls/md.h>
#include <time.h>

#include "device_secrets.h"
#include "provisioning.h"
#include "tls_roots.h"

#if __has_include("factory_pairing_frame.h")
#include "factory_pairing_frame.h"
#define RFM_FACTORY_PAIRING_FRAME_CONFIGURED 1
#else
#define RFM_FACTORY_PAIRING_FRAME_CONFIGURED 0
#endif

#if __has_include("ota_public_key.h")
#include "ota_public_key.h"
#define RFM_OTA_PUBLIC_KEY_CONFIGURED 1
#else
#define RFM_OTA_PUBLIC_KEY_CONFIGURED 0
#endif

// Updated: 2026-09-23 23:36:06 Asia/Shanghai
// Allow an unconfigured device to refresh its factory pairing code by holding
// BOOT for two seconds after reset, without erasing or reflashing the device.

SET_LOOP_TASK_STACK_SIZE(16 * 1024);

// Defer Arduino core's automatic OTA acceptance until this application has
// verified PSRAM, runtime configuration, Wi-Fi, time, and the backend report.
bool verifyRollbackLater() {
  return true;
}

namespace {

constexpr int kBusyPin = 9;
constexpr int kResetPin = 7;
constexpr int kDcPin = 8;
constexpr int kCsPin = 10;
constexpr int kSckPin = 12;
constexpr int kMosiPin = 11;
constexpr int kRgbPin = 38;

constexpr uint16_t kWidth = 800;
constexpr uint16_t kHeight = 480;
constexpr size_t kExpectedFrameBytes =
    static_cast<size_t>(kWidth) * kHeight / 4;
constexpr uint32_t kConnectTimeoutMs = 30000;
constexpr uint32_t kFastConnectTimeoutMs = 2500;
constexpr uint32_t kTimeSyncTimeoutMs = 30000;
constexpr uint32_t kHttpTimeoutMs = 15000;
constexpr uint32_t kBusyTimeoutMs = 60000;
constexpr uint32_t kBusyAssertTimeoutMs = 3000;
constexpr uint32_t kBusySignalDelayMs = 100;
constexpr uint32_t kPowerOffBusyObserveMs = 500;
constexpr uint32_t kBootActionWindowMs = 8000;
constexpr uint32_t kBootHoldDurationMs = 2000;
constexpr uint32_t kPollIntervalSeconds = 5UL * 60UL;
constexpr uint32_t kClockResyncIntervalSeconds = 60UL * 60UL;
constexpr time_t kMinimumValidUnixTime = 1700000000;
constexpr uint32_t kOtaFailureBackoffSeconds = 6UL * 60UL * 60UL;
constexpr uint64_t kMicrosecondsPerSecond = 1000000ULL;
constexpr size_t kDownloadChunkBytes = 4096;
constexpr char kExpectedPanelModel[] = "GDEM075F53";
constexpr char kPreferencesNamespace[] = "rfm-frame";
constexpr char kOtaPreferencesNamespace[] = "rfm-ota";
constexpr char kPairingPreferencesNamespace[] = "rfm-pairing";
constexpr char kPairingFrameShownKey[] = "frame-v1";
constexpr char kFirmwareVersion[] = "1.1.2";
constexpr uint32_t kFirmwareBuildNumber = 11002;
constexpr char kFirmwareHardware[] = "esp32-s3-dev-kit-n16r8";
constexpr char kEmptySha256[] =
    "e3b0c44298fc1c149afbf4c8996fb924"
    "27ae41e4649b934ca495991b7852b855";
constexpr size_t kOtaSignatureTrailerBytes = 512;
constexpr size_t kMaximumSignedFirmwareBytes = 3UL * 1024UL * 1024UL;
// Version the cache key once so the first boot after this BUSY-handshake fix
// downloads and displays a complete frame.  Older firmware could save an ETag
// before the panel had actually finished refreshing.
constexpr char kEtagPreferenceKey[] = "etag-v2";

SPISettings panelSpi(4000000, MSBFIRST, SPI_MODE0);

enum class FrameFetchResult {
  kFailed,
  kAuthenticationRejected,
  kNotModified,
  kDownloaded,
  kFirmwareUpdateAvailable,
  kDeviceUnbound,
};

enum class UpdateCycleResult {
  kFailed,
  kSucceeded,
  kDeviceUnbound,
};

struct FirmwareOffer {
  String releaseId;
  String version;
  String hardware;
  String path;
  String sha256;
  uint32_t buildNumber = 0;
  size_t signedSize = 0;

  bool available() const {
    return !releaseId.isEmpty();
  }
};

// This counter survives timer-based deep sleep, but is reset on a normal
// power-on or RST boot.  It preserves the 5/15/60/300-second retry sequence
// without keeping the CPU awake between attempts.
RTC_DATA_ATTR uint32_t consecutiveFailures = 0;
RTC_DATA_ATTR time_t lastClockSyncEpoch = 0;
RTC_DATA_ATTR uint8_t cachedWifiChannel = 0;
RTC_DATA_ATTR uint8_t cachedWifiBssid[6] = {0};
DeviceRuntimeConfig runtimeConfig;
volatile bool clockSynchronizedByNtp = false;
bool ntpSynchronizedThisWake = false;

void onClockSynchronized(struct timeval*) {
  clockSynchronizedByNtp = true;
}

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

bool waitForBusyCycle(const char* phase, uint32_t commandStartedAt) {
  // GDEM075F53 does not necessarily pull BUSY low in the same instant that the
  // command is sent.  Reading BUSY too early therefore looks like an immediate
  // success even though the refresh has not started yet.
  delay(kBusySignalDelayMs);
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
  Serial.printf(
      "    %s completed in %lu ms.\n",
      phase,
      static_cast<unsigned long>(millis() - commandStartedAt));
  return true;
}

bool waitForPowerOffCompletion(uint32_t commandStartedAt) {
  // Some GDEM075F53 controller revisions assert BUSY during power off, while
  // others remain at the idle HIGH level after accepting command 0x02.  Watch
  // briefly for either behavior without weakening the strict power-on and
  // full-refresh handshakes above.
  while (digitalRead(kBusyPin) == HIGH) {
    if (millis() - commandStartedAt >= kPowerOffBusyObserveMs) {
      Serial.printf(
          "    BUSY stayed idle for %lu ms after power off; continuing.\n",
          static_cast<unsigned long>(kPowerOffBusyObserveMs));
      return true;
    }
    delay(5);
  }

  Serial.printf(
      "    BUSY asserted after %lu ms; waiting for power off to finish...\n",
      static_cast<unsigned long>(millis() - commandStartedAt));
  if (!waitUntilIdle("power off")) {
    return false;
  }
  Serial.printf(
      "    power off completed in %lu ms.\n",
      static_cast<unsigned long>(millis() - commandStartedAt));
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

void sendFrame(const uint8_t* frame) {
  writeCommand(0x10);
  digitalWrite(kCsPin, LOW);
  digitalWrite(kDcPin, HIGH);
  for (size_t index = 0; index < kExpectedFrameBytes; ++index) {
    SPI.transfer(frame[index]);
  }
  digitalWrite(kCsPin, HIGH);
}

bool refreshPanel() {
  const uint32_t commandStartedAt = millis();
  writeCommand(0x12);
  writeData(0x00);
  return waitForBusyCycle("full refresh", commandStartedAt);
}

bool sleepPanel() {
  const uint32_t commandStartedAt = millis();
  writeCommand(0x02);
  writeData(0x00);
  if (!waitForPowerOffCompletion(commandStartedAt)) {
    return false;
  }
  writeCommand(0x07);
  writeData(0xA5);
  return true;
}

bool waitForWifiConnection(uint32_t timeoutMs) {
  const uint32_t startedAt = millis();
  uint32_t lastProgressAt = startedAt;
  while (WiFi.status() != WL_CONNECTED) {
    if (millis() - startedAt >= timeoutMs) {
      return false;
    }
    if (millis() - lastProgressAt >= 500) {
      Serial.print(".");
      lastProgressAt = millis();
    }
    delay(25);
  }
  return true;
}

bool hasCachedWifiRoute() {
  if (cachedWifiChannel == 0 || cachedWifiChannel > 14) {
    return false;
  }
  for (const uint8_t octet : cachedWifiBssid) {
    if (octet != 0) {
      return true;
    }
  }
  return false;
}

void rememberCurrentWifiRoute() {
  const int32_t channel = WiFi.channel();
  const uint8_t* bssid = WiFi.BSSID();
  if (channel <= 0 || channel > 14 || bssid == nullptr) {
    return;
  }
  cachedWifiChannel = static_cast<uint8_t>(channel);
  memcpy(cachedWifiBssid, bssid, sizeof(cachedWifiBssid));
}

bool connectWifi() {
  const uint32_t startedAt = millis();
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("1/8 Wi-Fi connected: %s\n",
                  WiFi.localIP().toString().c_str());
    return true;
  }

  WiFi.persistent(false);
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(false);

  if (hasCachedWifiRoute()) {
    Serial.printf(
        "1/7 Fast Wi-Fi connect on cached channel %u",
        static_cast<unsigned int>(cachedWifiChannel));
    WiFi.begin(
        runtimeConfig.wifiSsid.c_str(),
        runtimeConfig.wifiPassword.c_str(),
        cachedWifiChannel,
        cachedWifiBssid,
        true);
    if (waitForWifiConnection(kFastConnectTimeoutMs)) {
      rememberCurrentWifiRoute();
      Serial.println();
      Serial.printf("    ESP32 IPv4: %s\n", WiFi.localIP().toString().c_str());
      Serial.printf(
          "    Wi-Fi ready in %lu ms (fast path).\n",
          static_cast<unsigned long>(millis() - startedAt));
      return true;
    }
    Serial.println();
    Serial.println("    Fast path missed; falling back to full Wi-Fi connect.");
    WiFi.disconnect(false, false);
    delay(50);
  }

  WiFi.begin(
      runtimeConfig.wifiSsid.c_str(),
      runtimeConfig.wifiPassword.c_str());

  Serial.print("1/7 Connecting to Wi-Fi");
  if (!waitForWifiConnection(kConnectTimeoutMs)) {
    Serial.println();
    Serial.printf("ERROR: Wi-Fi connection timeout, status=%d\n",
                  static_cast<int>(WiFi.status()));
    return false;
  }
  rememberCurrentWifiRoute();
  Serial.println();
  Serial.printf("    ESP32 IPv4: %s\n", WiFi.localIP().toString().c_str());
  Serial.printf(
      "    Wi-Fi ready in %lu ms (full path).\n",
      static_cast<unsigned long>(millis() - startedAt));
  return true;
}

bool retainedClockIsFresh() {
  const time_t now = time(nullptr);
  if (now < kMinimumValidUnixTime ||
      lastClockSyncEpoch < kMinimumValidUnixTime ||
      now < lastClockSyncEpoch) {
    return false;
  }
  return static_cast<uint64_t>(now - lastClockSyncEpoch) <
         kClockResyncIntervalSeconds;
}

bool synchronizeClock(bool forceNtp) {
  if (!forceNtp && retainedClockIsFresh()) {
    const time_t now = time(nullptr);
    const uint32_t ageSeconds =
        static_cast<uint32_t>(now - lastClockSyncEpoch);
    Serial.printf(
        "2/8 Retained clock ready: %lu (last NTP %lu seconds ago)\n",
        static_cast<unsigned long>(now),
        static_cast<unsigned long>(ageSeconds));
    return true;
  }

  const uint32_t startedAt = millis();
  clockSynchronizedByNtp = false;
  esp_sntp_stop();
  sntp_set_time_sync_notification_cb(onClockSynchronized);
  Serial.print("2/8 Synchronizing time from NTP");
  configTime(
      0,
      0,
      "ntp.aliyun.com",
      "ntp.tencent.com",
      "pool.ntp.org");

  while (!clockSynchronizedByNtp) {
    if (millis() - startedAt >= kTimeSyncTimeoutMs) {
      Serial.println();
      Serial.println("ERROR: NTP time synchronization timed out.");
      esp_sntp_stop();
      return false;
    }
    Serial.print(".");
    delay(500);
  }

  const time_t synchronizedTime = time(nullptr);
  if (synchronizedTime < kMinimumValidUnixTime) {
    Serial.println();
    Serial.println("ERROR: NTP returned an invalid Unix timestamp.");
    esp_sntp_stop();
    return false;
  }

  lastClockSyncEpoch = synchronizedTime;
  ntpSynchronizedThisWake = true;
  esp_sntp_stop();
  Serial.println();
  Serial.printf("    NTP synchronized: %lu\n",
                static_cast<unsigned long>(synchronizedTime));
  Serial.printf(
      "    NTP ready in %lu ms.\n",
      static_cast<unsigned long>(millis() - startedAt));
  return true;
}

String makeNonce() {
  char nonce[33];
  for (size_t index = 0; index < 16; ++index) {
    snprintf(
        nonce + index * 2,
        3,
        "%02x",
        static_cast<unsigned int>(esp_random() & 0xFF));
  }
  nonce[32] = '\0';
  return String(nonce);
}

bool calculateHmacSha256(
    const String& message,
    String& signature) {
  const mbedtls_md_info_t* info =
      mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
  if (info == nullptr) {
    Serial.println("ERROR: SHA-256 implementation is unavailable.");
    return false;
  }

  unsigned char digest[32];
  const int result = mbedtls_md_hmac(
      info,
      reinterpret_cast<const unsigned char*>(kDeviceSecret),
      strlen(kDeviceSecret),
      reinterpret_cast<const unsigned char*>(message.c_str()),
      message.length(),
      digest);
  if (result != 0) {
    Serial.printf("ERROR: HMAC-SHA256 failed, code=%d.\n", result);
    return false;
  }

  char hexDigest[65];
  for (size_t index = 0; index < sizeof(digest); ++index) {
    snprintf(
        hexDigest + index * 2,
        3,
        "%02x",
        static_cast<unsigned int>(digest[index]));
  }
  hexDigest[64] = '\0';
  signature = String(hexDigest);
  return true;
}

String calculateSha256(const String& content) {
  SHA256Builder sha256;
  sha256.begin();
  sha256.add(
      reinterpret_cast<const uint8_t*>(content.c_str()),
      content.length());
  sha256.calculate();
  return sha256.toString();
}

bool addSignedDeviceHeaders(
    HTTPClient& http,
    const String& method,
    const String& path,
    const String& ifNoneMatch,
    const String& contentSha256) {
  if (strlen(kDeviceSecret) < 32) {
    Serial.println("ERROR: device secret is missing or too short.");
    return false;
  }
  const String timestamp = String(static_cast<unsigned long>(time(nullptr)));
  const String nonce = makeNonce();
  const String signingText =
      method + "\n" + path + "\n" + timestamp + "\n" + nonce + "\n" +
      ifNoneMatch + "\n" + kFirmwareVersion + "\n" +
      String(kFirmwareBuildNumber) + "\n" + kFirmwareHardware + "\n" +
      contentSha256;
  String signature;
  if (!calculateHmacSha256(signingText, signature)) {
    return false;
  }
  http.addHeader("X-Device-Auth-Version", "2");
  http.addHeader("X-Device-Timestamp", timestamp);
  http.addHeader("X-Device-Nonce", nonce);
  http.addHeader("X-Device-Signature", signature);
  http.addHeader("X-Device-Firmware-Version", kFirmwareVersion);
  http.addHeader(
      "X-Device-Firmware-Build",
      String(kFirmwareBuildNumber));
  http.addHeader("X-Device-Hardware", kFirmwareHardware);
  http.addHeader("X-Device-OTA-Capability", "1");
  http.addHeader("X-Content-SHA256", contentSha256);
  return true;
}

bool isLowercaseHex(const String& value, size_t expectedLength) {
  if (value.length() != expectedLength) {
    return false;
  }
  for (size_t index = 0; index < expectedLength; ++index) {
    const char character = value[index];
    if (!((character >= '0' && character <= '9') ||
          (character >= 'a' && character <= 'f'))) {
      return false;
    }
  }
  return true;
}

bool parseUnsigned(const String& text, uint32_t& value) {
  if (text.isEmpty()) {
    return false;
  }
  char* end = nullptr;
  const unsigned long parsed = strtoul(text.c_str(), &end, 10);
  if (end == text.c_str() || *end != '\0') {
    return false;
  }
  value = static_cast<uint32_t>(parsed);
  return true;
}

bool readFirmwareOffer(HTTPClient& http, FirmwareOffer& offer) {
  if (http.header("X-Firmware-Update") != "available") {
    return false;
  }
  offer.releaseId = http.header("X-Firmware-Release-Id");
  offer.version = http.header("X-Firmware-Version");
  offer.hardware = http.header("X-Firmware-Hardware");
  offer.path = http.header("X-Firmware-Path");
  offer.sha256 = http.header("X-Firmware-SHA256");
  uint32_t signedSize = 0;
  if (
      offer.releaseId.length() != 36 ||
      offer.version.isEmpty() || offer.version.length() > 32 ||
      offer.hardware != kFirmwareHardware ||
      !parseUnsigned(http.header("X-Firmware-Build"), offer.buildNumber) ||
      !parseUnsigned(http.header("X-Firmware-Size"), signedSize) ||
      offer.buildNumber <= kFirmwareBuildNumber ||
      signedSize <= kOtaSignatureTrailerBytes ||
      signedSize > kMaximumSignedFirmwareBytes ||
      !isLowercaseHex(offer.sha256, 64)) {
    Serial.println("WARNING: server returned an invalid OTA offer; ignoring it.");
    offer = FirmwareOffer();
    return false;
  }
  const String expectedPrefix =
      String("/v1/devices/") + kDeviceCode + "/firmware/";
  if (!offer.path.startsWith(expectedPrefix) ||
      offer.path != expectedPrefix + offer.releaseId) {
    Serial.println("WARNING: OTA download path failed validation; ignoring it.");
    offer = FirmwareOffer();
    return false;
  }
  offer.signedSize = signedSize;
  return true;
}

bool isOfferBackedOff(const FirmwareOffer& offer) {
  Preferences preferences;
  if (!preferences.begin(kOtaPreferencesNamespace, true)) {
    return false;
  }
  const String failedId = preferences.getString("failed-id", "");
  const uint32_t failedAt = preferences.getUInt("failed-at", 0);
  preferences.end();
  const uint32_t now = static_cast<uint32_t>(time(nullptr));
  return failedId == offer.releaseId && failedAt > 0 && now >= failedAt &&
         now - failedAt < kOtaFailureBackoffSeconds;
}

void rememberOtaFailure(const FirmwareOffer& offer) {
  Preferences preferences;
  if (!preferences.begin(kOtaPreferencesNamespace, false)) {
    return;
  }
  preferences.putString("failed-id", offer.releaseId);
  preferences.putUInt("failed-at", static_cast<uint32_t>(time(nullptr)));
  preferences.end();
}

void clearOtaFailure() {
  Preferences preferences;
  if (!preferences.begin(kOtaPreferencesNamespace, false)) {
    return;
  }
  preferences.remove("failed-id");
  preferences.remove("failed-at");
  preferences.end();
}

bool savePendingOta(const FirmwareOffer& offer) {
  Preferences preferences;
  if (!preferences.begin(kOtaPreferencesNamespace, false)) {
    return false;
  }
  const bool saved =
      preferences.putString("pending-id", offer.releaseId) > 0 &&
      preferences.putString("pending-ver", offer.version) > 0 &&
      preferences.putUInt("pending-build", offer.buildNumber) > 0;
  preferences.end();
  return saved;
}

bool loadPendingOta(FirmwareOffer& offer) {
  Preferences preferences;
  if (!preferences.begin(kOtaPreferencesNamespace, true)) {
    return false;
  }
  offer.releaseId = preferences.getString("pending-id", "");
  offer.version = preferences.getString("pending-ver", "");
  offer.buildNumber = preferences.getUInt("pending-build", 0);
  preferences.end();
  offer.hardware = kFirmwareHardware;
  return offer.releaseId.length() == 36 && offer.buildNumber > 0;
}

void clearPendingOta() {
  Preferences preferences;
  if (!preferences.begin(kOtaPreferencesNamespace, false)) {
    return;
  }
  preferences.remove("pending-id");
  preferences.remove("pending-ver");
  preferences.remove("pending-build");
  preferences.end();
}

bool sendFirmwareReport(
    const FirmwareOffer& offer,
    const char* event,
    const char* detail = nullptr) {
  const String path =
      String("/v1/devices/") + kDeviceCode + "/firmware/report";
  const String url = runtimeConfig.apiBaseUrl + path;
  String body = String("{\"release_id\":\"") + offer.releaseId +
                "\",\"event\":\"" + event + "\"";
  if (detail != nullptr) {
    body += String(",\"detail\":\"") + detail + "\"";
  }
  body += "}";

  WiFiClient plainClient;
  NetworkClientSecure secureClient;
  NetworkClient* client = &plainClient;
  if (url.startsWith("https://")) {
    secureClient.setCACert(kIsrgRootX1);
    client = &secureClient;
  }
  HTTPClient http;
  http.setConnectTimeout(kHttpTimeoutMs);
  http.setTimeout(kHttpTimeoutMs);
  if (!http.begin(*client, url)) {
    return false;
  }
  http.addHeader("Content-Type", "application/json");
  if (!addSignedDeviceHeaders(
          http,
          "POST",
          path,
          "",
          calculateSha256(body))) {
    http.end();
    return false;
  }
  const int statusCode = http.POST(body);
  http.end();
  if (statusCode != HTTP_CODE_NO_CONTENT) {
    Serial.printf(
        "WARNING: OTA %s report failed, HTTP status=%d.\n",
        event,
        statusCode);
    return false;
  }
  return true;
}

bool failFirmwareUpdate(
    const FirmwareOffer& offer,
    const char* detail) {
  Serial.printf("ERROR: OTA failed: %s\n", detail);
  rememberOtaFailure(offer);
  sendFirmwareReport(offer, "failed", detail);
  return false;
}

bool performFirmwareUpdate(const FirmwareOffer& offer) {
#if !RFM_OTA_PUBLIC_KEY_CONFIGURED
  return failFirmwareUpdate(offer, "public_key_not_configured");
#else
  Serial.println();
  Serial.printf(
      "OTA: downloading %s, build %lu (%u bytes).\n",
      offer.version.c_str(),
      static_cast<unsigned long>(offer.buildNumber),
      static_cast<unsigned int>(offer.signedSize));
  const String url = runtimeConfig.apiBaseUrl + offer.path;
  WiFiClient plainClient;
  NetworkClientSecure secureClient;
  NetworkClient* client = &plainClient;
  if (url.startsWith("https://")) {
    secureClient.setCACert(kIsrgRootX1);
    client = &secureClient;
  }
  HTTPClient http;
  http.setConnectTimeout(kHttpTimeoutMs);
  http.setTimeout(kHttpTimeoutMs);
  if (!http.begin(*client, url)) {
    return failFirmwareUpdate(offer, "http_begin_failed");
  }
  if (!addSignedDeviceHeaders(
          http,
          "GET",
          offer.path,
          "",
          kEmptySha256)) {
    http.end();
    return failFirmwareUpdate(offer, "request_signing_failed");
  }
  uint8_t* downloadBuffer = static_cast<uint8_t*>(heap_caps_malloc(
      kDownloadChunkBytes,
      MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  if (downloadBuffer == nullptr) {
    http.end();
    return failFirmwareUpdate(offer, "ota_download_buffer_unavailable");
  }
  Serial.printf(
      "OTA: download buffer allocated in PSRAM; free loop stack=%u bytes.\n",
      static_cast<unsigned int>(uxTaskGetStackHighWaterMark(nullptr)));
  const int statusCode = http.GET();
  if (statusCode != HTTP_CODE_OK) {
    heap_caps_free(downloadBuffer);
    http.end();
    return failFirmwareUpdate(offer, "download_http_failed");
  }
  if (http.getSize() != static_cast<int>(offer.signedSize)) {
    heap_caps_free(downloadBuffer);
    http.end();
    return failFirmwareUpdate(offer, "download_size_header_mismatch");
  }

  UpdaterECDSAVerifier verifier(PUBLIC_KEY, PUBLIC_KEY_LEN, HASH_SHA256);
  if (!Update.installSignature(&verifier) ||
      !Update.begin(offer.signedSize, U_FLASH)) {
    heap_caps_free(downloadBuffer);
    http.end();
    return failFirmwareUpdate(offer, "ota_partition_unavailable");
  }

  SHA256Builder sha256;
  sha256.begin();
  WiFiClient* stream = http.getStreamPtr();
  size_t received = 0;
  uint32_t lastDataAt = millis();
  while (received < offer.signedSize) {
    const size_t remaining = offer.signedSize - received;
    const size_t wanted =
        remaining < kDownloadChunkBytes ? remaining : kDownloadChunkBytes;
    const size_t bytesRead = stream->readBytes(downloadBuffer, wanted);
    if (bytesRead > 0) {
      sha256.add(downloadBuffer, bytesRead);
      if (Update.write(downloadBuffer, bytesRead) != bytesRead) {
        Update.abort();
        heap_caps_free(downloadBuffer);
        http.end();
        return failFirmwareUpdate(offer, "flash_write_failed");
      }
      received += bytesRead;
      lastDataAt = millis();
      continue;
    }
    if (!http.connected() || millis() - lastDataAt >= kHttpTimeoutMs) {
      break;
    }
    delay(10);
  }
  heap_caps_free(downloadBuffer);
  http.end();
  if (received != offer.signedSize) {
    Update.abort();
    return failFirmwareUpdate(offer, "download_incomplete");
  }
  sha256.calculate();
  if (!sha256.toString().equalsIgnoreCase(offer.sha256)) {
    Update.abort();
    return failFirmwareUpdate(offer, "download_sha256_mismatch");
  }
  if (!savePendingOta(offer)) {
    Update.abort();
    return failFirmwareUpdate(offer, "pending_state_save_failed");
  }
  if (!Update.end() || !Update.isFinished()) {
    clearPendingOta();
    return failFirmwareUpdate(offer, "signature_or_image_verification_failed");
  }

  clearOtaFailure();
  sendFirmwareReport(offer, "downloaded");
  Serial.println("OTA: signature valid; rebooting into the inactive slot.");
  Serial.flush();
  delay(250);
  ESP.restart();
  while (true) {
    delay(1000);
  }
#endif
}

bool runningImagePendingVerification() {
  const esp_partition_t* running = esp_ota_get_running_partition();
  esp_ota_img_states_t state;
  return running != nullptr &&
         esp_ota_get_state_partition(running, &state) == ESP_OK &&
         state == ESP_OTA_IMG_PENDING_VERIFY;
}

[[noreturn]] void rejectPendingImage(const char* reason) {
  Serial.printf("FATAL: rejecting pending OTA image: %s\n", reason);
  Serial.flush();
  delay(100);
  const esp_err_t result = esp_ota_mark_app_invalid_rollback_and_reboot();
  Serial.printf("FATAL: rollback failed, code=%d.\n", static_cast<int>(result));
  while (true) {
    delay(1000);
  }
}

void validatePendingImageIfNeeded() {
  if (!runningImagePendingVerification()) {
    return;
  }
  Serial.println("OTA: validating newly installed image before acceptance.");
  FirmwareOffer pending;
  if (!loadPendingOta(pending) ||
      pending.buildNumber != kFirmwareBuildNumber ||
      pending.version != kFirmwareVersion) {
    rejectPendingImage("release_metadata_mismatch");
  }
  uint8_t* psramProbe = static_cast<uint8_t*>(heap_caps_malloc(
      kExpectedFrameBytes,
      MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  if (psramProbe == nullptr) {
    rejectPendingImage("psram_self_test_failed");
  }
  heap_caps_free(psramProbe);
  if (!connectWifi() || !synchronizeClock(true)) {
    rejectPendingImage("network_self_test_failed");
  }
  if (!sendFirmwareReport(pending, "installed")) {
    rejectPendingImage("backend_confirmation_failed");
  }
  if (esp_ota_mark_app_valid_cancel_rollback() != ESP_OK) {
    rejectPendingImage("mark_valid_failed");
  }
  clearPendingOta();
  clearOtaFailure();
  Serial.println("OTA: new image accepted.");
}

void reportPreviousRollbackIfNeeded() {
  FirmwareOffer pending;
  if (!loadPendingOta(pending)) {
    return;
  }
  if (pending.buildNumber > kFirmwareBuildNumber) {
    if (sendFirmwareReport(pending, "rolled_back", "boot_validation_failed")) {
      clearPendingOta();
    }
    return;
  }
  if (pending.buildNumber == kFirmwareBuildNumber) {
    if (sendFirmwareReport(pending, "installed")) {
      clearPendingOta();
    }
    return;
  }
  clearPendingOta();
}

String loadCachedEtag() {
  Preferences preferences;
  if (!preferences.begin(kPreferencesNamespace, false)) {
    Serial.println("WARNING: could not open NVS to read cached ETag.");
    return "";
  }
  const String etag = preferences.getString(kEtagPreferenceKey, "");
  preferences.end();
  return etag;
}

bool saveCachedEtag(const String& etag) {
  Preferences preferences;
  if (!preferences.begin(kPreferencesNamespace, false)) {
    Serial.println("ERROR: could not open NVS to save ETag.");
    return false;
  }
  const size_t savedBytes = preferences.putString(kEtagPreferenceKey, etag);
  preferences.end();
  if (savedBytes == 0) {
    Serial.println("ERROR: could not save ETag to NVS.");
    return false;
  }
  return true;
}

void clearCachedEtag() {
  Preferences preferences;
  if (preferences.begin(kPreferencesNamespace, false)) {
    preferences.remove(kEtagPreferenceKey);
    preferences.end();
  }
}

bool pairingFrameWasShown() {
  Preferences preferences;
  if (!preferences.begin(kPairingPreferencesNamespace, true)) {
    return false;
  }
  const bool shown = preferences.getBool(kPairingFrameShownKey, false);
  preferences.end();
  return shown;
}

bool savePairingFrameShown() {
  Preferences preferences;
  if (!preferences.begin(kPairingPreferencesNamespace, false)) {
    return false;
  }
  const size_t saved = preferences.putBool(kPairingFrameShownKey, true);
  preferences.end();
  return saved == sizeof(uint8_t);
}

void clearPairingFrameShown() {
  Preferences preferences;
  if (preferences.begin(kPairingPreferencesNamespace, false)) {
    preferences.clear();
    preferences.end();
  }
}

FrameFetchResult downloadAndValidateFrame(
    const String& cachedEtag,
    uint8_t*& frame,
    String& downloadedEtag,
    FirmwareOffer& firmwareOffer,
    bool acceptFirmwareOffer) {
  const String path = String("/v1/devices/") + kDeviceCode + "/frame";
  const String url = runtimeConfig.apiBaseUrl + path;
  const char* responseHeaders[] = {
      "ETag",
      "X-Frame-Version",
      "X-Frame-SHA256",
      "X-Panel-Model",
      "X-Firmware-Update",
      "X-Firmware-Release-Id",
      "X-Firmware-Version",
      "X-Firmware-Build",
      "X-Firmware-Hardware",
      "X-Firmware-Size",
      "X-Firmware-SHA256",
      "X-Firmware-Path",
      "X-Device-State",
  };

  WiFiClient plainClient;
  NetworkClientSecure secureClient;
  NetworkClient* client = &plainClient;
  if (url.startsWith("https://")) {
    secureClient.setCACert(kIsrgRootX1);
    client = &secureClient;
  }
  HTTPClient http;
  http.setConnectTimeout(kHttpTimeoutMs);
  http.setTimeout(kHttpTimeoutMs);
  http.collectHeaders(
      responseHeaders,
      sizeof(responseHeaders) / sizeof(responseHeaders[0]));

  Serial.printf("3/8 Signed GET %s\n", url.c_str());
  Serial.printf("    Device: %s\n", kDeviceCode);
  if (!http.begin(*client, url)) {
    Serial.println("ERROR: HTTP client initialization failed.");
    return FrameFetchResult::kFailed;
  }
  if (!cachedEtag.isEmpty()) {
    http.addHeader("If-None-Match", cachedEtag);
    Serial.printf("    If-None-Match: %s\n", cachedEtag.c_str());
  } else {
    Serial.println("    No cached ETag; requesting the complete frame.");
  }
  if (!addSignedDeviceHeaders(
          http,
          "GET",
          path,
          cachedEtag,
          kEmptySha256)) {
    http.end();
    return FrameFetchResult::kFailed;
  }

  const uint32_t requestStartedAt = millis();
  const int statusCode = http.GET();
  Serial.printf("    HTTP status: %d\n", statusCode);
  Serial.printf(
      "    HTTP completed in %lu ms.\n",
      static_cast<unsigned long>(millis() - requestStartedAt));
  if (statusCode == HTTP_CODE_UNAUTHORIZED) {
    http.end();
    Serial.println(
        "    Authentication rejected; retained clock may need an NTP refresh.");
    return FrameFetchResult::kAuthenticationRejected;
  }
  if (statusCode == HTTP_CODE_CONFLICT &&
      http.header("X-Device-State") == "unbound") {
    http.end();
    Serial.println("    Backend confirmed that this device is unbound.");
    return FrameFetchResult::kDeviceUnbound;
  }
  FirmwareOffer offered;
  if ((statusCode == HTTP_CODE_OK || statusCode == HTTP_CODE_NOT_MODIFIED) &&
      readFirmwareOffer(http, offered)) {
    const bool backedOff = isOfferBackedOff(offered);
    if (acceptFirmwareOffer && !backedOff) {
      firmwareOffer = offered;
      http.end();
      Serial.printf(
          "    OTA available: %s, build %lu.\n",
          offered.version.c_str(),
          static_cast<unsigned long>(offered.buildNumber));
      return FrameFetchResult::kFirmwareUpdateAvailable;
    }
    if (backedOff) {
      Serial.println("    OTA offer is in the six-hour failure backoff window.");
    }
  }
  if (statusCode == HTTP_CODE_NOT_MODIFIED) {
    http.end();
    Serial.println("    Frame is unchanged; keeping the current display.");
    return FrameFetchResult::kNotModified;
  }
  if (statusCode != HTTP_CODE_OK) {
    if (statusCode < 0) {
      Serial.printf("ERROR: %s\n",
                    HTTPClient::errorToString(statusCode).c_str());
    } else {
      Serial.println("ERROR: server did not return HTTP 200.");
    }
    http.end();
    return FrameFetchResult::kFailed;
  }

  const int contentLength = http.getSize();
  const String panelModel = http.header("X-Panel-Model");
  const String expectedSha256 = http.header("X-Frame-SHA256");
  const String frameVersion = http.header("X-Frame-Version");
  const String etag = http.header("ETag");

  Serial.printf("4/8 Validating headers: %d bytes, panel=%s\n",
                contentLength, panelModel.c_str());
  if (contentLength != static_cast<int>(kExpectedFrameBytes)) {
    Serial.printf("ERROR: expected %u bytes, server announced %d.\n",
                  static_cast<unsigned int>(kExpectedFrameBytes),
                  contentLength);
    http.end();
    return FrameFetchResult::kFailed;
  }
  if (panelModel != kExpectedPanelModel) {
    Serial.printf("ERROR: expected panel %s, got %s.\n",
                  kExpectedPanelModel, panelModel.c_str());
    http.end();
    return FrameFetchResult::kFailed;
  }
  if (expectedSha256.length() != 64) {
    Serial.println("ERROR: missing or invalid X-Frame-SHA256 header.");
    http.end();
    return FrameFetchResult::kFailed;
  }
  if (etag.isEmpty()) {
    Serial.println("ERROR: missing ETag header.");
    http.end();
    return FrameFetchResult::kFailed;
  }

  frame = static_cast<uint8_t*>(
      heap_caps_malloc(kExpectedFrameBytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  if (frame == nullptr) {
    Serial.println("ERROR: could not allocate 96,000 bytes in PSRAM.");
    http.end();
    return FrameFetchResult::kFailed;
  }

  Serial.println("5/8 Downloading frame into PSRAM...");
  SHA256Builder sha256;
  sha256.begin();
  WiFiClient* stream = http.getStreamPtr();
  size_t received = 0;
  uint32_t lastDataAt = millis();

  while (received < kExpectedFrameBytes) {
    const size_t remaining = kExpectedFrameBytes - received;
    const size_t chunkSize =
        remaining < kDownloadChunkBytes ? remaining : kDownloadChunkBytes;
    const size_t bytesRead = stream->readBytes(frame + received, chunkSize);

    if (bytesRead > 0) {
      sha256.add(frame + received, bytesRead);
      received += bytesRead;
      lastDataAt = millis();
      continue;
    }

    if (!http.connected() || millis() - lastDataAt >= kHttpTimeoutMs) {
      break;
    }
    delay(10);
  }
  http.end();

  Serial.printf("    Received: %u bytes\n",
                static_cast<unsigned int>(received));
  if (received != kExpectedFrameBytes) {
    Serial.printf("ERROR: incomplete frame, expected %u bytes.\n",
                  static_cast<unsigned int>(kExpectedFrameBytes));
    heap_caps_free(frame);
    frame = nullptr;
    return FrameFetchResult::kFailed;
  }

  sha256.calculate();
  const String actualSha256 = sha256.toString();
  Serial.println("6/8 Verifying SHA-256...");
  if (!actualSha256.equalsIgnoreCase(expectedSha256)) {
    Serial.printf("ERROR: SHA-256 mismatch.\nExpected: %s\nActual  : %s\n",
                  expectedSha256.c_str(), actualSha256.c_str());
    heap_caps_free(frame);
    frame = nullptr;
    return FrameFetchResult::kFailed;
  }

  Serial.printf("    Version: %s\n", frameVersion.c_str());
  Serial.printf("    ETag   : %s\n", etag.c_str());
  Serial.printf("    SHA-256: %s\n", actualSha256.c_str());
  downloadedEtag = etag;
  return FrameFetchResult::kDownloaded;
}

bool displayFrame(const uint8_t* frame) {
  pinMode(kBusyPin, INPUT);
  pinMode(kResetPin, OUTPUT);
  pinMode(kDcPin, OUTPUT);
  pinMode(kCsPin, OUTPUT);
  digitalWrite(kResetPin, HIGH);
  digitalWrite(kDcPin, HIGH);
  digitalWrite(kCsPin, HIGH);

  SPI.begin(kSckPin, -1, kMosiPin, kCsPin);
  SPI.beginTransaction(panelSpi);

  Serial.println("7/8 Initializing panel and sending validated frame...");
  if (!initializePanel()) {
    SPI.endTransaction();
    SPI.end();
    return false;
  }
  sendFrame(frame);

  Serial.println("8/8 Refreshing; do not disconnect power...");
  if (!refreshPanel()) {
    SPI.endTransaction();
    SPI.end();
    return false;
  }
  if (!sleepPanel()) {
    SPI.endTransaction();
    SPI.end();
    return false;
  }

  SPI.endTransaction();
  SPI.end();
  return true;
}

bool displayFactoryPairingFrameIfNeeded(bool forceRefresh) {
#if RFM_FACTORY_PAIRING_FRAME_CONFIGURED
  static_assert(
      kFactoryPairingFrameSize == kExpectedFrameBytes,
      "factory pairing frame must contain exactly 96,000 bytes");
  if (!forceRefresh && pairingFrameWasShown()) {
    Serial.println(
        "PAIRING DISPLAY: already shown; preserving the current e-paper image.");
    return true;
  }
  Serial.println("PAIRING DISPLAY: showing this device's mini-program code.");
  if (!displayFrame(kFactoryPairingFrame)) {
    Serial.println("WARNING: could not refresh the factory pairing display.");
    return false;
  }
  if (!savePairingFrameShown()) {
    Serial.println("WARNING: could not remember the pairing display state.");
  }
  Serial.printf("PAIRING DEVICE: %s\n", kFactoryPairingDeviceCode);
  return true;
#else
  (void)forceRefresh;
  Serial.println(
      "WARNING: factory_pairing_frame.h is missing; BLE provisioning remains available.");
  return false;
#endif
}

UpdateCycleResult runUpdateCycle() {
  Serial.println();
  Serial.println("=== Scheduled frame update check ===");

  if (!connectWifi()) {
    return UpdateCycleResult::kFailed;
  }
  if (!synchronizeClock(false)) {
    return UpdateCycleResult::kFailed;
  }
  reportPreviousRollbackIfNeeded();

  const String cachedEtag = loadCachedEtag();
  if (cachedEtag.isEmpty()) {
    Serial.println("    Cached ETag: none");
  } else {
    Serial.printf("    Cached ETag: %s\n", cachedEtag.c_str());
  }

  uint8_t* frame = nullptr;
  String downloadedEtag;
  FirmwareOffer firmwareOffer;
  FrameFetchResult fetchResult =
      downloadAndValidateFrame(
          cachedEtag,
          frame,
          downloadedEtag,
          firmwareOffer,
          true);
  if (fetchResult == FrameFetchResult::kAuthenticationRejected &&
      !ntpSynchronizedThisWake) {
    Serial.println(
        "    Retrying once after a forced NTP synchronization.");
    if (!synchronizeClock(true)) {
      return UpdateCycleResult::kFailed;
    }
    fetchResult = downloadAndValidateFrame(
        cachedEtag,
        frame,
        downloadedEtag,
        firmwareOffer,
        true);
  }
  FrameFetchResult effectiveFetchResult = fetchResult;
  if (fetchResult == FrameFetchResult::kFirmwareUpdateAvailable) {
    performFirmwareUpdate(firmwareOffer);
    // A failed or temporarily blocked OTA must not prevent the normal frame
    // refresh. Fetch again while explicitly ignoring the same offer.
    effectiveFetchResult = downloadAndValidateFrame(
        cachedEtag,
        frame,
        downloadedEtag,
        firmwareOffer,
        false);
  }
  if (effectiveFetchResult == FrameFetchResult::kFailed) {
    return UpdateCycleResult::kFailed;
  }
  if (effectiveFetchResult == FrameFetchResult::kAuthenticationRejected) {
    Serial.println(
        "ERROR: device authentication was rejected after clock validation.");
    return UpdateCycleResult::kFailed;
  }
  if (effectiveFetchResult == FrameFetchResult::kDeviceUnbound) {
    return UpdateCycleResult::kDeviceUnbound;
  }
  if (effectiveFetchResult == FrameFetchResult::kNotModified) {
    Serial.println("ACTION: SKIP_REFRESH");
    return UpdateCycleResult::kSucceeded;
  }

  const bool displayed = displayFrame(frame);
  heap_caps_free(frame);
  if (!displayed) {
    return UpdateCycleResult::kFailed;
  }

  if (!saveCachedEtag(downloadedEtag)) {
    return UpdateCycleResult::kFailed;
  }

  clearPairingFrameShown();
  Serial.printf("Saved ETag : %s\n", downloadedEtag.c_str());
  Serial.println("ACTION: REFRESHED");
  return UpdateCycleResult::kSucceeded;
}

uint32_t nextSleepSeconds(bool succeeded) {
  if (succeeded) {
    consecutiveFailures = 0;
  } else {
    ++consecutiveFailures;
  }

  if (succeeded) {
    Serial.printf(
        "NEXT WAKE: %lu seconds\n",
        static_cast<unsigned long>(kPollIntervalSeconds));
  } else {
    Serial.printf(
        "RETRY WAKE: %lu seconds (failure streak=%lu)\n",
        static_cast<unsigned long>(kPollIntervalSeconds),
        static_cast<unsigned long>(consecutiveFailures));
  }
  return kPollIntervalSeconds;
}

void stopWifi() {
  esp_sntp_stop();
  WiFi.setAutoReconnect(false);
  WiFi.disconnect(true, false);
  WiFi.mode(WIFI_OFF);
  delay(50);
}

void releaseDeepSleepPinHolds() {
  gpio_deep_sleep_hold_dis();
  pinMode(kResetPin, OUTPUT);
  pinMode(kDcPin, OUTPUT);
  pinMode(kCsPin, OUTPUT);
  pinMode(kSckPin, OUTPUT);
  pinMode(kMosiPin, OUTPUT);
  pinMode(kRgbPin, OUTPUT);
  digitalWrite(kResetPin, HIGH);
  digitalWrite(kDcPin, LOW);
  digitalWrite(kCsPin, HIGH);
  digitalWrite(kSckPin, LOW);
  digitalWrite(kMosiPin, LOW);
  digitalWrite(kRgbPin, LOW);
  const gpio_num_t heldPins[] = {
      static_cast<gpio_num_t>(kResetPin),
      static_cast<gpio_num_t>(kDcPin),
      static_cast<gpio_num_t>(kCsPin),
      static_cast<gpio_num_t>(kSckPin),
      static_cast<gpio_num_t>(kMosiPin),
      static_cast<gpio_num_t>(kRgbPin),
  };
  for (const gpio_num_t pin : heldPins) {
    gpio_hold_dis(pin);
  }
}

void preparePinsForDeepSleep() {
  SPI.end();

  pinMode(kBusyPin, INPUT);
  gpio_set_pull_mode(
      static_cast<gpio_num_t>(kBusyPin),
      GPIO_FLOATING);

  pinMode(kResetPin, OUTPUT);
  pinMode(kDcPin, OUTPUT);
  pinMode(kCsPin, OUTPUT);
  pinMode(kSckPin, OUTPUT);
  pinMode(kMosiPin, OUTPUT);
  pinMode(kRgbPin, OUTPUT);
  digitalWrite(kResetPin, HIGH);
  digitalWrite(kDcPin, LOW);
  digitalWrite(kCsPin, HIGH);
  digitalWrite(kSckPin, LOW);
  digitalWrite(kMosiPin, LOW);
  digitalWrite(kRgbPin, LOW);

  const gpio_num_t heldPins[] = {
      static_cast<gpio_num_t>(kResetPin),
      static_cast<gpio_num_t>(kDcPin),
      static_cast<gpio_num_t>(kCsPin),
      static_cast<gpio_num_t>(kSckPin),
      static_cast<gpio_num_t>(kMosiPin),
      static_cast<gpio_num_t>(kRgbPin),
  };
  for (const gpio_num_t pin : heldPins) {
    gpio_hold_en(pin);
  }
  gpio_deep_sleep_hold_en();
}

[[noreturn]] void enterDeepSleep(uint32_t sleepSeconds) {
  stopWifi();
  preparePinsForDeepSleep();
  const esp_err_t timerResult = esp_sleep_enable_timer_wakeup(
      static_cast<uint64_t>(sleepSeconds) * kMicrosecondsPerSecond);
  if (timerResult != ESP_OK) {
    Serial.printf(
        "FATAL: could not configure deep-sleep timer, code=%d.\n",
        static_cast<int>(timerResult));
    Serial.flush();
    while (true) {
      delay(1000);
    }
  }

  Serial.printf("DEEP SLEEP: %lu seconds\n",
                static_cast<unsigned long>(sleepSeconds));
  Serial.println("Wi-Fi off; ESP32 entering deep sleep now.");
  Serial.flush();
  esp_deep_sleep_start();

  // esp_deep_sleep_start() does not normally return.
  while (true) {
    delay(1000);
  }
}

bool waitForBootHold() {
  const uint32_t windowStartedAt = millis();
  uint32_t pressedAt = 0;
  while (millis() - windowStartedAt < kBootActionWindowMs) {
    if (digitalRead(0) == LOW) {
      if (pressedAt == 0) {
        pressedAt = millis();
      } else if (millis() - pressedAt >= kBootHoldDurationMs) {
        return true;
      }
    } else {
      pressedAt = 0;
    }
    delay(50);
  }
  return false;
}

bool waitForRuntimeConfigReset() {
  Serial.println(
      "Saved configuration found. To clear it, press and hold BOOT now "
      "for 2 seconds.");
  return waitForBootHold();
}

bool waitForPairingFrameRedisplay() {
  Serial.println(
      "Pairing display already recorded. To show it again, press and hold "
      "BOOT now for 2 seconds.");
  return waitForBootHold();
}

}  // namespace

void setup() {
  const esp_sleep_wakeup_cause_t wakeupCause = esp_sleep_get_wakeup_cause();
  const bool timerWake = wakeupCause == ESP_SLEEP_WAKEUP_TIMER;

  releaseDeepSleepPinHolds();
  pinMode(kRgbPin, OUTPUT);
  digitalWrite(kRgbPin, LOW);
  Serial.begin(115200);
  delay(timerWake ? 150 : 2000);

  Serial.println();
  Serial.println("=== Refrigerator scheduled frame updater ===");
  Serial.printf("Wake reason: %s\n", timerWake ? "DEEP_SLEEP_TIMER" : "COLD_OR_RESET");
  Serial.printf(
      "Firmware: %s (build %lu, %s)\n",
      kFirmwareVersion,
      static_cast<unsigned long>(kFirmwareBuildNumber),
      kFirmwareHardware);
  Serial.println("Poll interval: 300 seconds (deep sleep between checks)");
  pinMode(0, INPUT_PULLUP);

  if (!timerWake) {
    consecutiveFailures = 0;
    lastClockSyncEpoch = 0;
    cachedWifiChannel = 0;
    memset(cachedWifiBssid, 0, sizeof(cachedWifiBssid));
  }

  bool hasRuntimeConfig = loadDeviceRuntimeConfig(runtimeConfig);
  // Only a real power-on or RST boot offers the configuration-reset window.
  // A five-minute timer wake skips this eight-second wait to save energy.
  if (hasRuntimeConfig && !timerWake && waitForRuntimeConfigReset()) {
    Serial.println("BOOT held after startup: clearing saved configuration.");
    clearDeviceRuntimeConfig();
    clearCachedEtag();
    clearPairingFrameShown();
    runtimeConfig = DeviceRuntimeConfig();
    hasRuntimeConfig = false;
  }

  bool forcePairingFrameRefresh = false;
  if (!hasRuntimeConfig && !timerWake && pairingFrameWasShown() &&
      waitForPairingFrameRedisplay()) {
    Serial.println(
        "BOOT held after startup: forcing pairing display refresh.");
    clearPairingFrameShown();
    forcePairingFrameRefresh = true;
  }

  while (true) {
    while (!hasRuntimeConfig) {
      displayFactoryPairingFrameIfNeeded(forcePairingFrameRefresh);
      forcePairingFrameRefresh = false;
      Serial.println("No saved configuration; starting secure BLE setup.");
      if (runBleProvisioning(runtimeConfig)) {
        hasRuntimeConfig = true;
        clearPairingFrameShown();
      } else {
        Serial.println(
            "BLE provisioning did not complete; retrying in 3 seconds.");
        delay(3000);
      }
    }
    Serial.println("Runtime configuration ready.");

    validatePendingImageIfNeeded();

    ntpSynchronizedThisWake = false;
    const uint32_t cycleStartedAt = millis();
    const UpdateCycleResult cycleResult = runUpdateCycle();
    Serial.printf(
        "CYCLE ELAPSED: %lu ms\n",
        static_cast<unsigned long>(millis() - cycleStartedAt));
    if (cycleResult == UpdateCycleResult::kDeviceUnbound) {
      Serial.println(
          "DEVICE STATE: UNBOUND; clearing household configuration and "
          "returning to BLE setup.");
      clearDeviceRuntimeConfig();
      clearCachedEtag();
      clearPairingFrameShown();
      runtimeConfig = DeviceRuntimeConfig();
      hasRuntimeConfig = false;
      stopWifi();
      displayFactoryPairingFrameIfNeeded(true);
      continue;
    }

    const bool succeeded = cycleResult == UpdateCycleResult::kSucceeded;
    Serial.println(succeeded ? "RESULT: PASS" : "RESULT: FAIL");
    enterDeepSleep(nextSleepSeconds(succeeded));
  }
}

void loop() {
  // setup() always enters deep sleep after one update attempt.
  delay(1000);
}
