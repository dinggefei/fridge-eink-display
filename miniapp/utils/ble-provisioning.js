const SERVICE_UUID = "7b9e0001-5f34-4f6f-9f46-7d4c8a1e0001";
const DEVICE_CODE_UUID = "7b9e0002-5f34-4f6f-9f46-7d4c8a1e0001";
const CHALLENGE_UUID = "7b9e0003-5f34-4f6f-9f46-7d4c8a1e0001";
const COMMAND_UUID = "7b9e0004-5f34-4f6f-9f46-7d4c8a1e0001";
const SAFE_CHUNK_SIZE = 12;

function normalizeUuid(value) {
  return String(value || "").toLowerCase();
}

function callWx(name, options = {}) {
  return new Promise((resolve, reject) => {
    wx[name]({ ...options, success: resolve, fail: reject });
  });
}

function wait(milliseconds) {
  return new Promise((resolve) => {
    setTimeout(resolve, milliseconds);
  });
}

function asciiBuffer(value) {
  const bytes = new Uint8Array(value.length);
  for (let index = 0; index < value.length; index += 1) {
    bytes[index] = value.charCodeAt(index) & 0xff;
  }
  return bytes.buffer;
}

function asciiString(buffer) {
  return Array.from(new Uint8Array(buffer))
    .map((value) => String.fromCharCode(value))
    .join("");
}

async function discoverDevice(timeoutMs = 15000) {
  await callWx("startBluetoothDevicesDiscovery", {
    services: [SERVICE_UUID],
    allowDuplicatesKey: false
  });
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      wx.offBluetoothDeviceFound(listener);
      reject(new Error("附近没有发现配网设备，请确认设备已进入配网模式"));
    }, timeoutMs);
    const listener = (event) => {
      const candidate = (event.devices || []).find((device) => {
        const services = device.advertisServiceUUIDs || [];
        return (
          services.some((uuid) => normalizeUuid(uuid) === SERVICE_UUID) ||
          String(device.localName || device.name || "").startsWith("RFM-")
        );
      });
      if (!candidate) {
        return;
      }
      clearTimeout(timer);
      wx.offBluetoothDeviceFound(listener);
      resolve(candidate);
    };
    wx.onBluetoothDeviceFound(listener);
  }).finally(() => {
    wx.stopBluetoothDevicesDiscovery({});
  });
}

function readCharacteristic(
  deviceId,
  serviceId,
  characteristicId,
  timeoutMs = 5000
) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      wx.offBLECharacteristicValueChange(listener);
      reject(new Error("读取设备信息超时"));
    }, timeoutMs);
    const listener = (event) => {
      if (
        event.deviceId !== deviceId ||
        normalizeUuid(event.characteristicId) !== normalizeUuid(characteristicId)
      ) {
        return;
      }
      clearTimeout(timer);
      wx.offBLECharacteristicValueChange(listener);
      resolve(asciiString(event.value));
    };
    wx.onBLECharacteristicValueChange(listener);
    wx.readBLECharacteristicValue({
      deviceId,
      serviceId,
      characteristicId,
      fail(error) {
        clearTimeout(timer);
        wx.offBLECharacteristicValueChange(listener);
        reject(error);
      }
    });
  });
}

async function writeCommand(device, command) {
  await callWx("writeBLECharacteristicValue", {
    deviceId: device.deviceId,
    serviceId: device.serviceId,
    characteristicId: device.commandCharacteristicId,
    value: asciiBuffer(command),
    writeType: "write"
  });
}

async function transmitPayload(device, encryptedPayload, sha256) {
  const chunks = [];
  for (
    let offset = 0;
    offset < encryptedPayload.length;
    offset += SAFE_CHUNK_SIZE
  ) {
    chunks.push(encryptedPayload.slice(offset, offset + SAFE_CHUNK_SIZE));
  }
  await writeCommand(device, `B|${chunks.length}`);
  for (let index = 0; index < chunks.length; index += 1) {
    await writeCommand(device, `D|${index}|${chunks[index]}`);
  }
  for (let index = 0; index < 4; index += 1) {
    await writeCommand(
      device,
      `H|${index}|${sha256.slice(index * 16, (index + 1) * 16)}`
    );
  }
  await writeCommand(device, "E");
}

async function openProvisioningDevice(expectedDeviceCode, onProgress) {
  onProgress("正在打开蓝牙…");
  await callWx("openBluetoothAdapter");
  onProgress("正在搜索附近设备…");
  const found = await discoverDevice();
  await callWx("createBLEConnection", {
    deviceId: found.deviceId,
    timeout: 10000
  });
  onProgress("正在读取设备身份…");
  // iOS may return error 10004 if a characteristic is accessed before
  // service and characteristic discovery has fully completed.
  await wait(300);
  const services = await callWx("getBLEDeviceServices", {
    deviceId: found.deviceId
  });
  const service = (services.services || []).find(
    (item) => normalizeUuid(item.uuid) === SERVICE_UUID
  );
  if (!service) {
    throw new Error("发现的设备不支持冰箱配网协议");
  }

  const characteristicResult = await callWx(
    "getBLEDeviceCharacteristics",
    {
      deviceId: found.deviceId,
      serviceId: service.uuid
    }
  );
  const characteristics = characteristicResult.characteristics || [];
  const deviceCodeCharacteristic = characteristics.find(
    (item) =>
      normalizeUuid(item.uuid) === DEVICE_CODE_UUID &&
      item.properties &&
      item.properties.read
  );
  const challengeCharacteristic = characteristics.find(
    (item) =>
      normalizeUuid(item.uuid) === CHALLENGE_UUID &&
      item.properties &&
      item.properties.read
  );
  const commandCharacteristic = characteristics.find(
    (item) =>
      normalizeUuid(item.uuid) === COMMAND_UUID &&
      item.properties &&
      (item.properties.write || item.properties.writeNoResponse)
  );
  if (
    !deviceCodeCharacteristic ||
    !challengeCharacteristic ||
    !commandCharacteristic
  ) {
    throw new Error("配网服务特征不完整，请确认 ESP32 已烧录最新固件");
  }

  await wait(100);
  const deviceCode = await readCharacteristic(
    found.deviceId,
    service.uuid,
    deviceCodeCharacteristic.uuid
  );
  if (expectedDeviceCode && deviceCode !== expectedDeviceCode) {
    throw new Error(`设备编号不一致，实际发现 ${deviceCode}`);
  }
  const challenge = await readCharacteristic(
    found.deviceId,
    service.uuid,
    challengeCharacteristic.uuid
  );
  if (!/^[0-9a-f]{32}$/i.test(challenge)) {
    throw new Error("设备配网挑战码格式错误");
  }
  return {
    deviceId: found.deviceId,
    serviceId: service.uuid,
    commandCharacteristicId: commandCharacteristic.uuid,
    deviceCode,
    challenge
  };
}

async function closeProvisioningDevice(deviceId) {
  if (deviceId) {
    try {
      await callWx("closeBLEConnection", { deviceId });
    } catch (error) {
      // The device normally disconnects itself while joining Wi-Fi.
    }
  }
  try {
    await callWx("closeBluetoothAdapter");
  } catch (error) {
    // Adapter may already be closed.
  }
}

module.exports = {
  closeProvisioningDevice,
  openProvisioningDevice,
  transmitPayload
};
