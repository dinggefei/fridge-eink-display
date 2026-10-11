const { request } = require("../../utils/request");

Page({
  data: {
    enabled: true,
    reminderTime: "20:00",
    thresholdDays: 3,
    thresholdOptions: [1, 2, 3, 4, 5, 6, 7],
    subscriptionGrants: 0,
    deliveryMode: "disabled",
    templateId: "",
    deliveryCounts: {},
    loading: true
  },

  onShow() {
    this.loadPreference();
  },

  async loadPreference() {
    try {
      const value = await request({
        path: "/reminders",
        householdScoped: true
      });
      this.setData({
        enabled: value.enabled,
        reminderTime: value.reminder_time,
        thresholdDays: value.threshold_days,
        subscriptionGrants: value.subscription_grants,
        deliveryMode: value.delivery_mode,
        templateId: value.template_id,
        deliveryCounts: value.delivery_counts || {}
      });
    } catch (error) {
      wx.showToast({ title: "提醒设置加载失败", icon: "none" });
    } finally {
      this.setData({ loading: false });
    }
  },

  onEnabledChange(event) {
    this.setData({ enabled: event.detail.value });
  },

  onTimeChange(event) {
    this.setData({ reminderTime: event.detail.value });
  },

  onThresholdChange(event) {
    this.setData({
      thresholdDays: this.data.thresholdOptions[Number(event.detail.value)]
    });
  },

  async savePreference() {
    try {
      const value = await request({
        path: "/reminders",
        householdScoped: true,
        method: "PUT",
        data: {
          enabled: this.data.enabled,
          reminder_time: this.data.reminderTime,
          threshold_days: this.data.thresholdDays
        }
      });
      this.setData({
        enabled: value.enabled,
        reminderTime: value.reminder_time,
        thresholdDays: value.threshold_days
      });
      wx.showToast({ title: "设置已保存", icon: "success" });
    } catch (error) {
      wx.showToast({ title: "保存失败", icon: "none" });
    }
  },

  async addGrant() {
    if (this.data.deliveryMode === "disabled") {
      wx.showModal({
        title: "订阅模板待配置",
        content:
          "当前已完成提醒设置与发送逻辑。待微信公众平台审核通过订阅模板后，即可在这里授权真实提醒。",
        showCancel: false
      });
      return;
    }

    if (this.data.deliveryMode === "wechat") {
      try {
        const result = await new Promise((resolve, reject) => {
          wx.requestSubscribeMessage({
            tmplIds: [this.data.templateId],
            success: resolve,
            fail: reject
          });
        });
        if (result[this.data.templateId] !== "accept") {
          wx.showToast({ title: "未获得本次提醒授权", icon: "none" });
          return;
        }
      } catch (error) {
        wx.showToast({ title: "订阅授权失败", icon: "none" });
        return;
      }
    }

    try {
      const result = await request({
        path: "/reminders/subscription-grants",
        householdScoped: true,
        method: "POST"
      });
      this.setData({ subscriptionGrants: result.subscription_grants });
      wx.showToast({ title: "已增加一次提醒", icon: "success" });
    } catch (error) {
      wx.showToast({ title: "授权记录失败", icon: "none" });
    }
  }
});
