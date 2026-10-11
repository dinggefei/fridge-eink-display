"""Render the proposed portrait three-day timetable without changing production."""

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

from app.services.display_renderer import (
    BLACK,
    RED,
    WHITE,
    YELLOW,
    _fit_text,
    _font,
    _to_four_colors,
)


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "docs" / "assets" / "timetable_mode"
NUMBER_FONT_PATH = Path("/System/Library/Fonts/Supplemental/Arial.ttf")

PERIODS = [
    ("08:00", "08:45"),
    ("08:55", "09:40"),
    ("10:00", "10:45"),
    ("10:55", "11:40"),
    ("13:30", "14:15"),
    ("14:25", "15:10"),
    ("15:30", "16:15"),
]

COURSES = [
    [("语文", "背诵课文"), ("数学", "单元测验"), ("机器人", "带电脑")],
    [("英语", "听写"), ("语文", "阅读课"), ("机器人", "搭建课")],
    [("数学", "随堂练习"), ("英语", "课文背诵"), ("游泳", "带泳具")],
    [("美术", "带画笔"), ("体育", "体能训练"), ("", "")],
    [("科学", "实验课"), ("劳动", "带手套"), ("", "")],
    [("音乐", "带竖笛"), ("道法", "复习"), ("", "")],
    [("阅读", "图书馆"), ("班会", "周总结"), ("", "")],
]


def number_font(size: int) -> ImageFont.FreeTypeFont:
    if not NUMBER_FONT_PATH.is_file():
        raise RuntimeError(f"number font not found: {NUMBER_FONT_PATH}")
    return ImageFont.truetype(str(NUMBER_FONT_PATH), size=size)


def render() -> Image.Image:
    now = datetime(2026, 9, 17, 9, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
    image = Image.new("RGB", (480, 800), WHITE)
    draw = ImageDraw.Draw(image)

    title_font = _font(27, bold=True)
    header_font = _font(18, bold=True)
    header_meta_font = _font(13)
    course_font = _font(18, bold=True)
    note_font = _font(12)
    footer_font = _font(12)
    date_font = number_font(15)
    time_font = number_font(16)
    time_end_font = number_font(14)

    draw.text((14, 13), "三日课程表", fill=BLACK, font=title_font)
    date_text = now.strftime("%Y-%m-%d")
    date_width = draw.textlength(date_text, font=date_font)
    draw.text((466 - date_width, 21), date_text, fill=BLACK, font=date_font)
    draw.line((12, 58, 468, 58), fill=BLACK, width=2)

    x0, x1 = 12, 468
    time_right = 90
    day_width = 126
    table_top = 68
    header_height = 64
    lunch_height = 26
    table_bottom = 744
    row_height = (table_bottom - table_top - header_height - lunch_height) / len(PERIODS)
    morning_count = 4
    lunch_top = table_top + header_height + morning_count * row_height

    draw.rectangle((time_right, table_top, time_right + day_width, table_top + header_height), fill=RED)
    draw.text(((x0 + time_right) / 2, table_top + 23), "时间", fill=BLACK, font=_font(16, bold=True), anchor="mm")

    day_names = ("今天", "明天", "后天")
    weekday_names = ("周四", "周五", "周六")
    for day_index in range(3):
        day = now.date() + timedelta(days=day_index)
        left = time_right + day_index * day_width
        center = left + day_width / 2
        color = WHITE if day_index == 0 else BLACK
        draw.text((center, table_top + 8), day_names[day_index], fill=color, font=header_font, anchor="ma")
        meta = f"{weekday_names[day_index]}  {day.strftime('%m/%d')}"
        draw.text((center, table_top + 37), meta, fill=color, font=header_meta_font, anchor="ma")

    for row_index, ((start, end), courses) in enumerate(zip(PERIODS, COURSES, strict=True)):
        y0 = table_top + header_height + row_index * row_height
        if row_index >= morning_count:
            y0 += lunch_height
        center_y = y0 + row_height / 2

        draw.text(((x0 + time_right) / 2, center_y - 11), start, fill=BLACK, font=time_font, anchor="mm")
        draw.text(((x0 + time_right) / 2, center_y + 11), end, fill=BLACK, font=time_end_font, anchor="mm")

        for day_index, (course_name, note) in enumerate(courses):
            left = time_right + day_index * day_width
            if day_index == 0 and row_index == 1:
                draw.rectangle((left + 3, y0 + 3, left + day_width - 3, y0 + row_height - 3), fill=YELLOW)
            if not course_name:
                continue
            course = _fit_text(draw, course_name, font=course_font, max_width=day_width - 12)
            note_text = _fit_text(draw, note, font=note_font, max_width=day_width - 10)
            draw.text((left + day_width / 2, center_y - 10), course, fill=BLACK, font=course_font, anchor="mm")
            draw.text((left + day_width / 2, center_y + 13), note_text, fill=BLACK, font=note_font, anchor="mm")

    draw.rectangle((x0, lunch_top, x1, lunch_top + lunch_height), fill=WHITE)
    draw.line((x0, lunch_top, x1, lunch_top), fill=BLACK, width=2)
    draw.line((x0, lunch_top + lunch_height, x1, lunch_top + lunch_height), fill=BLACK, width=2)
    draw.text(((x0 + time_right) / 2, lunch_top + lunch_height / 2), "午休", fill=RED, font=_font(12, bold=True), anchor="mm")
    draw.text(((time_right + x1) / 2, lunch_top + lunch_height / 2), "11:40—13:30", fill=BLACK, font=number_font(13), anchor="mm")

    vertical_segments = ((table_top, lunch_top), (lunch_top + lunch_height, table_bottom))
    for x in (x0, time_right, time_right + day_width, time_right + day_width * 2, x1):
        for start_y, end_y in vertical_segments:
            draw.line((x, start_y, x, end_y), fill=BLACK, width=1)
    draw.line((x0, table_top, x1, table_top), fill=BLACK, width=2)
    draw.line((x0, table_top + header_height, x1, table_top + header_height), fill=BLACK, width=2)
    for row_index in range(1, morning_count + 1):
        y = round(table_top + header_height + row_index * row_height)
        draw.line((x0, y, x1, y), fill=BLACK, width=1)
    for afternoon_index in range(1, len(PERIODS) - morning_count + 1):
        y = round(lunch_top + lunch_height + afternoon_index * row_height)
        draw.line((x0, y, x1, y), fill=BLACK, width=2 if afternoon_index == len(PERIODS) - morning_count else 1)

    draw.text((14, 762), "红色：今天", fill=RED, font=footer_font)
    draw.text((132, 762), "黄色：当前或下一节课", fill=BLACK, font=footer_font)
    draw.text((466, 762), "每日自动更新", fill=BLACK, font=footer_font, anchor="ra")
    return _to_four_colors(image)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    portrait = render()
    native = portrait.transpose(Image.Transpose.ROTATE_90)
    portrait_path = OUTPUT / "three_day_timetable_20260917_portrait.png"
    native_path = OUTPUT / "three_day_timetable_20260917_native.png"
    preview_path = OUTPUT / "three_day_timetable_20260917_preview.png"
    portrait.save(portrait_path)
    native.save(native_path)
    portrait.resize((960, 1600), Image.Resampling.NEAREST).save(preview_path)
    print(portrait_path)
    print(native_path)
    print(preview_path)


if __name__ == "__main__":
    main()
