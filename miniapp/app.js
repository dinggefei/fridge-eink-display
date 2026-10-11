let localConfig = {
  apiBaseUrl: "http://127.0.0.1:8000",
  enableDevLogin: true
};

try {
  localConfig = require("./config.local.js");
} catch (error) {
  console.warn("config.local.js not found; using the local development API.");
}

App({
  globalData: {
    apiBaseUrl: localConfig.apiBaseUrl,
    currentHouseholdId: null,
    accessToken: null,
    currentUser: null,
    households: []
  },

  onLaunch() {
    this.authReady = this.initializeSession();
  },

  async initializeSession() {
    const cachedToken = wx.getStorageSync("rfm_access_token");
    const cachedHouseholdId = wx.getStorageSync("rfm_household_id");
    if (cachedToken) {
      this.globalData.accessToken = cachedToken;
      this.globalData.currentHouseholdId = cachedHouseholdId || null;
      try {
        const session = await this.rawRequest({
          path: "/v1/me",
          token: cachedToken
        });
        this.applySession(session);
        return session;
      } catch (error) {
        this.clearSession();
      }
    }

    try {
      const loginResult = await new Promise((resolve, reject) => {
        wx.login({ success: resolve, fail: reject });
      });
      const session = await this.rawRequest({
        path: "/v1/auth/wechat",
        method: "POST",
        data: { code: loginResult.code }
      });
      this.applySession(session);
      return session;
    } catch (wechatError) {
      if (!localConfig.enableDevLogin) {
        throw wechatError;
      }
      const session = await this.rawRequest({
        path: "/v1/auth/dev-login",
        method: "POST",
        data: { nickname: "本地开发用户" }
      });
      this.applySession(session);
      return session;
    }
  },

  ensureAuthenticated() {
    if (!this.authReady) {
      this.authReady = this.initializeSession();
    }
    return this.authReady;
  },

  applySession(session) {
    this.globalData.accessToken = session.access_token;
    this.globalData.currentHouseholdId = session.current_household_id;
    this.globalData.currentUser = session.user;
    this.globalData.households = session.households || [];
    wx.setStorageSync("rfm_access_token", session.access_token);
    wx.setStorageSync("rfm_household_id", session.current_household_id);
  },

  clearSession() {
    this.globalData.accessToken = null;
    this.globalData.currentHouseholdId = null;
    this.globalData.currentUser = null;
    this.globalData.households = [];
    wx.removeStorageSync("rfm_access_token");
    wx.removeStorageSync("rfm_household_id");
  },

  rawRequest({ path, method = "GET", data, token }) {
    return new Promise((resolve, reject) => {
      const header = { "content-type": "application/json" };
      if (token) {
        header.Authorization = `Bearer ${token}`;
      }
      wx.request({
        url: `${this.globalData.apiBaseUrl}${path}`,
        method,
        data,
        header,
        success(response) {
          if (response.statusCode >= 200 && response.statusCode < 300) {
            resolve(response.data);
            return;
          }
          reject({
            statusCode: response.statusCode,
            data: response.data
          });
        },
        fail: reject
      });
    });
  }
});
