const { request } = require("../../utils/request");
const {
  closeProvisioningDevice,
  openProvisioningDevice,
  transmitPayload
} = require("../../utils/ble-provisioning");

function wait(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function openTodayPage() {
  return new Promise((resolve, reject) => {
    wx.switchTab({
      url: "/pages/today/index",
      success: resolve,
      fail: reject
    });
  });
}

function errorMessage(error) {
  if (error && error.data && error.data.detail) {
    return error.data.detail;
  }
  if (error && Number(error.errCode) === 10004) {
    return "未找到 BLE 配网服务或特征，请确认设备仍处于配网模式后重试";
  }
  if (error && error.errMsg) {
    return error.errMsg;
  }
  return (error && error.message) || "绑定失败，请重试";
}

Page({
  data: {
    steps: [
      { number: 1, title: "确认设备编号", description: "扫描外壳上的小程序码或手动输入" },
      { number: 2, title: "蓝牙连接", description: "小程序发现附近的 ESP32-S3" },
      { number: 3, title: "配置 Wi-Fi", description: "仅支持 2.4GHz Wi-Fi" },
      { number: 4, title: "完成绑定", description: "设备归属当前家庭" }
    ],
    deviceCode: "",
    wifiSsid: "",
    wifiPassword: "",
    showPassword: false,
    binding: false,
    progressText: "",
    errorText: "",
    codeWarning: "",
    success: false,
    devices: [],
    entryResolving: false,
    entryBlocked: false,
    entryMessage: ""
  },

  onLoad(options) {
    if (!options.scene) {
      return;
    }
    let scene = options.scene;
    try {
      scene = decodeURIComponent(scene);
    } catch (error) {
      this.setData({
        entryBlocked: true,
        entryMessage: "设备码格式不正确，请检查设备标签"
      });
      return;
    }
    const deviceCode = scene.startsWith("device_code=")
      ? scene.slice("device_code=".length)
      : scene;
    this.entryDeviceCode = deviceCode;
    this.setData({
      deviceCode,
      entryResolving: true,
      entryMessage: "正在识别设备…"
    });
    this.resolveScannedDevice();
  },

  onShow() {
    if (!this.entryDeviceCode) {
      this.loadDevices();
    }
  },

  onUnload() {
    closeProvisioningDevice(this.bleDeviceId);
  },

  updateField(event) {
    this.setData({ [event.currentTarget.dataset.field]: event.detail.value });
  },

  togglePassword() {
    this.setData({ showPassword: !this.data.showPassword });
  },

  setProgress(progressText) {
    this.setData({ progressText, errorText: "" });
  },

  async resolveScannedDevice() {
    const deviceCode = this.entryDeviceCode;
    if (!deviceCode) {
      return;
    }
    this.setData({
      entryResolving: true,
      entryBlocked: false,
      entryMessage: "正在识别设备…"
    });
    try {
      const entry = await request({
        path: `/v1/devices/${encodeURIComponent(deviceCode)}/entry`
      });
      if (entry.state === "accessible") {
        this.setData({ entryMessage: "正在打开对应冰箱…" });
        const app = getApp();
        if (entry.household_id !== app.globalData.currentHouseholdId) {
          const session = await request({
            path: "/v1/me/current-household",
            method: "POST",
            data: { household_id: entry.household_id }
          });
          app.applySession(session);
        }
        await openTodayPage();
        return;
      }
      if (entry.state === "unavailable") {
        this.setData({
          entryResolving: false,
          entryBlocked: true,
          entryMessage:
            "这台墨水屏已绑定到其他家庭。请让家庭管理员发送邀请码，加入对应家庭后再扫码。"
        });
        return;
      }
      this.setData({
        entryResolving: false,
        entryBlocked: false,
        entryMessage: ""
      });
      await this.loadDevices();
    } catch (error) {
      const notFound = Number(error && error.statusCode) === 404;
      this.setData({
        entryResolving: false,
        entryBlocked: true,
        entryMessage: notFound
          ? "设备码无效或该设备尚未登记，请检查设备标签。"
          : "暂时无法读取设备信息，请检查网络后重试。"
      });
    }
  },

  retryDeviceEntry() {
    this.resolveScannedDevice();
  },

  async goToToday() {
    try {
      await openTodayPage();
    } catch (error) {
      wx.showToast({ title: "页面打开失败，请重试", icon: "none" });
    }
  },

  async loadDevices() {
    try {
      const devices = await request({
        path: "/devices",
        householdScoped: true
      });
      this.setData({ devices });
    } catch (error) {
      // The binding form remains usable; submit will surface auth errors.
    }
  },

  async unbindDevice(event) {
    const deviceCode = event.currentTarget.dataset.code;
    const confirmed = await new Promise((resolve) => {
      wx.showModal({
        title: "解除绑定",
        content: `确认将设备 ${deviceCode} 从当前家庭移除？`,
        confirmColor: "#b8352d",
        success: (result) => resolve(result.confirm),
        fail: () => resolve(false)
      });
    });
    if (!confirmed) {
      return;
    }
    try {
      await request({
        path: `/devices/${deviceCode}/unbind`,
        method: "POST",
        householdScoped: true
      });
      await this.loadDevices();
      wx.showToast({ title: "已解除绑定", icon: "success" });
    } catch (error) {
      wx.showToast({ title: errorMessage(error), icon: "none" });
    }
  },

  async refreshMiniProgramCode(event) {
    const deviceCode = event.currentTarget.dataset.code;
    wx.showLoading({ title: "正在生成" });
    try {
      await request({
        path: `/devices/${deviceCode}/mini-program-code`,
        method: "POST",
        householdScoped: true
      });
      await this.loadDevices();
      this.setData({ codeWarning: "" });
      wx.showToast({ title: "小程序码已更新", icon: "success" });
    } catch (error) {
      const message = errorMessage(error);
      this.setData({
        codeWarning: `小程序码生成失败：${message}`
      });
      wx.showToast({ title: message, icon: "none" });
    } finally {
      wx.hideLoading();
    }
  },

  async pollCompletion(sessionId) {
    for (let attempt = 0; attempt < 45; attempt += 1) {
      const session = await request({
        path: `/devices/provisioning-sessions/${sessionId}`,
        householdScoped: true
      });
      if (session.status === "completed") {
        return;
      }
      if (["expired", "cancelled"].includes(session.status)) {
        throw new Error("配网会话已失效，请重新开始");
      }
      await wait(2000);
    }
    throw new Error("设备联网超时，请确认 Wi-Fi 密码和信号");
  },

  async startBinding() {
    if (this.data.binding) {
      return;
    }
    const deviceCode = this.data.deviceCode.trim();
    const wifiSsid = this.data.wifiSsid.trim();
    if (!deviceCode || !wifiSsid) {
      wx.showToast({ title: "请填写设备编号和 Wi-Fi 名称", icon: "none" });
      return;
    }
    this.setData({
      binding: true,
      success: false,
      errorText: "",
      codeWarning: "",
      progressText: "准备配网…"
    });
    try {
      const device = await openProvisioningDevice(
        deviceCode,
        (message) => this.setProgress(message)
      );
      this.bleDeviceId = device.deviceId;
      this.setProgress("正在安全封装 Wi-Fi 配置…");
      const session = await request({
        path: "/devices/provisioning-sessions",
        method: "POST",
        householdScoped: true,
        data: {
          device_code: device.deviceCode,
          challenge: device.challenge,
          wifi_ssid: wifiSsid,
          wifi_password: this.data.wifiPassword
        }
      });
      this.setProgress("正在通过蓝牙发送配置…");
      await transmitPayload(
        device,
        session.encrypted_payload,
        session.payload_sha256
      );
      this.setProgress("设备正在连接 2.4GHz Wi-Fi…");
      await this.pollCompletion(session.id);
      this.setProgress("正在生成设备小程序码…");
      let codeWarning = "";
      try {
        await request({
          path: `/devices/${device.deviceCode}/mini-program-code`,
          method: "POST",
          householdScoped: true
        });
      } catch (error) {
        codeWarning =
          `设备已绑定，但小程序码生成失败：${errorMessage(error)}。`
          + "请完善微信配置后点击“更新码”。";
      }
      this.setData({
        success: true,
        codeWarning,
        progressText: "绑定成功，设备将在下一轮询刷新画面",
        wifiPassword: ""
      });
      wx.showToast({ title: "绑定成功", icon: "success" });
      await this.loadDevices();
    } catch (error) {
      this.setData({
        errorText: errorMessage(error),
        progressText: ""
      });
    } finally {
      await closeProvisioningDevice(this.bleDeviceId);
      this.bleDeviceId = null;
      this.setData({ binding: false });
    }
  }
});
