const {
  request,
  uploadFile,
  downloadFile
} = require("../../utils/request");

const ROTATION_OPTIONS = [
  { label: "每 1 小时", value: 1 },
  { label: "每 3 小时", value: 3 },
  { label: "每 6 小时", value: 6 },
  { label: "每 12 小时", value: 12 },
  { label: "每 24 小时", value: 24 }
];

function errorText(error, fallback) {
  if (error && error.data && error.data.detail) {
    return error.data.detail;
  }
  return fallback;
}

Page({
  data: {
    loading: true,
    uploading: false,
    rotationOptions: ROTATION_OPTIONS,
    rotationIndex: 0,
    photos: [],
    confirmedCount: 0,
    maxPhotos: 6,
    errorMessage: ""
  },

  onShow() {
    this.loadAlbum();
  },

  async loadAlbum() {
    this.setData({ loading: true, errorMessage: "" });
    try {
      const album = await request({
        path: "/display-album",
        householdScoped: true
      });
      await this.applyAlbum(album);
    } catch (error) {
      this.setData({
        loading: false,
        errorMessage: "无法加载墨水屏相册"
      });
    }
  },

  async applyAlbum(album) {
    const photos = await Promise.all((album.photos || []).map(async (photo) => {
      try {
        const localPath = await downloadFile({ path: photo.image_path });
        return { ...photo, localPath };
      } catch (error) {
        return { ...photo, localPath: "" };
      }
    }));
    const confirmedCount = photos.filter(
      (photo) => photo.status === "confirmed"
    ).length;
    const rotationIndex = Math.max(
      0,
      ROTATION_OPTIONS.findIndex(
        (option) => option.value === album.rotation_hours
      )
    );
    this.setData({
      loading: false,
      rotationIndex,
      photos,
      confirmedCount,
      maxPhotos: album.max_photos || 6,
      errorMessage: ""
    });
  },

  async onRotationChange(event) {
    const index = Number(event.detail.value);
    const hours = ROTATION_OPTIONS[index].value;
    this.setData({ rotationIndex: index });
    try {
      const album = await request({
        path: "/display-album/settings",
        method: "PUT",
        householdScoped: true,
        data: { rotation_hours: hours }
      });
      await this.applyAlbum(album);
      wx.showToast({ title: "轮播周期已保存" });
    } catch (error) {
      wx.showToast({ title: "保存轮播周期失败", icon: "none" });
      await this.loadAlbum();
    }
  },

  choosePhoto() {
    if (this.data.uploading) {
      return;
    }
    if (this.data.photos.length >= this.data.maxPhotos) {
      wx.showToast({ title: `最多保存 ${this.data.maxPhotos} 张`, icon: "none" });
      return;
    }
    wx.chooseImage({
      count: 1,
      sizeType: ["compressed"],
      sourceType: ["album"],
      success: (result) => this.uploadPhoto(result.tempFilePaths[0])
    });
  },

  async uploadPhoto(filePath) {
    this.setData({ uploading: true });
    wx.showLoading({ title: "正在转换四色预览", mask: true });
    try {
      await uploadFile({
        path: "/display-album/photos",
        householdScoped: true,
        filePath,
        name: "image"
      });
      await this.loadAlbum();
      wx.showToast({ title: "请先检查预览" });
    } catch (error) {
      const message = error.statusCode === 413
        ? "图片不能超过 5MB"
        : errorText(error, "上传或转换失败");
      wx.showToast({ title: message, icon: "none" });
    } finally {
      wx.hideLoading();
      this.setData({ uploading: false });
    }
  },

  async confirmPhoto(event) {
    const photoId = event.currentTarget.dataset.id;
    try {
      const album = await request({
        path: `/display-album/photos/${photoId}/confirm`,
        method: "POST",
        householdScoped: true,
        data: {}
      });
      await this.applyAlbum(album);
      wx.showToast({ title: "照片已加入轮播" });
    } catch (error) {
      wx.showToast({ title: "确认照片失败", icon: "none" });
    }
  },

  async showNow(event) {
    const photoId = event.currentTarget.dataset.id;
    try {
      const album = await request({
        path: "/display-album/settings",
        method: "PUT",
        householdScoped: true,
        data: { active_photo_id: photoId }
      });
      await this.applyAlbum(album);
      wx.showToast({ title: "设备下次轮询时更新" });
    } catch (error) {
      wx.showToast({ title: "设置当前照片失败", icon: "none" });
    }
  },

  deletePhoto(event) {
    const photoId = event.currentTarget.dataset.id;
    wx.showModal({
      title: "删除照片",
      content: "删除后无法恢复，确定继续吗？",
      confirmColor: "#C42B25",
      success: async (result) => {
        if (!result.confirm) {
          return;
        }
        try {
          const album = await request({
            path: `/display-album/photos/${photoId}`,
            method: "DELETE",
            householdScoped: true
          });
          await this.applyAlbum(album);
          wx.showToast({ title: "照片已删除" });
        } catch (error) {
          wx.showToast({ title: "删除照片失败", icon: "none" });
        }
      }
    });
  },

  async movePhoto(event) {
    const photoId = event.currentTarget.dataset.id;
    const direction = Number(event.currentTarget.dataset.direction);
    const confirmed = this.data.photos.filter(
      (photo) => photo.status === "confirmed"
    );
    const index = confirmed.findIndex((photo) => photo.id === photoId);
    const target = index + direction;
    if (index < 0 || target < 0 || target >= confirmed.length) {
      return;
    }
    const reordered = [...confirmed];
    [reordered[index], reordered[target]] = [reordered[target], reordered[index]];
    try {
      const album = await request({
        path: "/display-album/order",
        method: "PUT",
        householdScoped: true,
        data: { photo_ids: reordered.map((photo) => photo.id) }
      });
      await this.applyAlbum(album);
    } catch (error) {
      wx.showToast({ title: "调整顺序失败", icon: "none" });
    }
  }
});
