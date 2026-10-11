const { request } = require("../../utils/request");

function errorText(error, fallback) {
  if (error && error.data && error.data.detail) {
    return error.data.detail;
  }
  if (error && error.errMsg) {
    return error.errMsg;
  }
  return fallback;
}

function confirmModal(options) {
  return new Promise((resolve) => {
    wx.showModal({
      ...options,
      success: (result) => resolve(result.confirm),
      fail: () => resolve(false)
    });
  });
}

Page({
  data: {
    loading: true,
    householdName: "",
    currentRole: "member",
    leaving: false,
    deleting: false,
    errorMessage: ""
  },

  onShow() {
    this.loadPage();
  },

  async loadPage() {
    this.setData({ loading: true, errorMessage: "" });
    try {
      const session = await request({ path: "/v1/me" });
      getApp().applySession(session);
      const household = session.households.find(
        (item) => item.id === session.current_household_id
      );
      this.setData({
        householdName: household ? household.name : "当前家庭",
        currentRole: household ? household.role : "member"
      });
    } catch (error) {
      this.setData({
        errorMessage: errorText(error, "隐私与数据信息加载失败")
      });
    } finally {
      this.setData({ loading: false });
    }
  },

  openPrivacyGuide() {
    wx.openPrivacyContract({
      fail: (error) => {
        wx.showToast({
          title: errorText(error, "隐私保护指引暂时无法打开"),
          icon: "none"
        });
      }
    });
  },

  async leaveHousehold() {
    if (this.data.currentRole === "admin") {
      wx.showModal({
        title: "管理员不能直接退出",
        content:
          "管理员需要保留家庭管理责任。如需清除全部数据，请先移除其他成员，再删除个人账号。",
        showCancel: false
      });
      return;
    }
    if (this.data.leaving) {
      return;
    }
    const confirmed = await confirmModal({
      title: "退出当前家庭",
      content:
        `确认退出“${this.data.householdName}”？退出后将无法查看该家庭的库存和记录。`,
      confirmText: "确认退出",
      confirmColor: "#b8352d"
    });
    if (!confirmed) {
      return;
    }

    this.setData({ leaving: true });
    try {
      const session = await request({
        path: `/v1/households/${getApp().globalData.currentHouseholdId}/leave`,
        method: "POST"
      });
      getApp().applySession(session);
      wx.showToast({ title: "已退出家庭", icon: "success" });
      setTimeout(() => wx.navigateBack(), 600);
    } catch (error) {
      wx.showToast({
        title: errorText(error, "退出家庭失败"),
        icon: "none"
      });
    } finally {
      this.setData({ leaving: false });
    }
  },

  async deleteAccount() {
    if (this.data.deleting) {
      return;
    }
    const understood = await confirmModal({
      title: "删除个人账号",
      content:
        "将删除个人身份、偏好和识别记录。你管理且没有其他成员的家庭库存会一并删除，绑定设备将解除绑定。其他家庭中的必要操作记录仅匿名保留。",
      confirmText: "继续",
      confirmColor: "#b8352d"
    });
    if (!understood) {
      return;
    }
    const confirmed = await confirmModal({
      title: "最终确认",
      content: "删除后无法恢复，确认删除个人账号及相关数据？",
      confirmText: "确认删除",
      confirmColor: "#b8352d"
    });
    if (!confirmed) {
      return;
    }

    this.setData({ deleting: true });
    try {
      await request({ path: "/v1/me", method: "DELETE" });
      const app = getApp();
      app.clearSession();
      app.authReady = null;
      wx.showModal({
        title: "删除完成",
        content: "个人数据已删除。再次进入小程序时会创建新的空白空间。",
        showCancel: false,
        success: () => {
          wx.exitMiniProgram({
            fail: () => wx.reLaunch({ url: "/pages/today/index" })
          });
        }
      });
    } catch (error) {
      wx.showModal({
        title: "暂时不能删除",
        content: errorText(error, "个人账号删除失败，请稍后重试"),
        showCancel: false
      });
    } finally {
      this.setData({ deleting: false });
    }
  }
});
