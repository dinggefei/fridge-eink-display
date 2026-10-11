const { request } = require("../../utils/request");

Page({
  data: {
    householdName: "我的冰箱",
    memberCount: 1,
    deviceStatus: "待绑定",
    nickname: "正在登录…",
    errorMessage: ""
  },

  onShow() {
    this.loadProfile();
  },

  async loadProfile() {
    try {
      const session = await request({ path: "/v1/me" });
      const household = session.households.find(
        (item) => item.id === session.current_household_id
      );
      this.setData({
        nickname: session.user.nickname || "微信用户",
        householdName: household ? household.name : "我的冰箱",
        memberCount: household ? household.member_count : 1,
        errorMessage: ""
      });
      const devices = await request({
        path: "/devices",
        householdScoped: true
      });
      const online = devices.filter((item) => item.status === "online").length;
      this.setData({
        deviceStatus:
          devices.length === 0
            ? "待绑定"
            : online > 0
              ? `${online} 台在线`
              : `${devices.length} 台离线`
      });
    } catch (error) {
      this.setData({
        nickname: "登录失败",
        errorMessage: "请确认后端服务和登录配置"
      });
    }
  },

  goToDevice() {
    wx.navigateTo({ url: "/pages/device/index" });
  },

  goToHousehold() {
    wx.navigateTo({ url: "/pages/household/index" });
  },

  goToReminder() {
    wx.navigateTo({ url: "/pages/reminder/index" });
  },

  goToRecognitionHistory() {
    wx.navigateTo({ url: "/pages/recognition-history/index" });
  },

  goToShelfLife() {
    wx.navigateTo({ url: "/pages/shelf-life/index" });
  },

  goToDisplaySettings() {
    wx.navigateTo({ url: "/pages/display-settings/index" });
  },

  goToPrivacyData() {
    wx.navigateTo({ url: "/pages/privacy-data/index" });
  }
});
