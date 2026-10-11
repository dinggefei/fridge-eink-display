const { request } = require("../../utils/request");

function formatDate(value) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

const today = new Date();
const defaultUseBy = new Date(today.getTime() + 3 * 24 * 60 * 60 * 1000);

Page({
  data: {
    itemId: "",
    pageTitle: "新增食材",
    saving: false,
    locationIndex: 0,
    locationOptions: [
      { label: "冷藏", value: "refrigerated" },
      { label: "冷冻", value: "frozen" },
      { label: "常温", value: "room_temperature" }
    ],
    form: {
      name: "",
      quantity: "1",
      unit: "个",
      stocked_on: formatDate(today),
      suggested_use_by: formatDate(defaultUseBy)
    }
  },

  onLoad(options) {
    if (options.id) {
      this.setData({
        itemId: options.id,
        pageTitle: "编辑食材"
      });
      wx.setNavigationBarTitle({ title: "编辑食材" });
      this.loadItem(options.id);
    }
  },

  async loadItem(itemId) {
    try {
      const result = await request({
        path: "/inventory",
        householdScoped: true
      });
      const item = result.items.find((candidate) => candidate.id === itemId);
      if (!item) {
        wx.showToast({ title: "食材不存在", icon: "none" });
        return;
      }
      const locationIndex = this.data.locationOptions.findIndex(
        (location) => location.value === item.location
      );
      this.setData({
        locationIndex: Math.max(0, locationIndex),
        form: {
          name: item.name,
          quantity: item.quantity,
          unit: item.unit,
          stocked_on: item.stocked_on,
          suggested_use_by: item.suggested_use_by || item.stocked_on
        }
      });
    } catch (error) {
      wx.showToast({ title: "读取食材失败", icon: "none" });
    }
  },

  onTextInput(event) {
    const field = event.currentTarget.dataset.field;
    this.setData({ [`form.${field}`]: event.detail.value });
  },

  onDateChange(event) {
    const field = event.currentTarget.dataset.field;
    this.setData({ [`form.${field}`]: event.detail.value });
  },

  onLocationChange(event) {
    this.setData({ locationIndex: Number(event.detail.value) });
    if (!this.data.itemId && this.data.form.name.trim()) {
      this.suggestUseBy();
    }
  },

  async suggestUseBy() {
    const form = this.data.form;
    if (!form.name.trim() || !form.stocked_on) {
      wx.showToast({ title: "请先填写食材名称", icon: "none" });
      return;
    }
    const location = this.data.locationOptions[this.data.locationIndex].value;
    try {
      const suggestion = await request({
        path:
          "/shelf-life-rules/suggestion" +
          `?food_name=${encodeURIComponent(form.name.trim())}` +
          `&location=${location}` +
          `&stocked_on=${form.stocked_on}`,
        householdScoped: true
      });
      this.setData({
        "form.suggested_use_by": suggestion.suggested_use_by
      });
      wx.showToast({
        title:
          suggestion.source === "household_rule"
            ? "已应用家庭规则"
            : "已应用默认规则",
        icon: "none"
      });
    } catch (error) {
      wx.showToast({ title: "保鲜日期计算失败", icon: "none" });
    }
  },

  async save() {
    const form = this.data.form;
    if (!form.name.trim()) {
      wx.showToast({ title: "请输入食材名称", icon: "none" });
      return;
    }
    if (!form.quantity || Number(form.quantity) <= 0) {
      wx.showToast({ title: "数量必须大于 0", icon: "none" });
      return;
    }
    if (!form.unit.trim()) {
      wx.showToast({ title: "请输入单位", icon: "none" });
      return;
    }
    if (form.suggested_use_by < form.stocked_on) {
      wx.showToast({ title: "建议食用日期不能早于入库日期", icon: "none" });
      return;
    }

    this.setData({ saving: true });
    try {
      await request({
        path: this.data.itemId
          ? `/inventory/${this.data.itemId}`
          : "/inventory",
        method: this.data.itemId ? "PUT" : "POST",
        householdScoped: true,
        data: {
          ...form,
          name: form.name.trim(),
          unit: form.unit.trim(),
          location: this.data.locationOptions[this.data.locationIndex].value
        }
      });
      wx.showToast({
        title: this.data.itemId ? "已更新" : "已加入库存"
      });
      setTimeout(() => wx.navigateBack(), 500);
    } catch (error) {
      const message = error.statusCode === 422
        ? "输入内容不符合要求"
        : "保存失败，请检查后端服务";
      wx.showToast({ title: message, icon: "none" });
      this.setData({ saving: false });
    }
  }
});
