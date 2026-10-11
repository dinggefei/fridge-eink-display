const { request, downloadFile } = require("../../utils/request");

const WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];
const COUNT_OPTIONS = [0, 1, 2, 3, 4, 5, 6];
const ORIENTATION_OPTIONS = [
  { value: "portrait", label: "竖屏模式", description: "显示今天、明天和后天" },
  { value: "landscape", label: "横屏模式", description: "显示周一至周日" }
];
const DEFAULT_TIMES = {
  morning: [
    ["08:00", "08:45"], ["08:55", "09:40"], ["10:00", "10:45"],
    ["10:55", "11:40"], ["11:50", "12:35"], ["12:45", "13:30"]
  ],
  afternoon: [
    ["13:30", "14:15"], ["14:25", "15:10"], ["15:30", "16:15"],
    ["16:25", "17:10"], ["17:20", "18:05"], ["18:15", "19:00"]
  ]
};

function errorText(error, fallback) {
  if (error && error.data && error.data.detail) {
    if (Array.isArray(error.data.detail)) return fallback;
    return error.data.detail;
  }
  return fallback;
}

function countSection(periods, section) {
  return periods.filter((period) => period.section === section).length;
}

function buildPeriods(periods, section, count) {
  const existing = periods.filter((period) => period.section === section);
  return Array.from({ length: count }, (_, index) => {
    if (existing[index]) return { ...existing[index] };
    const [startTime, endTime] = DEFAULT_TIMES[section][index];
    return {
      id: `${section}-${index + 1}`,
      section,
      start_time: startTime,
      end_time: endTime
    };
  });
}

Page({
  data: {
    loading: true,
    saving: false,
    periods: [],
    entries: [],
    orientation: "portrait",
    orientationOptions: ORIENTATION_OPTIONS,
    weekdays: WEEKDAYS.map((label, index) => ({ label, value: index + 1 })),
    selectedWeekday: 1,
    weekdayScrollIntoView: "weekday-1",
    morningCount: 4,
    afternoonCount: 3,
    countOptions: COUNT_OPTIONS,
    dayRows: [],
    previewPath: "",
    previewLoading: false,
    previewError: "",
    errorMessage: ""
  },

  onLoad() {
    const day = new Date().getDay();
    const selectedWeekday = day === 0 ? 7 : day;
    this.setData({
      selectedWeekday,
      weekdayScrollIntoView: `weekday-${selectedWeekday}`
    });
  },

  onShow() {
    this.loadTimetable();
  },

  async loadTimetable() {
    this.setData({ loading: true, errorMessage: "" });
    try {
      const timetable = await request({
        path: "/display-timetable",
        householdScoped: true
      });
      const periods = timetable.periods || [];
      const entries = timetable.entries || [];
      this.setData({
        loading: false,
        orientation: timetable.orientation || "portrait",
        periods,
        entries,
        morningCount: countSection(periods, "morning"),
        afternoonCount: countSection(periods, "afternoon")
      });
      this.refreshDayRows();
      this.loadPreview();
    } catch (error) {
      this.setData({ loading: false, errorMessage: "课程表加载失败" });
    }
  },

  refreshDayRows() {
    const { periods, entries, selectedWeekday } = this.data;
    const dayRows = periods.map((period, index) => {
      const entry = entries.find((item) => (
        item.weekday === selectedWeekday && item.period_id === period.id
      ));
      return {
        ...period,
        index,
        sectionText: period.section === "morning" ? "上午" : "下午",
        firstAfternoon: period.section === "afternoon" && (
          index === 0 || periods[index - 1].section !== "afternoon"
        ),
        courseName: entry ? entry.course_name : "",
        note: entry ? entry.note : ""
      };
    });
    this.setData({ dayRows });
  },

  onSelectWeekday(event) {
    const selectedWeekday = Number(event.currentTarget.dataset.weekday);
    this.setData({
      selectedWeekday,
      weekdayScrollIntoView: `weekday-${selectedWeekday}`
    });
    this.refreshDayRows();
  },

  onSelectOrientation(event) {
    const orientation = event.currentTarget.dataset.orientation;
    if (!ORIENTATION_OPTIONS.some((item) => item.value === orientation)) return;
    this.setData({ orientation });
  },

  onCountChange(event) {
    const section = event.currentTarget.dataset.section;
    const count = COUNT_OPTIONS[Number(event.detail.value)];
    const otherSection = section === "morning" ? "afternoon" : "morning";
    const otherCount = countSection(this.data.periods, otherSection);
    if (count + otherCount < 1 || count + otherCount > 10) {
      wx.showToast({ title: "全天课程总数需为1～10节", icon: "none" });
      return;
    }
    const morningCount = section === "morning" ? count : countSection(this.data.periods, "morning");
    const afternoonCount = section === "afternoon" ? count : countSection(this.data.periods, "afternoon");
    const periods = [
      ...buildPeriods(this.data.periods, "morning", morningCount),
      ...buildPeriods(this.data.periods, "afternoon", afternoonCount)
    ];
    const validIds = new Set(periods.map((period) => period.id));
    const entries = this.data.entries.filter((entry) => validIds.has(entry.period_id));
    this.setData({ periods, entries, morningCount, afternoonCount });
    this.refreshDayRows();
  },

  onPeriodTimeChange(event) {
    const index = Number(event.currentTarget.dataset.index);
    const field = event.currentTarget.dataset.field;
    const periods = this.data.periods.map((period, periodIndex) => (
      periodIndex === index ? { ...period, [field]: event.detail.value } : period
    ));
    this.setData({ periods });
    this.refreshDayRows();
  },

  onEntryInput(event) {
    const periodId = event.currentTarget.dataset.periodId;
    const field = event.currentTarget.dataset.field;
    const value = event.detail.value;
    const keyIndex = this.data.entries.findIndex((entry) => (
      entry.weekday === this.data.selectedWeekday && entry.period_id === periodId
    ));
    const entries = this.data.entries.map((entry) => ({ ...entry }));
    if (keyIndex >= 0) {
      entries[keyIndex][field] = value;
    } else {
      entries.push({
        weekday: this.data.selectedWeekday,
        period_id: periodId,
        course_name: field === "course_name" ? value : "",
        note: field === "note" ? value : ""
      });
    }
    this.setData({ entries });
    this.refreshDayRows();
  },

  validateBeforeSave() {
    const entries = this.data.entries.filter((entry) => (
      (entry.course_name || "").trim() || (entry.note || "").trim()
    ));
    const noteWithoutCourse = entries.some((entry) => (
      !(entry.course_name || "").trim() && (entry.note || "").trim()
    ));
    if (noteWithoutCourse) {
      wx.showToast({ title: "填写备注前请先填写课程名称", icon: "none" });
      return null;
    }
    return entries
      .filter((entry) => (entry.course_name || "").trim())
      .map((entry) => ({
        weekday: entry.weekday,
        period_id: entry.period_id,
        course_name: entry.course_name.trim(),
        note: (entry.note || "").trim()
      }));
  },

  async saveTimetable() {
    if (this.data.saving) return;
    const entries = this.validateBeforeSave();
    if (entries === null) return;
    this.setData({ saving: true });
    try {
      const timetable = await request({
        path: "/display-timetable",
        method: "PUT",
        householdScoped: true,
        data: {
          orientation: this.data.orientation,
          periods: this.data.periods,
          entries
        }
      });
      this.setData({
        saving: false,
        orientation: timetable.orientation || "portrait",
        periods: timetable.periods,
        entries: timetable.entries
      });
      this.refreshDayRows();
      await this.loadPreview();
      wx.showToast({ title: "课程表已保存" });
    } catch (error) {
      this.setData({ saving: false });
      wx.showToast({ title: errorText(error, "课程表保存失败，请检查时间设置"), icon: "none" });
    }
  },

  async loadPreview() {
    this.setData({ previewLoading: true, previewError: "", previewPath: "" });
    try {
      const previewPath = await downloadFile({
        path: "/display-timetable/preview",
        householdScoped: true
      });
      this.setData({ previewLoading: false, previewPath });
    } catch (error) {
      this.setData({ previewLoading: false, previewError: "课程表预览加载失败" });
    }
  },

  onPreviewError() {
    this.setData({ previewPath: "", previewError: "课程表预览加载失败" });
  }
});
