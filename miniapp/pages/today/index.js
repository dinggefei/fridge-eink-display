const { request } = require("../../utils/request");

function statusClass(status) {
  if (status === "overdue" || status === "eat_today") {
    return "status-red";
  }
  if (status === "eat_soon") {
    return "status-yellow";
  }
  return "status-green";
}

Page({
  data: {
    householdName: "我的冰箱",
    summary: [
      { label: "已超期", value: 0, className: "status-red" },
      { label: "今天吃", value: 0, className: "status-red" },
      { label: "尽快吃", value: 0, className: "status-yellow" },
      { label: "正常", value: 0, className: "status-green" }
    ],
    priorityFoods: [],
    loading: true,
    errorMessage: "",
    revision: 0
  },

  onShow() {
    this.loadInventory();
  },

  async loadInventory() {
    this.setData({ loading: true, errorMessage: "" });
    try {
      const result = await request({
        path: "/inventory",
        householdScoped: true
      });
      const summary = result.summary;
      const priorityFoods = result.items
        .filter((item) => ["overdue", "eat_today", "eat_soon"].includes(item.status))
        .slice(0, 6)
        .map((item) => ({
          id: item.id,
          name: item.name,
          quantityText: item.quantity_text,
          hint: item.status_text,
          className: statusClass(item.status)
        }));
      this.setData({
        householdName: result.household_name,
        revision: result.revision,
        summary: [
          {
            label: "已超期",
            value: summary.overdue,
            className: "status-red"
          },
          {
            label: "今天吃",
            value: summary.eat_today,
            className: "status-red"
          },
          {
            label: "尽快吃",
            value: summary.eat_soon,
            className: "status-yellow"
          },
          {
            label: "正常",
            value: summary.normal + summary.no_date,
            className: "status-green"
          }
        ],
        priorityFoods,
        loading: false
      });
    } catch (error) {
      this.setData({
        loading: false,
        errorMessage: "无法连接库存服务"
      });
    }
  },

  goToQuickEntry() {
    wx.navigateTo({ url: "/pages/quick-entry/index" });
  },

  goToImportOrder() {
    wx.navigateTo({ url: "/pages/import-order/index" });
  },

  retry() {
    this.loadInventory();
  }
});
