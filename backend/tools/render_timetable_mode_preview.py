"""Render the implemented timetable mode with representative local data."""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image

from app.services.display_renderer import native_image_to_portrait
from app.services.timetable_renderer import render_timetable_image


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "docs" / "assets" / "timetable_mode"

ENTRIES = [
    {"weekday": 1, "period_id": "morning-1", "course_name": "语文", "note": "预习课文"},
    {"weekday": 2, "period_id": "morning-1", "course_name": "数学", "note": "口算练习"},
    {"weekday": 3, "period_id": "morning-1", "course_name": "英语", "note": "单词听写"},
    {"weekday": 4, "period_id": "morning-1", "course_name": "语文", "note": "背诵课文"},
    {"weekday": 5, "period_id": "morning-1", "course_name": "数学", "note": "单元测验"},
    {"weekday": 6, "period_id": "morning-1", "course_name": "机器人", "note": "带电脑"},
    {"weekday": 1, "period_id": "morning-2", "course_name": "数学", "note": "作业讲评"},
    {"weekday": 2, "period_id": "morning-2", "course_name": "语文", "note": "习作课"},
    {"weekday": 3, "period_id": "morning-2", "course_name": "数学", "note": "几何练习"},
    {"weekday": 4, "period_id": "morning-2", "course_name": "英语", "note": "听写"},
    {"weekday": 5, "period_id": "morning-2", "course_name": "语文", "note": "阅读课"},
    {"weekday": 6, "period_id": "morning-2", "course_name": "机器人", "note": "搭建课"},
    {"weekday": 1, "period_id": "morning-3", "course_name": "英语", "note": "口语练习"},
    {"weekday": 2, "period_id": "morning-3", "course_name": "音乐", "note": "带竖笛"},
    {"weekday": 3, "period_id": "morning-3", "course_name": "科学", "note": "实验课"},
    {"weekday": 4, "period_id": "morning-3", "course_name": "数学", "note": "随堂练习"},
    {"weekday": 5, "period_id": "morning-3", "course_name": "英语", "note": "课文背诵"},
    {"weekday": 6, "period_id": "morning-3", "course_name": "游泳", "note": "带泳具"},
    {"weekday": 1, "period_id": "morning-4", "course_name": "体育", "note": "穿运动鞋"},
    {"weekday": 2, "period_id": "morning-4", "course_name": "英语", "note": "单词听写"},
    {"weekday": 3, "period_id": "morning-4", "course_name": "语文", "note": "阅读课"},
    {"weekday": 4, "period_id": "morning-4", "course_name": "美术", "note": "带画笔"},
    {"weekday": 5, "period_id": "morning-4", "course_name": "体育", "note": "体能训练"},
    {"weekday": 1, "period_id": "afternoon-1", "course_name": "科学", "note": "实验课"},
    {"weekday": 2, "period_id": "afternoon-1", "course_name": "道法", "note": "课堂讨论"},
    {"weekday": 3, "period_id": "afternoon-1", "course_name": "体育", "note": "穿运动鞋"},
    {"weekday": 4, "period_id": "afternoon-1", "course_name": "科学", "note": "实验课"},
    {"weekday": 5, "period_id": "afternoon-1", "course_name": "劳动", "note": "带手套"},
    {"weekday": 1, "period_id": "afternoon-2", "course_name": "美术", "note": "带画笔"},
    {"weekday": 2, "period_id": "afternoon-2", "course_name": "体育", "note": "穿运动鞋"},
    {"weekday": 3, "period_id": "afternoon-2", "course_name": "信息", "note": "机房实践"},
    {"weekday": 4, "period_id": "afternoon-2", "course_name": "音乐", "note": "带竖笛"},
    {"weekday": 5, "period_id": "afternoon-2", "course_name": "道法", "note": "复习"},
    {"weekday": 1, "period_id": "afternoon-3", "course_name": "班会", "note": "安全教育"},
    {"weekday": 2, "period_id": "afternoon-3", "course_name": "阅读", "note": "图书馆"},
    {"weekday": 3, "period_id": "afternoon-3", "course_name": "社团", "note": "活动室"},
    {"weekday": 4, "period_id": "afternoon-3", "course_name": "阅读", "note": "图书馆"},
    {"weekday": 5, "period_id": "afternoon-3", "course_name": "班会", "note": "周总结"},
    {"weekday": 4, "period_id": "morning-5", "course_name": "信息技术", "note": "机房上课"},
    {"weekday": 5, "period_id": "morning-5", "course_name": "科学", "note": "观察记录"},
    {"weekday": 6, "period_id": "morning-4", "course_name": "创意美术", "note": "带水彩笔"},
    {"weekday": 6, "period_id": "morning-5", "course_name": "阅读", "note": "自带图书"},
    {"weekday": 4, "period_id": "afternoon-4", "course_name": "综合实践活动", "note": "小组合作"},
    {"weekday": 5, "period_id": "afternoon-4", "course_name": "体育", "note": "穿运动鞋"},
    {"weekday": 6, "period_id": "afternoon-4", "course_name": "围棋", "note": "复盘练习"},
    {"weekday": 4, "period_id": "afternoon-5", "course_name": "托管", "note": "完成作业"},
    {"weekday": 5, "period_id": "afternoon-5", "course_name": "社团", "note": "科技教室"},
    {"weekday": 6, "period_id": "afternoon-5", "course_name": "自由活动", "note": "操场集合"},
]

TEN_PERIODS = [
    {"id": "morning-1", "section": "morning", "start_time": "08:00", "end_time": "08:40"},
    {"id": "morning-2", "section": "morning", "start_time": "08:50", "end_time": "09:30"},
    {"id": "morning-3", "section": "morning", "start_time": "09:50", "end_time": "10:30"},
    {"id": "morning-4", "section": "morning", "start_time": "10:40", "end_time": "11:20"},
    {"id": "morning-5", "section": "morning", "start_time": "11:30", "end_time": "12:10"},
    {"id": "afternoon-1", "section": "afternoon", "start_time": "13:30", "end_time": "14:10"},
    {"id": "afternoon-2", "section": "afternoon", "start_time": "14:20", "end_time": "15:00"},
    {"id": "afternoon-3", "section": "afternoon", "start_time": "15:10", "end_time": "15:50"},
    {"id": "afternoon-4", "section": "afternoon", "start_time": "16:00", "end_time": "16:40"},
    {"id": "afternoon-5", "section": "afternoon", "start_time": "16:50", "end_time": "17:30"},
]


def main() -> None:
    rendered_at = datetime(2026, 9, 17, 9, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
    portrait_native_image = render_timetable_image(
        TEN_PERIODS,
        ENTRIES,
        orientation="portrait",
        now=rendered_at,
    )
    portrait_image = native_image_to_portrait(portrait_native_image)
    landscape_image = render_timetable_image(
        TEN_PERIODS,
        ENTRIES,
        orientation="landscape",
        now=rendered_at,
    )
    OUTPUT.mkdir(parents=True, exist_ok=True)
    native = OUTPUT / "three_day_timetable_implemented_20260917_native.png"
    portrait = OUTPUT / "three_day_timetable_implemented_20260917_portrait.png"
    preview = OUTPUT / "three_day_timetable_implemented_20260917_preview.png"
    landscape_native = OUTPUT / "weekly_timetable_implemented_20260918_native.png"
    landscape_preview = OUTPUT / "weekly_timetable_implemented_20260918_preview.png"
    portrait_native_image.save(native)
    portrait_image.save(portrait)
    portrait_image.resize((960, 1600), Image.Resampling.NEAREST).save(preview)
    landscape_image.save(landscape_native)
    landscape_image.resize((1600, 960), Image.Resampling.NEAREST).save(landscape_preview)
    print(native)
    print(portrait)
    print(preview)
    print(landscape_native)
    print(landscape_preview)


if __name__ == "__main__":
    main()
