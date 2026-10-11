const { request } = require("../../utils/request");

const STATUS_LABELS = {
  pending: "待处理",
  processing: "识别中",
  needs_confirmation: "待确认",
  confirmed: "已确认",
  failed: "失败",
  cancelled: "已取消"
};

Page({
  data: {
    metrics: null,
    items: [],
    loading: true
  },

  onShow() {
    this.loadData();
  },

  async loadData() {
    this.setData({ loading: true });
    try {
      const [metrics, history] = await Promise.all([
        request({
          path: "/recognition/metrics",
          householdScoped: true
        }),
        request({
          path: "/recognition/history?page=1&page_size=50",
          householdScoped: true
        })
      ]);
      this.setData({
        metrics: {
          ...metrics,
          successRateText: `${Math.round(metrics.success_rate * 100)}%`,
          correctionRateText: `${Math.round(metrics.correction_rate * 100)}%`,
          confidenceText:
            metrics.average_confidence === null
              ? "—"
              : `${Math.round(metrics.average_confidence * 100)}%`,
          durationText:
            metrics.average_duration_ms === null
              ? "—"
              : `${(metrics.average_duration_ms / 1000).toFixed(1)} 秒`
        },
        items: history.items.map((item) => ({
          ...item,
          sourceLabel:
            item.source === "order_images" ? "订单图片" : "快速记一笔",
          statusLabel: STATUS_LABELS[item.status] || item.status,
          timeText: item.created_at.replace("T", " ").slice(0, 16)
        }))
      });
    } catch (error) {
      wx.showToast({ title: "识别记录加载失败", icon: "none" });
    } finally {
      this.setData({ loading: false });
    }
  }
});
