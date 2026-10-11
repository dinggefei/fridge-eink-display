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
    currentHouseholdName: "",
    displayTodos: [],
    loading: false,
    saving: false,
    errorMessage: ""
  },

  onShow() {
    this.loadPage();
  },

  async loadPage() {
    if (this.data.loading) return;
    this.setData({ loading: true, errorMessage: "" });
    try {
      const session = await request({ path: "/v1/me" });
      getApp().applySession(session);
      this.setData({
        households: session.households || [],
        currentHouseholdId: session.current_household_id
      });
      this.updateCurrentHousehold();
      await this.loadDisplayTodos();
    } catch (error) {
      this.setData({
        errorMessage: errorText(error, "待办加载失败")
      });
    } finally {
      this.setData({ loading: false });
    }
  },

  updateCurrentHousehold() {
    const household = this.data.households.find(
      (item) => item.id === this.data.currentHouseholdId
    );
    this.setData({
      currentHouseholdName: household ? household.name : "当前家庭"
    });
  },

  async loadDisplayTodos() {
    const result = await request({
      path: "/inventory/settings/display-todos",
      householdScoped: true
    });
    this.setData({ displayTodos: result.items || [] });
  },

  retry() {
    this.loadPage();
  },

  onTodoInput(event) {
    const index = Number(event.currentTarget.dataset.index);
    this.setData({
      [`displayTodos[${index}]`]: event.detail.value
    });
  },

  addTodo() {
    if (this.data.displayTodos.length >= 10) {
      wx.showToast({ title: "最多设置 10 条待办", icon: "none" });
      return;
    }
    this.setData({
      displayTodos: [...this.data.displayTodos, ""]
    });
  },

  removeTodo(event) {
    const index = Number(event.currentTarget.dataset.index);
    this.setData({
      displayTodos: this.data.displayTodos.filter(
        (_, itemIndex) => itemIndex !== index
      )
    });
  },

  async saveDisplayTodos() {
    if (this.data.saving) return;
    const items = this.data.displayTodos
      .map((item) => item.trim())
      .filter(Boolean);
    if (items.some((item) => item.length > 40)) {
      wx.showToast({ title: "每条待办最多 40 个字符", icon: "none" });
      return;
    }
    this.setData({ saving: true });
    try {
      const result = await request({
        path: "/inventory/settings/display-todos",
        method: "PUT",
        householdScoped: true,
        data: { items }
      });
      this.setData({ displayTodos: result.items || [] });
      wx.showToast({ title: "待办已保存", icon: "success" });
    } catch (error) {
      wx.showToast({
        title: errorText(error, "待办保存失败"),
        icon: "none"
      });
    } finally {
      this.setData({ saving: false });
    }
  },

  async switchHousehold(event) {
    const index = Number(event.detail.value);
    const household = this.data.households[index];
    if (!household || household.id === this.data.currentHouseholdId) {
      return;
    }
    this.setData({ loading: true, errorMessage: "" });
    try {
      const session = await request({
        path: "/v1/me/current-household",
        method: "POST",
        data: { household_id: household.id }
      });
      getApp().applySession(session);
      this.setData({
        households: session.households || [],
        currentHouseholdId: session.current_household_id
      });
      this.updateCurrentHousehold();
      await this.loadDisplayTodos();
    } catch (error) {
      this.setData({
        errorMessage: errorText(error, "家庭切换失败")
      });
    } finally {
      this.setData({ loading: false });
    }
  }
});
