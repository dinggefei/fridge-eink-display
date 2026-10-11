from datetime import date

from app.services.almanac import (
    ALMANAC_CALCULATION_VERSION,
    calculate_almanac,
)
from app.services.device_frame import FRAME_SIZE, encode_f53, load_almanac_frame
from app.services.display_renderer import (
    BLACK_RGB,
    DISPLAY_HEIGHT,
    DISPLAY_WIDTH,
    RED_RGB,
    WHITE_RGB,
    YELLOW_RGB,
    native_image_to_portrait,
    render_almanac_image,
)
from app.services.weather import WeatherSummary


DISPLAYED_ON = date(2026, 9, 7)


def test_real_almanac_data_for_2026_09_07() -> None:
    almanac = calculate_almanac(DISPLAYED_ON)

    assert ALMANAC_CALCULATION_VERSION == "lunar-python-1.4.8-sect1"
    assert almanac.weekday == "星期一"
    assert almanac.lunar_date == "二〇二六年七月廿六"
    assert almanac.ganzhi == "丙午年 丁酉月 甲申日"
    assert almanac.zodiac == "马"
    assert almanac.seasonal_note == "节气 白露"
    assert almanac.yi == ("嫁娶", "出行", "伐木", "拆卸")
    assert almanac.ji == ("掘井", "祈福", "安床", "开市")
    assert almanac.chong_sha == "冲（戊寅）虎 · 煞南"
    assert almanac.disclaimer == "传统民俗，仅供参考"


def test_almanac_render_is_native_four_color_frame() -> None:
    image = render_almanac_image(calculate_almanac(DISPLAYED_ON))

    assert image.size == (DISPLAY_WIDTH, DISPLAY_HEIGHT)
    assert native_image_to_portrait(image).size == (480, 800)
    assert set(image.get_flattened_data()) <= {
        WHITE_RGB,
        BLACK_RGB,
        YELLOW_RGB,
        RED_RGB,
    }
    assert len(encode_f53(image)) == FRAME_SIZE


def test_almanac_weather_render_is_native_four_color_frame() -> None:
    weather = WeatherSummary(
        location_name="上海",
        condition_text="多云转小雨",
        temp_min=18,
        temp_max=27,
        precip_probability=40,
    )
    image = render_almanac_image(calculate_almanac(DISPLAYED_ON), weather)

    assert image.size == (DISPLAY_WIDTH, DISPLAY_HEIGHT)
    assert set(image.get_flattened_data()) <= {
        WHITE_RGB,
        BLACK_RGB,
        YELLOW_RGB,
        RED_RGB,
    }
    assert len(encode_f53(image)) == FRAME_SIZE


def test_almanac_frame_etag_is_stable_for_one_day_and_changes_next_day() -> None:
    first = load_almanac_frame(DISPLAYED_ON)
    same_day = load_almanac_frame(DISPLAYED_ON)
    next_day = load_almanac_frame(date(2026, 9, 8))

    assert first is same_day
    assert len(first.data) == FRAME_SIZE
    assert first.version.startswith("almanac-v2-20260907-lp1.4.8-sect1-")
    assert first.etag == f'"{first.version}"'
    assert next_day.etag != first.etag


def test_almanac_weather_changes_the_device_frame_etag() -> None:
    without_weather = load_almanac_frame(DISPLAYED_ON)
    weather = WeatherSummary(
        location_name="上海",
        condition_text="多云",
        temp_min=18,
        temp_max=27,
        precip_probability=20,
    )
    with_weather = load_almanac_frame(DISPLAYED_ON, weather)

    assert with_weather.version.startswith(
        "almanac-v2-20260907-lp1.4.8-sect1-"
    )
    assert with_weather.etag != without_weather.etag
