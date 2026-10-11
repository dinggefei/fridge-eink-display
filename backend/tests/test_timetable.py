from datetime import datetime
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw

from app.services.device_frame import FRAME_SIZE, load_timetable_frame
from app.services.timetable_renderer import (
    PERIOD_LABELS,
    _largest_fitting_course_font,
    _largest_fitting_digit_font,
    default_timetable_periods,
    render_timetable_image,
)


NOW = datetime(2026, 9, 16, 10, 5, tzinfo=ZoneInfo("Asia/Shanghai"))


def sample_entries() -> list[dict]:
    return [
        {"weekday": 1, "period_id": "morning-1", "course_name": "语文", "note": "预习课文"},
        {"weekday": 3, "period_id": "morning-1", "course_name": "英语", "note": "单词听写"},
        {"weekday": 3, "period_id": "morning-3", "course_name": "科学", "note": "实验课"},
        {"weekday": 5, "period_id": "afternoon-1", "course_name": "劳动", "note": "带手套"},
    ]


def test_timetable_render_is_native_four_color_frame() -> None:
    image = render_timetable_image(
        default_timetable_periods(),
        sample_entries(),
        now=NOW,
    )
    assert image.size == (800, 480)
    assert set(color for _, color in image.getcolors(800 * 480)) == {
        (17, 17, 17),
        (255, 255, 255),
        (196, 43, 37),
        (224, 160, 0),
    }


def test_timetable_frame_changes_when_note_changes() -> None:
    periods = default_timetable_periods()
    first_entries = sample_entries()
    second_entries = [dict(entry) for entry in first_entries]
    second_entries[1]["note"] = "带课外书"
    first = load_timetable_frame(periods, first_entries, now=NOW)
    second = load_timetable_frame(periods, second_entries, now=NOW)
    assert len(first.data) == FRAME_SIZE == 96_000
    assert first.version.startswith("timetable-v6-")
    assert first.etag != second.etag


def test_timetable_ignores_courses_outside_the_three_day_window() -> None:
    periods = default_timetable_periods()
    first_entries = sample_entries()
    second_entries = [dict(entry) for entry in first_entries]
    second_entries[0]["note"] = "带课外书"
    first = load_timetable_frame(periods, first_entries, now=NOW)
    second = load_timetable_frame(periods, second_entries, now=NOW)
    assert first.etag == second.etag


def test_timetable_renders_ten_custom_periods() -> None:
    periods = [
        {
            "id": f"morning-{index + 1}" if index < 5 else f"afternoon-{index - 4}",
            "section": "morning" if index < 5 else "afternoon",
            "start_time": f"{8 + index:02d}:00",
            "end_time": f"{8 + index:02d}:40",
        }
        for index in range(10)
    ]
    image = render_timetable_image(periods, [], now=NOW)
    assert image.size == (800, 480)
    assert len(image.getcolors(800 * 480)) <= 4


def test_landscape_timetable_renders_full_week_and_changes_frame_identity() -> None:
    periods = default_timetable_periods()
    entries = sample_entries()
    portrait = load_timetable_frame(periods, entries, orientation="portrait", now=NOW)
    landscape = load_timetable_frame(periods, entries, orientation="landscape", now=NOW)
    landscape_image = render_timetable_image(
        periods,
        entries,
        orientation="landscape",
        now=NOW,
    )
    assert landscape_image.size == (800, 480)
    assert len(landscape_image.getcolors(800 * 480)) <= 4
    assert portrait.orientation == "portrait"
    assert landscape.orientation == "landscape"
    assert portrait.etag != landscape.etag


def test_landscape_week_includes_monday_course_changes() -> None:
    periods = default_timetable_periods()
    first_entries = sample_entries()
    second_entries = [dict(entry) for entry in first_entries]
    second_entries[0]["note"] = "带课外书"
    first = load_timetable_frame(periods, first_entries, orientation="landscape", now=NOW)
    second = load_timetable_frame(periods, second_entries, orientation="landscape", now=NOW)
    assert first.etag != second.etag


def test_timetable_rejects_unknown_orientation() -> None:
    try:
        render_timetable_image(
            default_timetable_periods(),
            sample_entries(),
            orientation="diagonal",
            now=NOW,
        )
    except ValueError as error:
        assert "portrait or landscape" in str(error)
    else:
        raise AssertionError("unknown timetable orientation was accepted")


def test_course_font_uses_more_of_the_cell_for_short_names() -> None:
    draw = ImageDraw.Draw(Image.new("RGB", (200, 80), "white"))
    short_font = _largest_fitting_course_font(
        draw,
        "语文",
        max_width=114,
        max_height=30,
        min_size=13,
        max_size=30,
    )
    long_font = _largest_fitting_course_font(
        draw,
        "综合实践活动",
        max_width=114,
        max_height=30,
        min_size=13,
        max_size=30,
    )
    assert short_font.size == 30
    assert long_font.size < short_font.size
    assert draw.textbbox((0, 0), "综合实践活动", font=long_font)[2] <= 114


def test_time_font_uses_the_largest_size_that_fits_the_period_cell() -> None:
    draw = ImageDraw.Draw(Image.new("RGB", (100, 40), "white"))
    font = _largest_fitting_digit_font(
        draw,
        "08:00–08:40",
        max_width=64,
        max_height=12,
        min_size=7,
        max_size=16,
    )
    left, top, right, bottom = draw.textbbox((0, 0), "08:00–08:40", font=font)
    assert font.size > 7
    assert right - left <= 64
    assert bottom - top <= 12


def test_period_labels_cover_all_ten_rows() -> None:
    assert PERIOD_LABELS == (
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
