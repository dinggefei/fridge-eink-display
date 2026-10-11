const { request } = require("../../utils/request");

const REFRESH_OPTIONS = [
  { label: "每 15 分钟", value: 15 },
  { label: "每 30 分钟", value: 30 },
  { label: "每 60 分钟", value: 60 }
];

const TYPE_LABELS = {
  crypto: "数字货币",
  us_stock: "美股",
  cn_stock: "A 股",
  hk_stock: "港股",
  index: "指数"
};

const SEARCH_TYPES = [
  { label: "数字货币", value: "crypto", placeholder: "搜索 BTC、ETH、Solana…" },
  { label: "美股", value: "us_stock", placeholder: "搜索代码或公司名称" },
  { label: "A 股", value: "cn_stock", placeholder: "搜索 600519 或贵州茅台" },
  { label: "港股", value: "hk_stock", placeholder: "搜索 00700 或腾讯" }
];

function errorText(error, fallback) {
  if (error && error.data && error.data.detail) {
    return error.data.detail;
  }
  return fallback;
}

function priceText(asset) {
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

function displayAsset(asset) {
  const change = asset.change_percent;
  const changeNumber = change === null || change === undefined
    ? null
    : Number(change);
  return {
    ...asset,
    typeLabel: TYPE_LABELS[asset.asset_type] || asset.asset_type,
    priceText: priceText(asset),
    changeText: changeNumber === null
      ? "--"
      : `${changeNumber > 0 ? "+" : ""}${changeNumber.toFixed(2)}%`,
    changeClass: changeNumber > 0 ? "change-up" : "change-down"
  };
}

Page({
  data: {
    loading: true,
    saving: false,
    searching: false,
    refreshOptions: REFRESH_OPTIONS,
    refreshIndex: 1,
    nightPause: true,
    assets: [],
    catalog: [],
    indexOptions: [],
    searchTypes: SEARCH_TYPES,
    searchType: SEARCH_TYPES[0].value,
    searchPlaceholder: SEARCH_TYPES[0].placeholder,
    searchQuery: "",
    searchPerformed: false,
    searchResults: [],
    maxAssets: 6,
    displayMode: "inventory",
    sourceLabel: "",
    disclaimer: "行情仅供参考",
    errorMessage: ""
  },

  onShow() {
    this.loadDashboard();
  },

  async loadDashboard() {
    this.setData({ loading: true, errorMessage: "" });
    try {
      const dashboard = await request({
        path: "/display-market",
        householdScoped: true
      });
      this.applyDashboard(dashboard);
    } catch (error) {
      this.setData({
        loading: false,
        errorMessage: "无法加载行情看板"
      });
    }
  },

  applyDashboard(dashboard) {
    const selectedKeys = new Set(
      (dashboard.assets || []).map((item) => `${item.asset_type}:${item.symbol}`)
    );
    const catalog = (dashboard.catalog || []).map((item) => ({
      ...item,
      typeLabel: TYPE_LABELS[item.asset_type] || item.asset_type,
      label: `${TYPE_LABELS[item.asset_type] || item.asset_type} · ${item.name} (${item.symbol})`,
      selected: selectedKeys.has(`${item.asset_type}:${item.symbol}`)
    }));
    const searchResults = (this.data.searchResults || []).map((item) => ({
      ...item,
      selected: selectedKeys.has(`${item.asset_type}:${item.symbol}`)
    }));
    const refreshIndex = Math.max(
      0,
      REFRESH_OPTIONS.findIndex(
        (option) => option.value === dashboard.refresh_minutes
      )
    );
    this.setData({
      loading: false,
      saving: false,
      refreshIndex,
      nightPause: dashboard.night_pause,
      assets: (dashboard.assets || []).map(displayAsset),
      catalog,
      indexOptions: catalog.filter((item) => item.asset_type === "index"),
      searchResults,
      maxAssets: dashboard.max_assets || 6,
      displayMode: dashboard.display_mode,
      sourceLabel: dashboard.source_label || "",
      disclaimer: dashboard.disclaimer || "行情仅供参考",
      errorMessage: ""
    });
  },

  async saveDashboard(data, successTitle) {
    if (this.data.saving) {
      return;
    }
    this.setData({ saving: true });
    try {
      const dashboard = await request({
        path: "/display-market",
        method: "PUT",
        householdScoped: true,
        data
      });
      this.applyDashboard(dashboard);
      if (successTitle) {
        wx.showToast({ title: successTitle });
      }
    } catch (error) {
      this.setData({ saving: false });
      wx.showToast({
        title: errorText(error, "保存行情设置失败"),
        icon: "none"
      });
      await this.loadDashboard();
    }
  },

  onRefreshChange(event) {
    const index = Number(event.detail.value);
    const minutes = REFRESH_OPTIONS[index].value;
    this.setData({ refreshIndex: index });
    this.saveDashboard({ refresh_minutes: minutes }, "刷新周期已保存");
  },

  onNightPauseChange(event) {
    const nightPause = Boolean(event.detail.value);
    this.setData({ nightPause });
    this.saveDashboard({ night_pause: nightPause }, "夜间设置已保存");
  },

  onSearchTypeTap(event) {
    const searchType = event.currentTarget.dataset.value;
    const selected = SEARCH_TYPES.find((item) => item.value === searchType);
    if (!selected || searchType === this.data.searchType) {
      return;
    }
    this.setData({
      searchType,
      searchPlaceholder: selected.placeholder,
      searchQuery: "",
      searchPerformed: false,
      searchResults: []
    });
  },

  onSearchInput(event) {
    this.setData({
      searchQuery: event.detail.value,
      searchPerformed: false
    });
  },

  async searchAssets() {
    const query = this.data.searchQuery.trim();
    if (!query) {
      wx.showToast({ title: "请输入代码或名称", icon: "none" });
      return;
    }
    if (this.data.searching) {
      return;
    }
    this.setData({
      searching: true,
      searchPerformed: false,
      searchResults: []
    });
    try {
      const results = await request({
        path: "/display-market/search",
        householdScoped: true,
        data: {
          asset_type: this.data.searchType,
          query
        }
      });
      const selectedKeys = new Set(
        this.data.assets.map((item) => `${item.asset_type}:${item.symbol}`)
      );
      this.setData({
        searching: false,
        searchPerformed: true,
        searchResults: (results || []).map((item) => ({
          ...item,
          key: `${item.asset_type}:${item.provider_symbol}`,
          typeLabel: TYPE_LABELS[item.asset_type] || item.asset_type,
          selected: selectedKeys.has(`${item.asset_type}:${item.symbol}`)
        }))
      });
    } catch (error) {
      this.setData({ searching: false, searchPerformed: true });
      wx.showToast({
        title: errorText(error, "搜索行情失败"),
        icon: "none"
      });
    }
  },

  async addSearchResult(event) {
    if (this.data.assets.length >= this.data.maxAssets) {
      wx.showToast({ title: `最多展示 ${this.data.maxAssets} 项`, icon: "none" });
      return;
    }
    const key = event.currentTarget.dataset.key;
    const item = this.data.searchResults.find((result) => result.key === key);
    if (!item || item.selected || this.data.saving) {
      return;
    }
    this.setData({ saving: true });
    try {
      const dashboard = await request({
        path: "/display-market/assets",
        method: "POST",
        householdScoped: true,
        data: {
          asset_type: item.asset_type,
          provider_symbol: item.provider_symbol
        }
      });
      this.applyDashboard(dashboard);
      wx.showToast({ title: "已添加" });
    } catch (error) {
      this.setData({ saving: false });
      wx.showToast({
        title: errorText(error, "添加资产失败"),
        icon: "none"
      });
    }
  },

  addIndexAsset(event) {
    if (this.data.assets.length >= this.data.maxAssets) {
      wx.showToast({ title: `最多展示 ${this.data.maxAssets} 项`, icon: "none" });
      return;
    }
    const symbol = event.currentTarget.dataset.symbol;
    const item = this.data.indexOptions.find((option) => option.symbol === symbol);
    if (!item || item.selected) {
      return;
    }
    const assets = [
      ...this.data.assets.map((asset) => ({
        asset_type: asset.asset_type,
        symbol: asset.symbol
      })),
      { asset_type: item.asset_type, symbol: item.symbol }
    ];
    this.saveDashboard({ assets }, "已添加");
  },

  async removeAsset(event) {
    const assetId = event.currentTarget.dataset.id;
    const asset = this.data.assets.find((item) => item.id === assetId);
    if (!asset || this.data.saving) {
      return;
    }
    const modal = await new Promise((resolve) => {
      wx.showModal({
        title: `删除 ${asset.name}`,
        content: "删除后将不再在水墨屏行情列表中展示。",
        confirmText: "删除",
        confirmColor: "#c42b25",
        success: resolve,
        fail: () => resolve({ confirm: false })
      });
    });
    if (!modal.confirm) {
      return;
    }
    this.setData({ saving: true });
    try {
      const dashboard = await request({
        path: `/display-market/assets/${assetId}`,
        method: "DELETE",
        householdScoped: true
      });
      this.applyDashboard(dashboard);
      wx.showToast({ title: "已删除" });
    } catch (error) {
      this.setData({ saving: false });
      wx.showToast({
        title: errorText(error, "删除资产失败"),
        icon: "none"
      });
    }
  },

  moveAsset(event) {
    const assetId = event.currentTarget.dataset.id;
    const direction = Number(event.currentTarget.dataset.direction);
    const assets = [...this.data.assets];
    const index = assets.findIndex((asset) => asset.id === assetId);
    const target = index + direction;
    if (index < 0 || target < 0 || target >= assets.length) {
      return;
    }
    [assets[index], assets[target]] = [assets[target], assets[index]];
    this.saveDashboard({
      assets: assets.map((asset) => ({
        asset_type: asset.asset_type,
        symbol: asset.symbol
      }))
    });
  },

  async activateMarket() {
    if (this.data.assets.length === 0) {
      wx.showToast({ title: "请先添加至少一项资产", icon: "none" });
      return;
    }
    try {
      await request({
        path: "/display-settings",
        method: "PUT",
        householdScoped: true,
        data: { display_mode: "market" }
      });
      this.setData({ displayMode: "market" });
      wx.showToast({ title: "已设为当前显示" });
    } catch (error) {
      wx.showToast({
        title: errorText(error, "启用行情看板失败"),
        icon: "none"
      });
    }
  }
});
