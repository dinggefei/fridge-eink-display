"""Render a standalone four-colour weekly timetable concept preview.

This script does not change the mini program, API, database, or device firmware.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "docs" / "assets" / "timetable_mode"

BLACK = "#111111"
WHITE = "#FFFFFF"
RED = "#C8322C"
YELLOW = "#E7A900"


def font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = "/System/Library/Fonts/PingFang.ttc"
    return ImageFont.truetype(path, size=size, index=1 if bold else 0)


def main() -> None:
    image = Image.new("RGB", (800, 480), WHITE)
    draw = ImageDraw.Draw(image)

    # Real calendar week containing 2026-09-16 (Wednesday).
    weekdays = [
        ("周一", "09/14"),
        ("周二", "09/15"),
        ("周三", "09/16"),
        ("周四", "09/17"),
        ("周五", "09/18"),
        ("周六", "09/19"),
        ("周日", "09/20"),
    ]
    periods = [
        ("08:00", "08:45", "morning"),
        ("08:55", "09:40", "morning"),
        ("10:00", "10:45", "morning"),
        ("10:55", "11:40", "morning"),
        ("13:30", "14:15", "afternoon"),
        ("14:25", "15:10", "afternoon"),
        ("15:30", "16:15", "afternoon"),
    ]
    # course, short note; empty entries render as no class.
    schedule = [
        [("语文", "预习课文"), ("数学", "口算练习"), ("英语", "单词听写"), ("语文", "背诵课文"), ("数学", "单元测验"), ("机器人", "带电脑"), None],
        [("数学", "作业讲评"), ("语文", "习作课"), ("数学", "几何练习"), ("英语", "听写"), ("语文", "阅读课"), ("机器人", "搭建课"), None],
        [("英语", "口语练习"), ("音乐", "带竖笛"), ("科学", "实验课"), ("数学", "随堂练习"), ("英语", "课文背诵"), ("游泳", "带泳具"), None],
        [("体育", "穿运动鞋"), ("英语", "单词听写"), ("语文", "阅读课"), ("美术", "带画笔"), ("体育", "体能训练"), None, None],
        [("科学", "实验课"), ("道法", "课堂讨论"), ("体育", "穿运动鞋"), ("科学", "实验课"), ("劳动", "带手套"), None, None],
        [("美术", "带画笔"), ("体育", "穿运动鞋"), ("信息", "机房实践"), ("音乐", "带竖笛"), ("道法", "复习"), None, None],
        [("班会", "安全教育"), ("阅读", "图书馆"), ("社团", "活动室"), ("阅读", "图书馆"), ("班会", "周总结"), None, None],
    ]

    draw.text((16, 8), "第3周课程表", font=font(29, bold=True), fill=BLACK)
    draw.text((788, 13), "2026年9月14日—9月20日", font=font(17), fill=BLACK, anchor="ra")
    draw.line((14, 47, 786, 47), fill=BLACK, width=2)

    grid_x0, grid_x1 = 14, 786
    grid_y0, grid_y1 = 52, 447
    period_width = 72
    day_width = 100
    header_height = 47
    lunch_height = 20
    row_height = (grid_y1 - grid_y0 - header_height - lunch_height) / len(periods)
    day_x0 = grid_x0 + period_width
    lunch_y0 = grid_y0 + header_height + 4 * row_height

    # Wednesday column gets a very light yellow band. The final quantization
    # keeps the panel palette to black, white, red, and yellow only.
    wednesday_left = day_x0 + 2 * day_width
    draw.rectangle((wednesday_left, grid_y0, wednesday_left + day_width, grid_y1), fill="#FFF4C7")
    draw.rectangle((wednesday_left, grid_y0, wednesday_left + day_width, grid_y0 + header_height), fill=RED)

    # Header labels.
    draw.text((grid_x0 + period_width / 2, grid_y0 + 13), "时间", font=font(16, bold=True), fill=BLACK, anchor="ma")
    for index, (weekday, day) in enumerate(weekdays):
        cx = day_x0 + index * day_width + day_width / 2
        color = WHITE if index == 2 else BLACK
        draw.text((cx, grid_y0 + 5), "今天" if index == 2 else weekday, font=font(17, bold=True), fill=color, anchor="ma")
        draw.text((cx, grid_y0 + 26), day, font=font(12), fill=color, anchor="ma")

    # Course cells. The afternoon rows shift down by a dedicated lunch band.
    for row, (start_time, end_time, section) in enumerate(periods):
        y0 = grid_y0 + header_height + row * row_height
        if section == "afternoon":
            y0 += lunch_height
        cy = y0 + row_height / 2
        draw.text((grid_x0 + period_width / 2, cy - 10), start_time, font=font(12, bold=True), fill=BLACK, anchor="ma")
        draw.text((grid_x0 + period_width / 2, cy + 10), end_time, font=font(11), fill=BLACK, anchor="ma")
        for day_index, entry in enumerate(schedule[row]):
            if entry is None:
                continue
            course, short_note = entry
            x0 = day_x0 + day_index * day_width
            # Demonstrate the current/next lesson without obscuring the grid.
            if row == 2 and day_index == 2:
                draw.rectangle((x0 + 3, y0 + 3, x0 + day_width - 3, y0 + row_height - 3), fill=YELLOW)
            text_color = RED if (course == "劳动" and day_index == 4) else BLACK
            draw.text((x0 + day_width / 2, cy - 9), course, font=font(17, bold=True), fill=text_color, anchor="ma")
            draw.text((x0 + day_width / 2, cy + 9), short_note, font=font(11), fill=text_color, anchor="ma")

    # Morning / afternoon divider. It is deliberately compact so course rows
    # remain readable even when the user configures eight to ten periods.
    draw.rectangle((grid_x0, lunch_y0, grid_x1, lunch_y0 + lunch_height), fill=WHITE)
    draw.line((grid_x0, lunch_y0, grid_x1, lunch_y0), fill=BLACK, width=2)
    draw.line((grid_x0, lunch_y0 + lunch_height, grid_x1, lunch_y0 + lunch_height), fill=BLACK, width=2)
    draw.text((grid_x0 + period_width / 2, lunch_y0 + lunch_height / 2), "午休", font=font(12, bold=True), fill=RED, anchor="mm")
    draw.text((day_x0 + 350, lunch_y0 + lunch_height / 2), "11:40—13:30", font=font(11), fill=BLACK, anchor="mm")

    # Grid lines are drawn last so every cell remains visually crisp.
    for x in [grid_x0, day_x0] + [day_x0 + i * day_width for i in range(1, 8)]:
        draw.line((x, grid_y0, x, lunch_y0), fill=BLACK, width=1)
        draw.line((x, lunch_y0 + lunch_height, x, grid_y1), fill=BLACK, width=1)
    draw.line((grid_x0, grid_y0, grid_x1, grid_y0), fill=BLACK, width=2)
    draw.line((grid_x0, grid_y0 + header_height, grid_x1, grid_y0 + header_height), fill=BLACK, width=2)
    for row in range(1, 5):
        y = round(grid_y0 + header_height + row * row_height)
        draw.line((grid_x0, y, grid_x1, y), fill=BLACK, width=1)
    for row in range(1, 4):
        y = round(lunch_y0 + lunch_height + row * row_height)
        draw.line((grid_x0, y, grid_x1, y), fill=BLACK, width=1 if row < 3 else 2)

    draw.text((16, 458), "红色：今天/临时调整", font=font(11), fill=RED)
    draw.text((188, 458), "黄色：当前或下一节课", font=font(11), fill=BLACK)
    draw.text((787, 458), "周三 · 第3周", font=font(11), fill=BLACK, anchor="ra")

    # Map to the exact four colours used by the target panel.
    pixels = image.load()
    for y in range(image.height):
        for x in range(image.width):
            r, g, b = pixels[x, y]
            # Preserve neutral anti-aliased text as black/white. A simple
            # nearest-colour calculation can incorrectly turn grey glyph edges
            # red because the panel red is also relatively dark.
            if max(r, g, b) - min(r, g, b) < 30:
                pixels[x, y] = (17, 17, 17) if (r + g + b) / 3 < 225 else (255, 255, 255)
            elif r > 150 and g > 105 and b < 100:
                pixels[x, y] = (231, 169, 0)
            elif r > 120 and r > g * 1.35 and r > b * 1.35:
                pixels[x, y] = (200, 50, 44)
            else:
                luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
                pixels[x, y] = (17, 17, 17) if luminance < 210 else (255, 255, 255)

    OUTPUT.mkdir(parents=True, exist_ok=True)
    native = OUTPUT / "weekly_timetable_custom_periods_20260916_native.png"
    preview = OUTPUT / "weekly_timetable_custom_periods_20260916_preview.png"
    image.save(native)
    image.resize((1600, 960), Image.Resampling.NEAREST).save(preview)
    assert image.size == (800, 480)
    assert len(image.getcolors(800 * 480 + 1)) == 4
    print(native)
    print(preview)


if __name__ == "__main__":
    main()
