from __future__ import annotations

from datetime import datetime, timedelta
import os
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageDraw, ImageFont

from app.services.display_renderer import (
    BLACK,
    DISPLAY_TIMEZONE,
    RED,
    WHITE,
    YELLOW,
    _fit_text,
    _font,
    _to_four_colors,
    display_datetime,
)


TIMETABLE_RENDER_VERSION = "v6"
WEEKDAY_LABELS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
DAY_LABELS = ("今天", "明天", "后天")
PERIOD_LABELS = (
    "第一节",
    "第二节",
    "第三节",
    "第四节",
    "第五节",
    "第六节",
    "第七节",
    "第八节",
    "第九节",
    "第十节",
)

DEFAULT_TIMETABLE_PERIODS: tuple[dict[str, str], ...] = (
    {"id": "morning-1", "section": "morning", "start_time": "08:00", "end_time": "08:45"},
    {"id": "morning-2", "section": "morning", "start_time": "08:55", "end_time": "09:40"},
    {"id": "morning-3", "section": "morning", "start_time": "10:00", "end_time": "10:45"},
    {"id": "morning-4", "section": "morning", "start_time": "10:55", "end_time": "11:40"},
    {"id": "afternoon-1", "section": "afternoon", "start_time": "13:30", "end_time": "14:15"},
    {"id": "afternoon-2", "section": "afternoon", "start_time": "14:25", "end_time": "15:10"},
    {"id": "afternoon-3", "section": "afternoon", "start_time": "15:30", "end_time": "16:15"},
)


def default_timetable_periods() -> list[dict[str, str]]:
    return [dict(period) for period in DEFAULT_TIMETABLE_PERIODS]


def _find_digit_font_path() -> str:
    candidates = (
        os.getenv("RFM_DIGIT_FONT"),
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    )
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise RuntimeError(
        "No timetable digit font found. Set RFM_DIGIT_FONT to a sans-serif font file."
    )


def _digit_font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(_find_digit_font_path(), size=size)


def _text_size(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
) -> tuple[int, int]:
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    return right - left, bottom - top


def _largest_fitting_course_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    max_width: int,
    max_height: int,
    min_size: int,
    max_size: int,
) -> ImageFont.FreeTypeFont:
    """Return the largest bold CJK font that fits one timetable cell."""
    for size in range(max_size, min_size - 1, -1):
        candidate = _font(size, bold=True)
        width, height = _text_size(draw, text, candidate)
        if width <= max_width and height <= max_height:
            return candidate
    return _font(min_size, bold=True)


def _largest_fitting_digit_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    max_width: int,
    max_height: int,
    min_size: int,
    max_size: int,
) -> ImageFont.FreeTypeFont:
    """Return the largest plain digit font that fits a timetable area."""
    for size in range(max_size, min_size - 1, -1):
        candidate = _digit_font(size)
        width, height = _text_size(draw, text, candidate)
        if width <= max_width and height <= max_height:
            return candidate
    return _digit_font(min_size)


def _minutes(value: str) -> int:
    hour_text, minute_text = value.split(":", 1)
    return int(hour_text) * 60 + int(minute_text)


def _current_period_id(
    periods: Sequence[dict],
    entries: Sequence[dict],
    now: datetime,
) -> str | None:
    weekday = now.weekday() + 1
    available = {
        str(entry["period_id"])
        for entry in entries
        if int(entry["weekday"]) == weekday and str(entry.get("course_name", "")).strip()
    }
    if not available:
        return None
    current_minutes = now.hour * 60 + now.minute
    upcoming: str | None = None
    for period in periods:
        period_id = str(period["id"])
        if period_id not in available:
            continue
        start = _minutes(str(period["start_time"]))
        end = _minutes(str(period["end_time"]))
        if start <= current_minutes < end:
            return period_id
        if current_minutes < start and upcoming is None:
            upcoming = period_id
    return upcoming


def _render_portrait_timetable_image(
    periods: Sequence[dict],
    entries: Sequence[dict],
    *,
    now: datetime | None = None,
) -> Image.Image:
    """Render today, tomorrow and the day after in the portrait device layout."""
    if not 1 <= len(periods) <= 10:
        raise ValueError("timetable requires between 1 and 10 periods")

    rendered_at = display_datetime(now or datetime.now(DISPLAY_TIMEZONE))
    portrait = Image.new("RGB", (480, 800), WHITE)
    draw = ImageDraw.Draw(portrait)

    title_font = _font(27, bold=True)
    date_font = _digit_font(15)
    draw.text((14, 13), "三日课程表", fill=BLACK, font=title_font)
    date_text = rendered_at.strftime("%Y-%m-%d")
    draw.text(
        (466 - draw.textlength(date_text, font=date_font), 21),
        date_text,
        fill=BLACK,
        font=date_font,
    )
    draw.line((12, 58, 468, 58), fill=BLACK, width=2)

    x0, x1 = 12, 468
    time_right = 90
    day_width = 126
    table_top = 68
    header_height = 64
    table_bottom = 744
    morning_count = sum(period.get("section") == "morning" for period in periods)
    afternoon_count = len(periods) - morning_count
    lunch_height = 26 if morning_count and afternoon_count else 0
    row_height = (
        table_bottom - table_top - header_height - lunch_height
    ) / len(periods)
    lunch_top = table_top + header_height + morning_count * row_height

    header_font = _font(18, bold=True)
    header_meta_font = _font(13)
    draw.rectangle(
        (time_right, table_top, time_right + day_width, table_top + header_height),
        fill=RED,
    )
    draw.text(
        ((x0 + time_right) / 2, table_top + 23),
        "节次",
        fill=BLACK,
        font=_font(16, bold=True),
        anchor="mm",
    )
    displayed_days = [rendered_at.date() + timedelta(days=index) for index in range(3)]
    displayed_weekdays = [day.weekday() + 1 for day in displayed_days]
    for day_index, day in enumerate(displayed_days):
        left = time_right + day_index * day_width
        center = left + day_width / 2
        fill = WHITE if day_index == 0 else BLACK
        draw.text(
            (center, table_top + 8),
            DAY_LABELS[day_index],
            fill=fill,
            font=header_font,
            anchor="ma",
        )
        meta = f"{WEEKDAY_LABELS[day.weekday()]}  {day.strftime('%m/%d')}"
        draw.text(
            (center, table_top + 37),
            meta,
            fill=fill,
            font=header_meta_font,
            anchor="ma",
        )

    entries_by_slot = {
        (int(entry["weekday"]), str(entry["period_id"])): entry
        for entry in entries
        if str(entry.get("course_name", "")).strip()
    }
    highlighted_period = _current_period_id(periods, entries, rendered_at)
    if row_height >= 70:
        note_font = _font(12)
        period_font, time_range_font = _font(15, bold=True), _digit_font(11)
        course_max_size = 34
    elif row_height >= 55:
        note_font = _font(10)
        period_font, time_range_font = _font(14, bold=True), _digit_font(10)
        course_max_size = 30
    else:
        note_font = _font(9)
        period_font, time_range_font = _font(12, bold=True), _digit_font(9)
        course_max_size = 26

    for row_index, period in enumerate(periods):
        y0 = table_top + header_height + row_index * row_height
        if row_index >= morning_count and lunch_height:
            y0 += lunch_height
        center_y = y0 + row_height / 2
        draw.text(
            ((x0 + time_right) / 2, center_y - 11),
            PERIOD_LABELS[row_index],
            fill=BLACK,
            font=period_font,
            anchor="mm",
        )
        time_range = f"{period['start_time']}–{period['end_time']}"
        draw.text(
            ((x0 + time_right) / 2, center_y + 13),
            time_range,
            fill=BLACK,
            font=time_range_font,
            anchor="mm",
        )
        for day_index, weekday in enumerate(displayed_weekdays):
            entry = entries_by_slot.get((weekday, str(period["id"])))
            if entry is None:
                continue
            left = time_right + day_index * day_width
            if day_index == 0 and str(period["id"]) == highlighted_period:
                draw.rectangle(
                    (left + 3, y0 + 3, left + day_width - 3, y0 + row_height - 3),
                    fill=YELLOW,
                )
            raw_course_name = str(entry["course_name"])
            raw_note = str(entry.get("note") or "")
            note_height = _text_size(draw, raw_note, note_font)[1] if raw_note else 0
            course_height = max(16, round(row_height - note_height - (14 if raw_note else 10)))
            course_font = _largest_fitting_course_font(
                draw,
                raw_course_name,
                max_width=day_width - 12,
                max_height=course_height,
                min_size=13,
                max_size=course_max_size,
            )
            course_name = _fit_text(
                draw,
                raw_course_name,
                font=course_font,
                max_width=day_width - 12,
            )
            note = _fit_text(
                draw,
                raw_note,
                font=note_font,
                max_width=day_width - 10,
            )
            if note:
                course_text_height = _text_size(draw, course_name, course_font)[1]
                note_text_height = _text_size(draw, note, note_font)[1]
                gap = 5
                block_height = course_text_height + gap + note_text_height
                course_center_y = center_y - block_height / 2 + course_text_height / 2
                note_center_y = center_y + block_height / 2 - note_text_height / 2
                draw.text(
                    (left + day_width / 2, course_center_y),
                    course_name,
                    fill=BLACK,
                    font=course_font,
                    anchor="mm",
                )
                draw.text(
                    (left + day_width / 2, note_center_y),
                    note,
                    fill=BLACK,
                    font=note_font,
                    anchor="mm",
                )
            else:
                draw.text(
                    (left + day_width / 2, center_y),
                    course_name,
                    fill=BLACK,
                    font=course_font,
                    anchor="mm",
                )

    if lunch_height:
        draw.rectangle((x0, lunch_top, x1, lunch_top + lunch_height), fill=WHITE)
        draw.line((x0, lunch_top, x1, lunch_top), fill=BLACK, width=2)
        draw.line(
            (x0, lunch_top + lunch_height, x1, lunch_top + lunch_height),
            fill=BLACK,
            width=2,
        )
        draw.text(
            ((x0 + time_right) / 2, lunch_top + lunch_height / 2),
            "午休",
            fill=RED,
            font=_font(12, bold=True),
            anchor="mm",
        )
        draw.text(
            ((time_right + x1) / 2, lunch_top + lunch_height / 2),
            f"{periods[morning_count - 1]['end_time']}—{periods[morning_count]['start_time']}",
            fill=BLACK,
            font=_digit_font(13),
            anchor="mm",
        )

    vertical_segments = (
        ((table_top, lunch_top), (lunch_top + lunch_height, table_bottom))
        if lunch_height
        else ((table_top, table_bottom),)
    )
    for x in (x0, time_right, time_right + day_width, time_right + day_width * 2, x1):
        for start_y, end_y in vertical_segments:
            draw.line((x, start_y, x, end_y), fill=BLACK, width=1)
    draw.line((x0, table_top, x1, table_top), fill=BLACK, width=2)
    draw.line(
        (x0, table_top + header_height, x1, table_top + header_height),
        fill=BLACK,
        width=2,
    )
    for row_index in range(1, morning_count + 1):
        y = round(table_top + header_height + row_index * row_height)
        draw.line((x0, y, x1, y), fill=BLACK, width=1)
    for row_index in range(1, afternoon_count + 1):
        y = round(lunch_top + lunch_height + row_index * row_height)
        draw.line(
            (x0, y, x1, y),
            fill=BLACK,
            width=2 if row_index == afternoon_count else 1,
        )

    footer_font = _font(12)
    draw.text((14, 762), "红色：今天", fill=RED, font=footer_font)
    draw.text((132, 762), "黄色：当前或下一节课", fill=BLACK, font=footer_font)
    draw.text((466, 762), "每日自动更新", fill=BLACK, font=footer_font, anchor="ra")
    return _to_four_colors(portrait.transpose(Image.Transpose.ROTATE_90))


def _render_landscape_timetable_image(
    periods: Sequence[dict],
    entries: Sequence[dict],
    *,
    now: datetime | None = None,
) -> Image.Image:
    """Render Monday through Sunday in the panel's native landscape layout."""
    if not 1 <= len(periods) <= 10:
        raise ValueError("timetable requires between 1 and 10 periods")

    rendered_at = display_datetime(now or datetime.now(DISPLAY_TIMEZONE))
    image = Image.new("RGB", (800, 480), WHITE)
    draw = ImageDraw.Draw(image)

    week_start = rendered_at.date() - timedelta(days=rendered_at.weekday())
    displayed_days = [week_start + timedelta(days=index) for index in range(7)]
    displayed_weekdays = [day.weekday() + 1 for day in displayed_days]

    title_font = _font(24, bold=True)
    date_font = _digit_font(13)
    draw.text((14, 8), "一周课程表", fill=BLACK, font=title_font)
    range_text = f"{displayed_days[0].strftime('%Y-%m-%d')}—{displayed_days[-1].strftime('%m-%d')}"
    draw.text((786, 16), range_text, fill=BLACK, font=date_font, anchor="ra")
    draw.line((12, 45, 788, 45), fill=BLACK, width=2)

    x0, x1 = 12, 788
    time_right = 82
    day_width = (x1 - time_right) / 7.0
    table_top = 51
    header_height = 44
    table_bottom = 445
    morning_count = sum(period.get("section") == "morning" for period in periods)
    afternoon_count = len(periods) - morning_count
    lunch_height = 18 if morning_count and afternoon_count else 0
    row_height = (
        table_bottom - table_top - header_height - lunch_height
    ) / len(periods)
    lunch_top = table_top + header_height + morning_count * row_height

    today_index = rendered_at.weekday()
    today_left = time_right + today_index * day_width
    draw.rectangle(
        (today_left, table_top, today_left + day_width, table_top + header_height),
        fill=RED,
    )

    draw.text(
        ((x0 + time_right) / 2, table_top + header_height / 2),
        "节次",
        fill=BLACK,
        font=_font(13, bold=True),
        anchor="mm",
    )
    for day_index, day in enumerate(displayed_days):
        left = time_right + day_index * day_width
        center = left + day_width / 2
        color = WHITE if day_index == today_index else BLACK
        weekday_text = "今天" if day_index == today_index else WEEKDAY_LABELS[day_index]
        date_text = day.strftime("%m/%d")
        weekday_meta_font = _largest_fitting_digit_font(
            draw,
            date_text,
            max_width=max(20, round(day_width - 8)),
            max_height=max(8, round(header_height * 0.25)),
            min_size=8,
            max_size=max(11, round(header_height * 0.34)),
        )
        meta_height = _text_size(draw, date_text, weekday_meta_font)[1]
        weekday_font = _largest_fitting_course_font(
            draw,
            weekday_text,
            max_width=max(20, round(day_width - 8)),
            max_height=max(12, round(header_height - meta_height - 10)),
            min_size=12,
            max_size=max(18, round(header_height * 0.62)),
        )
        label_height = _text_size(draw, weekday_text, weekday_font)[1]
        header_gap = 3
        header_block_height = label_height + header_gap + meta_height
        label_center_y = table_top + (header_height - header_block_height) / 2 + label_height / 2
        date_center_y = label_center_y + label_height / 2 + header_gap + meta_height / 2
        draw.text(
            (center, label_center_y),
            weekday_text,
            fill=color,
            font=weekday_font,
            anchor="mm",
        )
        draw.text(
            (center, date_center_y),
            date_text,
            fill=color,
            font=weekday_meta_font,
            anchor="mm",
        )

    entries_by_slot = {
        (int(entry["weekday"]), str(entry["period_id"])): entry
        for entry in entries
        if str(entry.get("course_name", "")).strip()
    }
    highlighted_period = _current_period_id(periods, entries, rendered_at)
    if row_height >= 48:
        note_font = _font(9)
    elif row_height >= 36:
        note_font = _font(8)
    else:
        note_font = _font(7)
    # Let the actual cell dimensions, rather than a conservative fixed cap,
    # decide the course-name size. Width and the note-reserved height below
    # still constrain long names, while short names can use the full cell.
    course_max_size = max(18, min(38, round(row_height * 1.15)))

    for row_index, period in enumerate(periods):
        row_top = table_top + header_height + row_index * row_height
        if row_index >= morning_count and lunch_height:
            row_top += lunch_height
        center_y = row_top + row_height / 2
        period_text = PERIOD_LABELS[row_index]
        time_range = f"{period['start_time']}–{period['end_time']}"
        time_range_font = _largest_fitting_digit_font(
            draw,
            time_range,
            max_width=max(24, round(time_right - x0 - 6)),
            max_height=max(7, round(row_height * 0.29)),
            min_size=7,
            max_size=max(10, min(16, round(row_height * 0.42))),
        )
        time_height = _text_size(draw, time_range, time_range_font)[1]
        period_font = _largest_fitting_course_font(
            draw,
            period_text,
            max_width=max(24, round(time_right - x0 - 6)),
            max_height=max(9, round(row_height - time_height - 7)),
            min_size=9,
            max_size=max(14, min(24, round(row_height * 0.68))),
        )
        period_height = _text_size(draw, period_text, period_font)[1]
        period_gap = max(1, min(4, round(row_height * 0.07)))
        period_block_height = period_height + period_gap + time_height
        period_center_y = center_y - period_block_height / 2 + period_height / 2
        time_center_y = center_y + period_block_height / 2 - time_height / 2
        draw.text(
            ((x0 + time_right) / 2, period_center_y),
            period_text,
            fill=BLACK,
            font=period_font,
            anchor="mm",
        )
        draw.text(
            ((x0 + time_right) / 2, time_center_y),
            time_range,
            fill=BLACK,
            font=time_range_font,
            anchor="mm",
        )

        for day_index, weekday in enumerate(displayed_weekdays):
            entry = entries_by_slot.get((weekday, str(period["id"])))
            if entry is None:
                continue
            left = time_right + day_index * day_width
            if day_index == today_index and str(period["id"]) == highlighted_period:
                draw.rectangle(
                    (left + 2, row_top + 2, left + day_width - 2, row_top + row_height - 2),
                    fill=YELLOW,
                )

            raw_course_name = str(entry["course_name"])
            raw_note = str(entry.get("note") or "")
            note_height = _text_size(draw, raw_note, note_font)[1] if raw_note else 0
            course_height = max(10, round(row_height - note_height - (6 if raw_note else 4)))
            course_font = _largest_fitting_course_font(
                draw,
                raw_course_name,
                max_width=max(20, round(day_width - 6)),
                max_height=course_height,
                min_size=9,
                max_size=course_max_size,
            )
            course_name = _fit_text(
                draw,
                raw_course_name,
                font=course_font,
                max_width=max(20, round(day_width - 6)),
            )
            note = _fit_text(
                draw,
                raw_note,
                font=note_font,
                max_width=max(20, round(day_width - 6)),
            )
            center_x = left + day_width / 2
            if note:
                course_text_height = _text_size(draw, course_name, course_font)[1]
                note_text_height = _text_size(draw, note, note_font)[1]
                gap = 2
                block_height = course_text_height + gap + note_text_height
                draw.text(
                    (center_x, center_y - block_height / 2 + course_text_height / 2),
                    course_name,
                    fill=BLACK,
                    font=course_font,
                    anchor="mm",
                )
                draw.text(
                    (center_x, center_y + block_height / 2 - note_text_height / 2),
                    note,
                    fill=BLACK,
                    font=note_font,
                    anchor="mm",
                )
            else:
                draw.text(
                    (center_x, center_y),
                    course_name,
                    fill=BLACK,
                    font=course_font,
                    anchor="mm",
                )

    if lunch_height:
        draw.rectangle((x0, lunch_top, x1, lunch_top + lunch_height), fill=WHITE)
        draw.line((x0, lunch_top, x1, lunch_top), fill=BLACK, width=2)
        draw.line((x0, lunch_top + lunch_height, x1, lunch_top + lunch_height), fill=BLACK, width=2)
        draw.text(
            ((x0 + time_right) / 2, lunch_top + lunch_height / 2),
            "午休",
            fill=RED,
            font=_font(9, bold=True),
            anchor="mm",
        )
        draw.text(
            ((time_right + x1) / 2, lunch_top + lunch_height / 2),
            f"{periods[morning_count - 1]['end_time']}—{periods[morning_count]['start_time']}",
            fill=BLACK,
            font=_digit_font(9),
            anchor="mm",
        )

    vertical_segments = (
        ((table_top, lunch_top), (lunch_top + lunch_height, table_bottom))
        if lunch_height
        else ((table_top, table_bottom),)
    )
    vertical_x = [x0, time_right] + [time_right + index * day_width for index in range(1, 8)]
    for x in vertical_x:
        for start_y, end_y in vertical_segments:
            draw.line((round(x), round(start_y), round(x), round(end_y)), fill=BLACK, width=1)
    draw.line((x0, table_top, x1, table_top), fill=BLACK, width=2)
    draw.line((x0, table_top + header_height, x1, table_top + header_height), fill=BLACK, width=2)
    for row_index in range(1, morning_count + 1):
        y = round(table_top + header_height + row_index * row_height)
        draw.line((x0, y, x1, y), fill=BLACK, width=1)
    for row_index in range(1, afternoon_count + 1):
        y = round(lunch_top + lunch_height + row_index * row_height)
        draw.line((x0, y, x1, y), fill=BLACK, width=2 if row_index == afternoon_count else 1)

    footer_font = _font(9)
    draw.text((14, 458), "红色：今天", fill=RED, font=footer_font)
    draw.text((105, 458), "黄色：当前或下一节课", fill=BLACK, font=footer_font)
    draw.text((786, 458), "每周课程 · 每日自动更新", fill=BLACK, font=footer_font, anchor="ra")
    return _to_four_colors(image)


def render_timetable_image(
    periods: Sequence[dict],
    entries: Sequence[dict],
    *,
    orientation: str = "portrait",
    now: datetime | None = None,
) -> Image.Image:
    """Render a portrait three-day or landscape seven-day timetable frame."""
    if orientation == "portrait":
        return _render_portrait_timetable_image(periods, entries, now=now)
    if orientation == "landscape":
        return _render_landscape_timetable_image(periods, entries, now=now)
    raise ValueError("timetable orientation must be portrait or landscape")
