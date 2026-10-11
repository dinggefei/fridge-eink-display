const { request, uploadFile } = require("../../utils/request");

const POLL_INTERVAL_MS = 1000;
const POLL_MAX_ATTEMPTS = 180;

const LOCATION_OPTIONS = [
  { label: "冷藏", value: "refrigerated" },
  { label: "冷冻", value: "frozen" },
  { label: "常温", value: "room_temperature" }
];

function toReviewItem(action) {
  return {
    ...action,
    selected: action.location !== "room_temperature",
    confidenceText: `${Math.round((action.confidence || 0) * 100)}%`,
    locationIndex: Math.max(
      0,
      LOCATION_OPTIONS.findIndex((item) => item.value === action.location)
    )
  };
}

function toApiItem(item) {
  const action = { ...item };
  delete action.selected;
  delete action.locationIndex;
  delete action.confidenceText;
  action.location = LOCATION_OPTIONS[item.locationIndex].value;
  return action;
}

Page({
  data: {
    images: [],
    phase: "select",
    progressText: "",
    taskId: "",
    items: [],
    warnings: [],
    confirming: false,
    locationOptions: LOCATION_OPTIONS
  },

  chooseImages() {
    const remaining = 9 - this.data.images.length;
    if (remaining <= 0) {
      wx.showToast({ title: "最多选择 9 张", icon: "none" });
      return;
    }

    wx.chooseImage({
      count: remaining,
      sizeType: ["compressed"],
      sourceType: ["album"],
      success: (result) => {
        this.setData({
          images: [...this.data.images, ...result.tempFilePaths]
        });
      }
    });
  },

  removeImage(event) {
    const index = Number(event.currentTarget.dataset.index);
    const images = this.data.images.filter((_, itemIndex) => itemIndex !== index);
    this.setData({ images });
  },

  async startImport() {
    if (this.data.images.length === 0 || this.data.phase !== "select") {
      return;
    }
    this.setData({
      phase: "uploading",
      progressText: "正在创建识别任务…",
      items: [],
      warnings: []
    });
    try {
      const task = await request({
        path: "/imports",
        method: "POST",
        householdScoped: true,
        data: {}
      });
      this.setData({ taskId: task.id });
      for (let index = 0; index < this.data.images.length; index += 1) {
        this.setData({
          progressText: `正在上传第 ${index + 1}/${this.data.images.length} 张图片`
        });
        await uploadFile({
          path: `/imports/${task.id}/images`,
          householdScoped: true,
          filePath: this.data.images[index],
          name: "image"
        });
      }
      this.setData({
        phase: "processing",
        progressText: "图片上传完成，正在识别商品…"
      });
      const started = await request({
        path: `/imports/${task.id}/start`,
        method: "POST",
        householdScoped: true,
        data: {}
      });
      await this.handleTask(started);
    } catch (error) {
      this.setData({
        phase: "select",
        progressText: ""
      });
      const message = error.statusCode === 422
        ? "图片格式或大小不符合要求"
        : "上传或识别失败，请重试";
      wx.showToast({ title: message, icon: "none" });
    }
  },

  async handleTask(task) {
    if (task.status === "needs_confirmation") {
      const result = task.result || { actions: [], warnings: [] };
      this.setData({
        phase: "review",
        progressText: "",
        images: [],
        items: result.actions.map(toReviewItem),
        warnings: result.warnings || []
      });
      if (result.actions.length === 0) {
        wx.showToast({ title: "没有识别到商品", icon: "none" });
      }
      return;
    }
    if (task.status === "failed") {
      throw { statusCode: 503, data: task.error_message };
    }
    await this.pollTask(task.id);
  },

  async pollTask(taskId) {
    for (let attempt = 0; attempt < POLL_MAX_ATTEMPTS; attempt += 1) {
      await new Promise((resolve) => {
        this.pollTimer = setTimeout(resolve, POLL_INTERVAL_MS);
      });
      if (this.unloaded) {
        return;
      }
      const task = await request({
        path: `/imports/${taskId}`,
        householdScoped: true
      });
      if (task.status === "needs_confirmation" || task.status === "failed") {
        await this.handleTask(task);
        return;
      }
      this.setData({
        progressText: `正在识别商品… ${Math.min(
          99,
          10 + Math.floor(attempt / 2)
        )}%`
      });
    }
    throw { statusCode: 504 };
  },

  onItemInput(event) {
    const index = Number(event.currentTarget.dataset.index);
    const field = event.currentTarget.dataset.field;
    this.setData({ [`items[${index}].${field}`]: event.detail.value });
  },

  onItemSelected(event) {
    const index = Number(event.currentTarget.dataset.index);
    this.setData({ [`items[${index}].selected`]: event.detail.value });
  },

  onLocationChange(event) {
    const index = Number(event.currentTarget.dataset.index);
    this.setData({
      [`items[${index}].locationIndex`]: Number(event.detail.value)
    });
  },

  onDateChange(event) {
    const index = Number(event.currentTarget.dataset.index);
    const field = event.currentTarget.dataset.field;
    this.setData({ [`items[${index}].${field}`]: event.detail.value });
  },

  async confirmImport() {
    if (this.data.confirming) {
      return;
    }
    const actions = this.data.items
      .filter((item) => item.selected)
      .map(toApiItem);
    if (actions.length === 0) {
      wx.showToast({ title: "请至少选择一项", icon: "none" });
      return;
    }
    if (actions.some((item) =>
      !item.name.trim() || Number(item.quantity) <= 0 || !item.unit.trim()
    )) {
      wx.showToast({ title: "请补全名称、数量和单位", icon: "none" });
      return;
    }
    this.setData({ confirming: true });
    try {
      await request({
        path: `/imports/${this.data.taskId}/confirm`,
        method: "POST",
        householdScoped: true,
        data: { actions }
      });
      wx.showToast({ title: "已批量加入库存" });
      setTimeout(() => wx.switchTab({ url: "/pages/inventory/index" }), 500);
    } catch (error) {
      const message = error.statusCode === 409
        ? "库存已变化，请重新识别"
        : "批量入库失败";
      wx.showToast({ title: message, icon: "none" });
      this.setData({ confirming: false });
    }
  },

  async cancelImport() {
    if (this.data.taskId) {
      try {
        await request({
          path: `/imports/${this.data.taskId}/cancel`,
          method: "POST",
          householdScoped: true,
          data: {}
        });
      } catch (error) {
        // The task may already be finished; local reset is still safe.
      }
    }
    this.setData({
      images: [],
      phase: "select",
      progressText: "",
      taskId: "",
      items: [],
      warnings: []
    });
  },

  onUnload() {
    this.unloaded = true;
    if (this.pollTimer) {
      clearTimeout(this.pollTimer);
    }
  }
});
