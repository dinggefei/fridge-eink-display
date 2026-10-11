const { request, downloadFile } = require("../../utils/request");

const DISPLAY_MODES = [
  {
    value: "inventory",
    title: "食材管理",
    description: "显示食材、待办、小程序码和更新时间"
  },
  {
    value: "almanac",
    title: "完整简版黄历",
    description: "全屏显示农历、宜忌、冲煞、节气和可选天气"
  },
  {
    value: "weather",
    title: "天气预报",
    description: "全屏显示今天和未来六天天气，每 3 小时更新"
  },
  {
    value: "timetable",
    title: "课程表",
    description: "竖屏显示三日课程，横屏显示一周课程"
  },
  {
    value: "market",
    title: "行情看板",
    description: "全屏显示数字货币、美股、A 股、港股和指数行情"
  },
  {
    value: "album",
    title: "独立相册",
    description: "全屏轮播家庭照片，不显示其他信息"
  }
];

function errorText(error, fallback) {
  if (error && error.data && error.data.detail) {
    return error.data.detail;
  }
  return fallback;
}

function previewStatusClass(status) {
  if (status === "overdue" || status === "eat_today") {
    return "preview-status-red";
  }
  if (status === "eat_soon") {
    return "preview-status-yellow";
  }
  return "preview-status-black";
}

function marketPriceText(asset) {
  if (asset.price === null || asset.price === undefined) {
    return "--";
  }
  const number = Number(asset.price);
  const prefix = { USD: "$", CNY: "¥", HKD: "HK$" }[asset.currency] || `${asset.currency} `;
  const digits = Math.abs(number) < 1 ? 4 : 2;
  return `${prefix}${number.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits
  })}`;
}

function marketPreviewAsset(asset) {
  const changeNumber = asset.change_percent === null || asset.change_percent === undefined
    ? null
    : Number(asset.change_percent);
  return {
    ...asset,
    priceText: marketPriceText(asset),
    changeText: changeNumber === null
      ? "--"
      : `${changeNumber > 0 ? "+" : ""}${changeNumber.toFixed(2)}%`,
    changeClass: changeNumber > 0 ? "market-change-up" : "market-change-down"
  };
}

Page({
  data: {
    loading: true,
    saving: false,
    scopeOptions: [{ label: "家庭默认（所有未单独设置的设备）", deviceCode: "" }],
    scopeIndex: 0,
    selectedDeviceCode: "",
    inheritsHousehold: true,
    householdDisplayMode: "inventory",
    modes: DISPLAY_MODES,
    displayMode: "inventory",
    selectedMode: "inventory",
    albumReady: false,
    marketReady: false,
    timetableReady: false,
    timetableOrientation: "portrait",
    almanac: null,
    inventoryPreviewLoading: true,
    inventoryPreviewItems: [],
    inventoryPreviewTodos: [],
    inventoryPreviewHiddenCount: 0,
    marketPreviewLoading: true,
    marketPreviewAssets: [],
    marketRefreshMinutes: 30,
    marketSourceLabel: "",
    weatherEnabled: false,
    weatherProviderReady: false,
    weatherLocation: null,
    weather: null,
    weatherSourceName: "和风天气",
    weatherSourceUrl: "https://www.qweather.com",
    weatherQuery: "",
    weatherSearching: false,
    weatherLocations: [],
    weatherSaving: false,
    weatherPreviewPath: "",
    weatherPreviewLoading: false,
    weatherPreviewError: "",
    timetablePreviewPath: "",
    timetablePreviewLoading: false,
    timetablePreviewError: "",
    errorMessage: ""
  },

  onShow() {
    this.weatherPreviewGeneration = (this.weatherPreviewGeneration || 0) + 1;
    this.setData({
      weatherPreviewPath: "",
      weatherPreviewError: "",
      timetablePreviewPath: "",
      timetablePreviewError: ""
    });
    this.loadSettings();
  },

  onHide() {
    this.weatherPreviewGeneration = (this.weatherPreviewGeneration || 0) + 1;
  },

  async loadSettings() {
    this.setData({ loading: true, errorMessage: "" });
    try {
      const devices = await request({
        path: "/devices",
        householdScoped: true
      });
      const scopeOptions = [
        { label: "家庭默认（所有未单独设置的设备）", deviceCode: "" },
        ...devices.map((device) => ({
          label: `${device.panel_model === "Kindle-Paperwhite-3" ? "Kindle PW3" : "ESP32 墨水屏"} · ${device.device_code}`,
          deviceCode: device.device_code
        }))
      ];
      let scopeIndex = scopeOptions.findIndex(
        (item) => item.deviceCode === this.data.selectedDeviceCode
      );
      if (scopeIndex < 0) scopeIndex = 0;
      const selectedDeviceCode = scopeOptions[scopeIndex].deviceCode;
      this.setData({ scopeOptions, scopeIndex, selectedDeviceCode });
      const settings = await request({
        path: this.settingsPath(selectedDeviceCode),
        householdScoped: true
      });
      this.applySettings(settings);
      await Promise.all([
        this.loadInventoryPreview(),
        this.loadMarketPreview()
      ]);
    } catch (error) {
      this.setData({
        loading: false,
        errorMessage: "无法加载水墨屏显示设置"
      });
    }
  },

  applySettings(settings) {
    this.setData({
      loading: false,
      saving: false,
      displayMode: settings.display_mode,
      selectedMode: settings.display_mode,
      inheritsHousehold: settings.inherits_household,
      householdDisplayMode: settings.household_display_mode,
      modes: DISPLAY_MODES.filter((mode) => (
        (mode.value !== "weather" || settings.weather_mode_available) &&
        (mode.value !== "timetable" || settings.timetable_mode_available)
      )),
      albumReady: settings.album_ready,
      marketReady: settings.market_ready,
      timetableReady: settings.timetable_ready,
      timetableOrientation: settings.timetable_orientation || "portrait",
      almanac: settings.almanac,
      weatherEnabled: settings.weather_enabled,
      weatherProviderReady: settings.weather_provider_ready,
      weatherLocation: settings.weather_location,
      weather: settings.weather,
      weatherSourceName: settings.weather_source_name || "和风天气",
      weatherSourceUrl: settings.weather_source_url || "https://www.qweather.com",
      weatherSaving: false,
      errorMessage: ""
    });
    if (settings.display_mode === "weather") this.loadWeatherPreview();
    if (settings.display_mode === "timetable") this.loadTimetablePreview();
  },

  settingsPath(deviceCode = this.data.selectedDeviceCode) {
    if (!deviceCode) return "/display-settings";
    return `/display-settings?device_code=${encodeURIComponent(deviceCode)}`;
  },

  onScopeChange(event) {
    const scopeIndex = Number(event.detail.value);
    const selectedDeviceCode = this.data.scopeOptions[scopeIndex].deviceCode;
    this.setData({ scopeIndex, selectedDeviceCode });
    this.loadSettings();
  },

  async followHouseholdDefault() {
    if (!this.data.selectedDeviceCode || this.data.saving) return;
    this.setData({ saving: true });
    try {
      const settings = await request({
        path: this.settingsPath(),
        method: "PUT",
        householdScoped: true,
        data: { display_mode: null }
      });
      this.applySettings(settings);
      wx.showToast({ title: "已跟随家庭默认" });
    } catch (error) {
      this.setData({ saving: false });
      wx.showToast({ title: errorText(error, "更新失败"), icon: "none" });
    }
  },

  async loadTimetablePreview() {
    this.setData({ timetablePreviewLoading: true, timetablePreviewError: "", timetablePreviewPath: "" });
    try {
      const timetablePreviewPath = await downloadFile({
        path: "/display-timetable/preview",
        householdScoped: true
      });
      this.setData({ timetablePreviewPath, timetablePreviewLoading: false });
    } catch (error) {
      this.setData({ timetablePreviewLoading: false, timetablePreviewError: "课程表预览加载失败" });
    }
  },

  onTimetablePreviewError() {
    this.setData({ timetablePreviewPath: "", timetablePreviewError: "课程表预览加载失败" });
  },

  async loadWeatherPreview() {
    const generation = (this.weatherPreviewGeneration || 0) + 1;
    this.weatherPreviewGeneration = generation;
    this.setData({ weatherPreviewLoading: true, weatherPreviewError: "", weatherPreviewPath: "" });
    try {
      const path = await downloadFile({ path: "/display-settings/weather-preview", householdScoped: true });
      if (generation !== this.weatherPreviewGeneration) return;
      this.setData({ weatherPreviewPath: path, weatherPreviewLoading: false });
    } catch (error) {
      if (generation !== this.weatherPreviewGeneration) return;
      this.setData({ weatherPreviewLoading: false, weatherPreviewError: "天气预览加载失败，请重试" });
    }
  },

  onWeatherPreviewError() {
    this.setData({ weatherPreviewPath: "", weatherPreviewError: "天气预览加载失败，请重试" });
  },

  async loadInventoryPreview() {
    this.setData({ inventoryPreviewLoading: true });
    try {
      const [inventory, todos] = await Promise.all([
        request({ path: "/inventory", householdScoped: true }),
        request({
          path: "/inventory/settings/display-todos",
          householdScoped: true
        })
      ]);
      const allItems = inventory.items || [];
      this.setData({
        inventoryPreviewLoading: false,
        inventoryPreviewItems: allItems.slice(0, 8).map((item) => ({
          id: item.id,
          name: item.name,
          quantityText: item.quantity_text,
          statusText: item.status_text,
          statusClass: previewStatusClass(item.status)
        })),
        inventoryPreviewTodos: (todos.items || []).slice(0, 3),
        inventoryPreviewHiddenCount: Math.max(0, allItems.length - 8)
      });
    } catch (error) {
      this.setData({
        inventoryPreviewLoading: false,
        inventoryPreviewItems: [],
        inventoryPreviewTodos: [],
        inventoryPreviewHiddenCount: 0
      });
    }
  },

  async loadMarketPreview() {
    this.setData({ marketPreviewLoading: true });
    try {
      const dashboard = await request({
        path: "/display-market",
        householdScoped: true
      });
      this.setData({
        marketPreviewLoading: false,
        marketPreviewAssets: (dashboard.assets || []).map(marketPreviewAsset),
        marketRefreshMinutes: dashboard.refresh_minutes || 30,
        marketSourceLabel: dashboard.source_label || ""
      });
    } catch (error) {
      this.setData({
        marketPreviewLoading: false,
        marketPreviewAssets: [],
        marketSourceLabel: ""
      });
    }
  },

  onSelectMode(event) {
    const mode = event.currentTarget.dataset.mode;
    if (this.data.saving || this.data.weatherSaving || mode === this.data.selectedMode) {
      return;
    }
    if (mode === "weather" && !this.data.weatherProviderReady) {
      wx.showToast({ title: "天气服务未配置，未切换", icon: "none" });
      return;
    }
    this.setData({ selectedMode: mode });
    if (mode === "weather" && !this.data.weatherLocation) {
      wx.showToast({ title: "请先搜索并选择城市", icon: "none" });
      return;
    }
    if (mode === "album" && !this.data.albumReady) {
      return;
    }
    if (mode === "market" && !this.data.marketReady) {
      return;
    }
    if (mode === "timetable" && !this.data.timetableReady) {
      this.loadTimetablePreview();
      return;
    }
    this.saveMode(mode);
  },

  async saveMode(mode) {
    this.setData({ saving: true });
    try {
      const settings = await request({
        path: this.settingsPath(),
        method: "PUT",
        householdScoped: true,
        data: { display_mode: mode }
      });
      this.applySettings(settings);
      wx.showToast({ title: "显示模式已更新" });
    } catch (error) {
      this.setData({
        saving: false,
        selectedMode: this.data.displayMode
      });
      wx.showToast({
        title: errorText(error, "更新显示模式失败"),
        icon: "none"
      });
    }
  },

  onWeatherQueryInput(event) {
    this.setData({ weatherQuery: event.detail.value });
  },

  async searchWeatherLocations() {
    const query = (this.data.weatherQuery || "").trim();
    if (query.length < 2) {
      wx.showToast({ title: "请输入至少两个字", icon: "none" });
      return;
    }
    this.setData({ weatherSearching: true, weatherLocations: [] });
    try {
      const locations = await request({
        path: "/display-settings/weather-locations",
        householdScoped: true,
        data: { query }
      });
      this.setData({
        weatherSearching: false,
        weatherLocations: locations || []
      });
      if (!locations || locations.length === 0) {
        wx.showToast({ title: "没有找到这个城市", icon: "none" });
      }
    } catch (error) {
      this.setData({ weatherSearching: false });
      wx.showToast({
        title: errorText(error, "城市搜索失败"),
        icon: "none"
      });
    }
  },

  onSelectWeatherLocation(event) {
    const index = Number(event.currentTarget.dataset.index);
    const location = this.data.weatherLocations[index];
    if (!location) {
      return;
    }
    this.saveWeatherSettings(this.data.selectedMode === "weather" ? null : true, location);
  },

  onWeatherToggle(event) {
    const enabled = Boolean(event.detail.value);
    if (enabled && !this.data.weatherLocation) {
      this.setData({ weatherEnabled: false });
      wx.showToast({ title: "请先搜索并选择城市", icon: "none" });
      return;
    }
    this.saveWeatherSettings(enabled, this.data.weatherLocation);
  },

  async saveWeatherSettings(enabled, location) {
    if (this.data.weatherSaving || this.data.saving) return;
    const selectedMode = this.data.selectedMode;
    this.setData({ weatherSaving: true });
    try {
      const settings = await request({
        path: "/display-settings/weather",
        method: "PUT",
        householdScoped: true,
        data: {
          enabled,
          location: location || null
        }
      });
      this.applySettings(settings);
      this.setData({ selectedMode });
      this.setData({
        weatherSaving: false,
        weatherQuery: "",
        weatherLocations: []
      });
      if (selectedMode === "weather") {
        if (settings.display_mode !== "weather") await this.saveMode("weather");
      } else {
        wx.showToast({ title: enabled ? "天气已显示" : "天气已关闭" });
      }
    } catch (error) {
      this.setData({
        weatherSaving: false,
        weatherEnabled: this.data.weatherEnabled
      });
      wx.showToast({
        title: errorText(error, "天气设置保存失败"),
        icon: "none"
      });
    }
  },

  copyWeatherSource() {
    wx.setClipboardData({
      data: this.data.weatherSourceUrl,
      success() {
        wx.showToast({ title: "服务网址已复制" });
      }
    });
  },

  goToAlbum() {
    wx.navigateTo({ url: "/pages/display-album/index" });
  },

  goToMarket() {
    wx.navigateTo({ url: "/pages/display-market/index" });
  },

  goToTimetable() {
    wx.navigateTo({ url: "/pages/display-timetable/index" });
  },

  goToTodo() {
    wx.navigateTo({ url: "/pages/todo/index" });
  }
});
