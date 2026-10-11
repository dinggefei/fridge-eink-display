const { request } = require("../../utils/request");

const ACTION_LABELS = {
  add: "新增",
  edit: "修改",
  consume: "消耗",
  discard: "丢弃",
  delete: "删除",
  restore: "撤销恢复"
};

Page({
  data: {
    items: [],
    loading: true
  },

  onShow() {
    this.loadHistory();
  },

  async loadHistory() {
    this.setData({ loading: true });
    try {
      const result = await request({
        path: "/inventory/history?page=1&page_size=100",
        householdScoped: true
      });
      this.setData({
        items: result.items.map((item) => ({
          ...item,
          actionLabel: ACTION_LABELS[item.action] || item.action,
          timeText: item.created_at.replace("T", " ").slice(0, 16)
        }))
      });
    } catch (error) {
      wx.showToast({ title: "历史加载失败", icon: "none" });
    } finally {
      this.setData({ loading: false });
    }
  },

  restore(event) {
    const item = event.currentTarget.dataset.item;
    wx.showModal({
      title: "撤销最近操作",
      content: `恢复“${item.food_name}”到操作前的状态？`,
      success: async (result) => {
        if (!result.confirm) return;
        try {
          await request({
            path: `/inventory/history/${item.id}/restore`,
            householdScoped: true,
            method: "POST"
          });
          await this.loadHistory();
          wx.showToast({ title: "已恢复", icon: "success" });
        } catch (error) {
          wx.showToast({
            title:
              (error.data && error.data.detail)
              || "当前操作不能撤销",
            icon: "none"
          });
        }
      }
    });
  }
});
