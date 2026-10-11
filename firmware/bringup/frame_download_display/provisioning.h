#pragma once

#include <Arduino.h>

struct DeviceRuntimeConfig {
  String wifiSsid;
  String wifiPassword;
  String apiBaseUrl;
};

bool loadDeviceRuntimeConfig(DeviceRuntimeConfig& config);
bool saveDeviceRuntimeConfig(const DeviceRuntimeConfig& config);
void clearDeviceRuntimeConfig();
bool runBleProvisioning(DeviceRuntimeConfig& config);
