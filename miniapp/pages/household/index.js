const { request } = require("../../utils/request");

function errorText(error, fallback) {
  if (error && error.data && error.data.detail) {
    return error.data.detail;
  }
  return fallback;
}

Page({
  data: {
    households: [],
    currentHouseholdId: "",
    currentRole: "member",
    householdName: "",
    savingName: false,
    members: [],
    invitationCode: "",
    invitationExpiresAt: "",
    joinCode: "",
    loading: false,
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
      this.setData({
        households: session.households,
        currentHouseholdId: session.current_household_id
      });
      this.updateCurrentRole();
      await this.loadMembers();
    } catch (error) {
      this.setData({
        errorMessage: errorText(error, "家庭信息加载失败")
      });
    } finally {
      this.setData({ loading: false });
    }
  },

  updateCurrentRole() {
    const household = this.data.households.find(
      (item) => item.id === this.data.currentHouseholdId
    );
    this.setData({
      currentRole: household ? household.role : "member",
      householdName: household ? household.name : ""
    });
  },

  onHouseholdNameInput(event) {
    this.setData({ householdName: event.detail.value });
  },

  async saveHouseholdName() {
    if (this.data.currentRole !== "admin" || this.data.savingName) {
      return;
    }
    const name = this.data.householdName.trim();
    if (!name) {
      wx.showToast({ title: "冰箱名称不能为空", icon: "none" });
      return;
    }
    if (name.length > 40) {
      wx.showToast({ title: "冰箱名称最多 40 个字符", icon: "none" });
      return;
    }
    this.setData({ savingName: true });
    try {
      const result = await request({
        path: "/inventory/settings/household",
        method: "PUT",
        householdScoped: true,
        data: { name }
      });
      const households = this.data.households.map((item) =>
        item.id === this.data.currentHouseholdId
          ? { ...item, name: result.household_name }
          : item
      );
      getApp().globalData.households = households;
      this.setData({
        households,
        householdName: result.household_name
      });
      wx.showToast({ title: "名称已保存", icon: "success" });
    } catch (error) {
      wx.showToast({
        title: errorText(error, "名称保存失败"),
        icon: "none"
      });
    } finally {
      this.setData({ savingName: false });
    }
  },

  async loadMembers() {
    const members = await request({
      path: `/v1/households/${this.data.currentHouseholdId}/members`
    });
    this.setData({ members });
  },

  async switchHousehold(event) {
    const index = Number(event.detail.value);
    const household = this.data.households[index];
    if (!household || household.id === this.data.currentHouseholdId) {
      return;
    }
    try {
      const session = await request({
        path: "/v1/me/current-household",
        method: "POST",
        data: { household_id: household.id }
      });
      getApp().applySession(session);
      this.setData({
        households: session.households,
        currentHouseholdId: session.current_household_id,
        invitationCode: "",
        invitationExpiresAt: ""
      });
      this.updateCurrentRole();
      await this.loadMembers();
    } catch (error) {
      wx.showToast({
        title: errorText(error, "切换失败"),
        icon: "none"
      });
    }
  },

  onJoinCodeInput(event) {
    this.setData({ joinCode: event.detail.value });
  },

  async createInvitation() {
    try {
      const invitation = await request({
        path: `/v1/households/${this.data.currentHouseholdId}/invitations`,
        method: "POST"
      });
      this.setData({
        invitationCode: invitation.code,
        invitationExpiresAt: invitation.expires_at
      });
    } catch (error) {
      wx.showToast({
        title: errorText(error, "邀请码生成失败"),
        icon: "none"
      });
    }
  },

  copyInvitation() {
    wx.setClipboardData({ data: this.data.invitationCode });
  },

  async joinHousehold() {
    const code = this.data.joinCode.trim();
    if (!code) {
      wx.showToast({ title: "请输入邀请码", icon: "none" });
      return;
    }
    try {
      const session = await request({
        path: "/v1/households/join",
        method: "POST",
        data: { invitation_code: code }
      });
      getApp().applySession(session);
      this.setData({
        households: session.households,
        currentHouseholdId: session.current_household_id,
        joinCode: ""
      });
      this.updateCurrentRole();
      await this.loadMembers();
      wx.showToast({ title: "已加入家庭", icon: "success" });
    } catch (error) {
      wx.showToast({
        title: errorText(error, "加入失败"),
        icon: "none"
      });
    }
  },

  removeMember(event) {
    const member = event.currentTarget.dataset.member;
    wx.showModal({
      title: "移除家庭成员",
      content: `确认移除 ${member.nickname || "该成员"}？`,
      confirmColor: "#b8352d",
      success: async (result) => {
        if (!result.confirm) return;
        try {
          await request({
            path:
              `/v1/households/${this.data.currentHouseholdId}` +
              `/members/${member.user_id}`,
            method: "DELETE"
          });
          await this.loadMembers();
          wx.showToast({ title: "已移除", icon: "success" });
        } catch (error) {
          wx.showToast({
            title: errorText(error, "移除失败"),
            icon: "none"
          });
        }
      }
    });
  }
});
