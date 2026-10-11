const { request } = require("../../utils/request");

const LOCATION_OPTIONS = [
  { label: "冷藏", value: "refrigerated" },
  { label: "冷冻", value: "frozen" },
  { label: "常温", value: "room_temperature" }
];

const ACTION_LABELS = {
  add: "新增",
  consume: "消耗",
  discard: "丢弃",
  edit: "修改"
};

function toReviewAction(action) {
  const locationIndex = Math.max(
    0,
    LOCATION_OPTIONS.findIndex((item) => item.value === action.location)
  );
  return {
    ...action,
    selected: true,
    locationIndex,
    typeLabel: ACTION_LABELS[action.type] || action.type
  };
}

function toApiAction(action) {
  const result = { ...action };
  delete result.selected;
  delete result.locationIndex;
  delete result.typeLabel;
  if (result.type === "add" || result.type === "edit") {
    result.location = LOCATION_OPTIONS[action.locationIndex].value;
  }
  return result;
}

Page({
  data: {
    text: "",
    canSubmit: false,
    parsing: false,
    confirming: false,
    taskId: "",
    actions: [],
    queryResults: [],
    warnings: [],
    locationOptions: LOCATION_OPTIONS
  },

  onInput(event) {
    const text = event.detail.value;
    this.setData({
      text,
      canSubmit: text.trim().length > 0
    });
  },

  async submit() {
    if (!this.data.canSubmit || this.data.parsing) {
      return;
    }
    this.setData({
      parsing: true,
      actions: [],
      queryResults: [],
      warnings: []
    });
    try {
      const task = await request({
        path: "/quick-entry/parse",
        method: "POST",
        householdScoped: true,
        data: { text: this.data.text.trim() }
      });
      const result = task.result || { actions: [], warnings: [] };
      this.setData({
        taskId: task.id,
        actions: result.actions.map(toReviewAction),
        queryResults: result.query_results || [],
        warnings: result.warnings || [],
        parsing: false
      });
      if (
        result.actions.length === 0
        && (result.query_results || []).length === 0
      ) {
        wx.showToast({ title: "没有识别到食材", icon: "none" });
      }
    } catch (error) {
      this.setData({ parsing: false });
      wx.showToast({ title: "解析失败，请稍后重试", icon: "none" });
    }
  },

  onActionInput(event) {
    const index = Number(event.currentTarget.dataset.index);
    const field = event.currentTarget.dataset.field;
    this.setData({ [`actions[${index}].${field}`]: event.detail.value });
  },

  onActionSelected(event) {
    const index = Number(event.currentTarget.dataset.index);
    this.setData({
      [`actions[${index}].selected`]: event.detail.value
    });
  },

  onLocationChange(event) {
    const index = Number(event.currentTarget.dataset.index);
    this.setData({
      [`actions[${index}].locationIndex`]: Number(event.detail.value)
    });
  },

  onDateChange(event) {
    const index = Number(event.currentTarget.dataset.index);
    const field = event.currentTarget.dataset.field;
    this.setData({ [`actions[${index}].${field}`]: event.detail.value });
  },

  async confirm() {
    if (this.data.confirming) {
      return;
    }
    const actions = this.data.actions
      .filter((action) => action.selected)
      .map(toApiAction);
    if (actions.length === 0) {
      wx.showToast({ title: "请至少选择一项", icon: "none" });
      return;
    }
    if (actions.some((action) =>
      !action.name.trim() || Number(action.quantity) <= 0 || !action.unit.trim()
    )) {
      wx.showToast({ title: "请补全名称、数量和单位", icon: "none" });
      return;
    }
    this.setData({ confirming: true });
    try {
      await request({
        path: `/quick-entry/${this.data.taskId}/confirm`,
        method: "POST",
        householdScoped: true,
        data: { actions }
      });
      wx.showToast({ title: "库存已更新" });
      setTimeout(() => wx.switchTab({ url: "/pages/inventory/index" }), 500);
    } catch (error) {
      const message = error.statusCode === 409
        ? "库存已变化，请重新解析"
        : "确认失败，请稍后重试";
      wx.showToast({ title: message, icon: "none" });
      this.setData({ confirming: false });
    }
  }
});
