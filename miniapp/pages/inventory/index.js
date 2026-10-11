const { request } = require("../../utils/request");

const LOCATION_LABELS = {
  refrigerated: "冷藏",
  frozen: "冷冻",
  room_temperature: "常温"
};

function statusClass(status) {
  if (status === "overdue" || status === "eat_today") {
    return "status-red";
  }
  if (status === "eat_soon") {
    return "status-yellow";
  }
  return "status-green";
}

function viewModel(item) {
  return {
    ...item,
    locationLabel: LOCATION_LABELS[item.location] || item.location,
    quantityText: item.quantity_text,
    statusText: item.status_text,
    statusClass: statusClass(item.status)
  };
}

Page({
  data: {
    filters: [
      { value: "all", label: "全部" },
      { value: "refrigerated", label: "冷藏" },
      { value: "frozen", label: "冷冻" },
      { value: "room_temperature", label: "常温" }
    ],
    selectedFilter: "all",
    allFoods: [],
    foods: [],
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
      const allFoods = result.items.map(viewModel);
      this.setData({
        allFoods,
        foods: this.filteredFoods(allFoods, this.data.selectedFilter),
        revision: result.revision,
        loading: false
      });
    } catch (error) {
      this.setData({
        loading: false,
        errorMessage: "无法连接库存服务，请确认 FastAPI 正在运行。"
      });
    }
  },

  filteredFoods(foods, selectedFilter) {
    return selectedFilter === "all"
      ? foods
      : foods.filter((item) => item.location === selectedFilter);
  },

  selectFilter(event) {
    const selectedFilter = event.currentTarget.dataset.value;
    const foods = this.filteredFoods(this.data.allFoods, selectedFilter);
    this.setData({ selectedFilter, foods });
  },

  goToAdd() {
    wx.navigateTo({
      url: "/pages/inventory-edit/index",
      fail: (error) => {
        console.error("打开新增食材页面失败", error);
        wx.showModal({
          title: "页面跳转失败",
          content: error.errMsg || "请重新编译小程序后再试。",
          showCancel: false
        });
      }
    });
  },

  goToEdit(event) {
    const { id } = event.currentTarget.dataset;
    wx.navigateTo({ url: `/pages/inventory-edit/index?id=${id}` });
  },

  goToHistory() {
    wx.navigateTo({ url: "/pages/inventory-history/index" });
  },

  applyOperation(event) {
    const { id, name, action, quantity } = event.currentTarget.dataset;
    const actionText = action === "consume" ? "消耗" : "丢弃";
    wx.showModal({
      title: `${actionText}“${name}”`,
      content: "1",
      editable: true,
      placeholderText: `输入数量，当前共有 ${quantity}`,
      confirmText: actionText,
      success: async (result) => {
        if (!result.confirm) return;
        const amount = Number(result.content);
        if (!Number.isFinite(amount) || amount <= 0) {
          wx.showToast({ title: "数量必须大于 0", icon: "none" });
          return;
        }
        try {
          await request({
            path: `/inventory/${id}/actions`,
            method: "POST",
            householdScoped: true,
            data: { action, quantity: String(amount) }
          });
          wx.showToast({ title: `已${actionText}` });
          this.loadInventory();
        } catch (error) {
          wx.showToast({
            title:
              error.statusCode === 409
                ? "数量超过当前库存"
                : `${actionText}失败`,
            icon: "none"
          });
        }
      }
    });
  },

  deleteItem(event) {
    const { id, name } = event.currentTarget.dataset;
    wx.showModal({
      title: `删除“${name}”？`,
      content: "删除后库存和墨水屏画面都会更新。",
      success: async (result) => {
        if (!result.confirm) {
          return;
        }
        try {
          await request({
            path: `/inventory/${id}`,
            method: "DELETE",
            householdScoped: true
          });
          wx.showToast({ title: "已删除" });
          this.loadInventory();
        } catch (error) {
          wx.showToast({ title: "删除失败", icon: "none" });
        }
      }
    });
  }
});
