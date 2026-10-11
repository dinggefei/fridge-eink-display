function mutationId() {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

async function request(options) {
  const app = getApp();
  await app.ensureAuthenticated();

  const headers = {
    "content-type": "application/json",
    ...(options.header || {})
  };

  if (app.globalData.accessToken) {
    headers.Authorization = `Bearer ${app.globalData.accessToken}`;
  }
  const method = options.method || "GET";
  if (["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
    headers["X-Idempotency-Key"] =
      headers["X-Idempotency-Key"] || mutationId();
  }
  const path = options.householdScoped
    ? `/v1/households/${app.globalData.currentHouseholdId}${options.path}`
    : options.path;

  return new Promise((resolve, reject) => {
    wx.request({
      url: `${app.globalData.apiBaseUrl}${path}`,
      method,
      data: options.data,
      header: headers,
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

async function uploadFile(options) {
  const app = getApp();
  await app.ensureAuthenticated();
  const path = options.householdScoped
    ? `/v1/households/${app.globalData.currentHouseholdId}${options.path}`
    : options.path;
  const headers = {
    ...(options.header || {}),
    "X-Idempotency-Key":
      (options.header || {})["X-Idempotency-Key"] || mutationId()
  };
  if (app.globalData.accessToken) {
    headers.Authorization = `Bearer ${app.globalData.accessToken}`;
  }

  return new Promise((resolve, reject) => {
    const task = wx.uploadFile({
      url: `${app.globalData.apiBaseUrl}${path}`,
      filePath: options.filePath,
      name: options.name || "image",
      formData: options.formData || {},
      header: headers,
      success(response) {
        let data = response.data;
        try {
          data = JSON.parse(response.data);
        } catch (error) {
          // Keep the raw response so the caller can show a useful failure.
        }
        if (response.statusCode >= 200 && response.statusCode < 300) {
          resolve(data);
          return;
        }
        reject({ statusCode: response.statusCode, data });
      },
      fail: reject
    });
    if (options.onProgress) {
      task.onProgressUpdate(options.onProgress);
    }
  });
}

async function downloadFile(options) {
  const app = getApp();
  await app.ensureAuthenticated();
  const path = options.householdScoped
    ? `/v1/households/${app.globalData.currentHouseholdId}${options.path}`
    : options.path;
  const headers = { ...(options.header || {}) };
  if (app.globalData.accessToken) {
    headers.Authorization = `Bearer ${app.globalData.accessToken}`;
  }

  return new Promise((resolve, reject) => {
    wx.downloadFile({
      url: `${app.globalData.apiBaseUrl}${path}`,
      header: headers,
      success(response) {
        if (response.statusCode >= 200 && response.statusCode < 300) {
          resolve(response.tempFilePath);
          return;
        }
        reject({ statusCode: response.statusCode });
      },
      fail: reject
    });
  });
}

module.exports = {
  request,
  uploadFile,
  downloadFile
};
