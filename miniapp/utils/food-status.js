const FOOD_STATUS = {
  NORMAL: "normal",
  EAT_SOON: "eat_soon",
  EAT_TODAY: "eat_today",
  OVERDUE: "overdue",
  NO_DATE: "no_date"
};

const FOOD_STATUS_LABEL = {
  [FOOD_STATUS.NORMAL]: "正常",
  [FOOD_STATUS.EAT_SOON]: "尽快吃",
  [FOOD_STATUS.EAT_TODAY]: "今天吃",
  [FOOD_STATUS.OVERDUE]: "已超期",
  [FOOD_STATUS.NO_DATE]: "待补充"
};

module.exports = {
  FOOD_STATUS,
  FOOD_STATUS_LABEL
};
