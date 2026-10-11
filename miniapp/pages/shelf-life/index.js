const { request } = require("../../utils/request");

const LOCATIONS = [
  { label: "冷藏", value: "refrigerated" },
  { label: "冷冻", value: "frozen" },
  { label: "常温", value: "room_temperature" }
];

Page({
  data: {
    rules: [],
    isAdmin: false,
    locationOptions: LOCATIONS,
    locationIndex: 0,
    foodName: "",
    suggestedDays: "3"
  },

  onShow() {
    this.loadRules();
  },

  async loadRules() {
    try {
      await getApp().ensureAuthenticated();
      const household = getApp().globalData.households.find(
        (item) => item.id === getApp().globalData.currentHouseholdId
      );
      const rules = await request({
        path: "/shelf-life-rules",
        householdScoped: true
      });
      this.setData({
        isAdmin: household && household.role === "admin",
        rules: rules.map((rule) => ({
          ...rule,
          locationLabel:
            (LOCATIONS.find((item) => item.value === rule.location) || {}).label
              || rule.location
        }))
      });
    } catch (error) {
      wx.showToast({ title: "规则加载失败", icon: "none" });
    }
  },

  onInput(event) {
    this.setData({ [event.currentTarget.dataset.field]: event.detail.value });
  },

  onLocationChange(event) {
    this.setData({ locationIndex: Number(event.detail.value) });
  },

  async saveRule() {
    const foodName = this.data.foodName.trim();
    const days = Number(this.data.suggestedDays);
    if (!foodName || !Number.isInteger(days) || days < 0) {
      wx.showToast({ title: "请填写食材名称和有效天数", icon: "none" });
      return;
    }
    try {
      await request({
        path: "/shelf-life-rules",
        householdScoped: true,
        method: "POST",
        data: {
          food_name: foodName,
          location: LOCATIONS[this.data.locationIndex].value,
          suggested_days: days
        }
      });
      this.setData({ foodName: "", suggestedDays: "3" });
      await this.loadRules();
      wx.showToast({ title: "规则已保存", icon: "success" });
    } catch (error) {
      wx.showToast({ title: "规则保存失败", icon: "none" });
    }
  },

  deleteRule(event) {
    const rule = event.currentTarget.dataset.rule;
    wx.showModal({
      title: "删除保鲜规则",
      content: `确认删除“${rule.food_name} · ${rule.locationLabel}”？`,
      success: async (result) => {
        if (!result.confirm) return;
        try {
          await request({
            path: `/shelf-life-rules/${rule.id}`,
            householdScoped: true,
            method: "DELETE"
          });
          await this.loadRules();
        } catch (error) {
          wx.showToast({ title: "删除失败", icon: "none" });
        }
      }
    });
  }
});
