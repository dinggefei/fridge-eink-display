from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Iterable
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

from app.domain.inventory import FoodStatus
from app.services.almanac import AlmanacDay

if TYPE_CHECKING:
    from app.services.market_data import MarketSnapshot, MarketSnapshotItem
    from app.services.weather import WeatherSummary


DISPLAY_WIDTH = 800
DISPLAY_HEIGHT = 480
PORTRAIT_WIDTH = 480
PORTRAIT_HEIGHT = 800
MAX_DISPLAY_ITEMS = 15
MAX_DISPLAY_TODOS = 3
DISPLAY_TIMEZONE = ZoneInfo("Asia/Shanghai")
FOOD_NAME_FONT_SIZE = 20
FOOD_DETAIL_FONT_SIZE = 16
TODO_TITLE_FONT_SIZE = 22
TODO_ITEM_FONT_SIZE = 20
TODO_NOTE_FONT_SIZE = 14

WHITE = "#FFFFFF"
BLACK = "#111111"
RED = "#C42B25"
YELLOW = "#E0A000"
LIGHT_GRAY = "#E5E5E5"

WHITE_RGB = (255, 255, 255)
BLACK_RGB = (17, 17, 17)
RED_RGB = (196, 43, 37)
YELLOW_RGB = (224, 160, 0)


@dataclass(frozen=True, slots=True)
class DisplayFoodItem:
    name: str
    quantity_text: str
    status: FoodStatus
    status_text: str


def display_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=DISPLAY_TIMEZONE)
    return value.astimezone(DISPLAY_TIMEZONE)


def current_display_date(now: datetime | None = None) -> date:
    value = now or datetime.now(DISPLAY_TIMEZONE)
    return display_datetime(value).date()


def display_header_text(
    rendered_at: datetime,
    displayed_on: date | None = None,
) -> tuple[str, str]:
    local_rendered_at = display_datetime(rendered_at)
    date_text = (displayed_on or local_rendered_at.date()).strftime(
        "%Y-%m-%d"
    )
    return date_text, f"更新 {local_rendered_at.strftime('%H:%M')}"


def _find_font_path() -> str:
    configured = os.getenv("RFM_CJK_FONT")
    candidates = [
        configured,
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise RuntimeError(
        "No CJK font found. Set RFM_CJK_FONT to a Chinese font file."
    )


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    font_path = _find_font_path()
    index = 1 if bold and font_path.endswith(".ttc") else 0
    return ImageFont.truetype(font_path, size=size, index=index)


def _status_color(status: FoodStatus) -> str:
    if status in (FoodStatus.EAT_TODAY, FoodStatus.OVERDUE):
        return RED
    if status == FoodStatus.EAT_SOON:
        return YELLOW
    return BLACK


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> str:
    if draw.textlength(text, font=font) <= max_width:
        return text

    suffix = "…"
    result = text
    while result and draw.textlength(result + suffix, font=font) > max_width:
        result = result[:-1]
    return result + suffix


def _center_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    y: int,
    font: ImageFont.FreeTypeFont,
    fill: str,
    left: int = 0,
    right: int = PORTRAIT_WIDTH,
) -> None:
    width = draw.textlength(text, font=font)
    draw.text((left + (right - left - width) / 2, y), text, fill=fill, font=font)


def _to_four_colors(image: Image.Image) -> Image.Image:
    """Remove font antialiasing without turning neutral gray edges red."""
    normalized: list[tuple[int, int, int]] = []
    for red, green, blue in image.convert("RGB").get_flattened_data():
        channel_spread = max(red, green, blue) - min(red, green, blue)
        if channel_spread <= 20:
            normalized.append(BLACK_RGB if red < 200 else WHITE_RGB)
        elif red - blue > 55 and green - blue > 35 and red - green < 110:
            normalized.append(YELLOW_RGB)
        elif red - green > 45 and red - blue > 45:
            normalized.append(RED_RGB)
        else:
            luminance = (red * 299 + green * 587 + blue * 114) // 1000
            normalized.append(BLACK_RGB if luminance < 150 else WHITE_RGB)

    output = Image.new("RGB", image.size, WHITE_RGB)
    output.putdata(normalized)
    return output


def render_display_image(
    *,
    household_name: str,
    items: Iterable[DisplayFoodItem],
    rendered_at: datetime,
    displayed_on: date | None = None,
    mini_program_code_png: bytes | None = None,
    display_todos: Iterable[str] = (),
) -> Image.Image:
    all_items = list(items)
    visible_items = all_items[:MAX_DISPLAY_ITEMS]
    all_todos = list(display_todos)
    visible_todos = all_todos[:MAX_DISPLAY_TODOS]
    portrait = Image.new("RGB", (PORTRAIT_WIDTH, PORTRAIT_HEIGHT), WHITE)
    draw = ImageDraw.Draw(portrait)

    title_font = _font(32, bold=True)
    header_font = _font(17)
    item_font = _font(FOOD_NAME_FONT_SIZE, bold=True)
    detail_font = _font(FOOD_DETAIL_FONT_SIZE)
    footer_font = _font(15)

    date_text, update_text = display_header_text(
        rendered_at,
        displayed_on,
    )
    date_width = draw.textlength(date_text, font=header_font)
    update_width = draw.textlength(update_text, font=header_font)
    header_right = PORTRAIT_WIDTH - 24
    header_block_width = max(date_width, update_width)
    title = _fit_text(
        draw,
        household_name,
        font=title_font,
        max_width=max(160, PORTRAIT_WIDTH - 64 - header_block_width),
    )
    draw.text((24, 18), title, fill=BLACK, font=title_font)
    draw.text(
        (header_right - date_width, 16),
        date_text,
        fill=BLACK,
        font=header_font,
    )
    draw.text(
        (header_right - update_width, 45),
        update_text,
        fill=BLACK,
        font=header_font,
    )
    draw.line((24, 92, PORTRAIT_WIDTH - 24, 92), fill=BLACK, width=2)

    row_top = 106
    row_height = 30
    name_x = 24
    quantity_x = 262
    status_x = 356
    content_right = PORTRAIT_WIDTH - 20
    for index, item in enumerate(visible_items):
        y = row_top + index * row_height
        color = _status_color(item.status)
        marker = "●"
        draw.text((name_x, y + 1), marker, fill=color, font=detail_font)
        name = _fit_text(
            draw,
            item.name,
            font=item_font,
            max_width=quantity_x - name_x - 48,
        )
        draw.text((name_x + 26, y), name, fill=BLACK, font=item_font)
        quantity = _fit_text(
            draw,
            item.quantity_text,
            font=detail_font,
            max_width=status_x - quantity_x - 12,
        )
        status_text = _fit_text(
            draw,
            item.status_text,
            font=detail_font,
            max_width=content_right - status_x,
        )
        draw.text((quantity_x, y + 2), quantity, fill=BLACK, font=detail_font)
        draw.text((status_x, y + 2), status_text, fill=color, font=detail_font)

    if not visible_items:
        empty_font = _font(22, bold=True)
        empty_text = "冰箱里还没有食材"
        empty_width = draw.textlength(empty_text, font=empty_font)
        draw.text(
            ((PORTRAIT_WIDTH - empty_width) / 2, 210),
            empty_text,
            fill=BLACK,
            font=empty_font,
        )

    hidden_count = max(0, len(all_items) - MAX_DISPLAY_ITEMS)
    footer_top = 566
    draw.line(
        (24, footer_top, PORTRAIT_WIDTH - 24, footer_top),
        fill=BLACK,
        width=2,
    )
    qr_left = 24
    qr_top = 592
    qr_size = 132
    code_image = _prepare_mini_program_code(
        mini_program_code_png,
        size=qr_size,
    )
    if code_image is not None:
        portrait.paste(code_image, (qr_left, qr_top))
    else:
        draw.rectangle(
            (qr_left, qr_top, qr_left + qr_size, qr_top + qr_size),
            outline=BLACK,
            width=2,
        )
        placeholder = "设备码待生成"
        placeholder_font = _font(14)
        placeholder_width = draw.textlength(
            placeholder,
            font=placeholder_font,
        )
        draw.text(
            (
                qr_left + (qr_size - placeholder_width) / 2,
                qr_top + qr_size / 2 - 10,
            ),
            placeholder,
            fill=BLACK,
            font=placeholder_font,
        )

    qr_caption = f"共 {len(all_items)} 项食材"
    qr_caption_width = draw.textlength(qr_caption, font=footer_font)
    draw.text(
        (qr_left + (qr_size - qr_caption_width) / 2, 732),
        qr_caption,
        fill=BLACK,
        font=footer_font,
    )
    qr_detail = f"另有 {hidden_count} 项未显示" if hidden_count else "扫码管理"
    qr_detail_width = draw.textlength(qr_detail, font=detail_font)
    draw.text(
        (qr_left + (qr_size - qr_detail_width) / 2, 756),
        qr_detail,
        fill=BLACK,
        font=detail_font,
    )

    todo_left = 176
    todo_top = 588
    todo_right = PORTRAIT_WIDTH - 24
    todo_bottom = 772
    draw.rounded_rectangle(
        (todo_left, todo_top, todo_right, todo_bottom),
        radius=12,
        fill=WHITE,
        outline=BLACK,
        width=2,
    )
    draw.rectangle(
        (todo_left + 2, todo_top + 12, todo_left + 9, todo_bottom - 12),
        fill=YELLOW,
    )
    todo_title_font = _font(TODO_TITLE_FONT_SIZE, bold=True)
    todo_item_font = _font(TODO_ITEM_FONT_SIZE)
    todo_note_font = _font(TODO_NOTE_FONT_SIZE)
    draw.text((194, 600), "待办", fill=RED, font=todo_title_font)

    if visible_todos:
        for index, todo in enumerate(visible_todos):
            y = 637 + index * 34
            draw.rectangle((191, y + 3, 203, y + 15), outline=BLACK, width=2)
            todo_text = _fit_text(
                draw,
                todo,
                font=todo_item_font,
                max_width=todo_right - 216 - 12,
            )
            draw.text((216, y), todo_text, fill=RED, font=todo_item_font)
    else:
        draw.text((194, 650), "暂无待办", fill=RED, font=todo_item_font)

    hidden_todos = max(0, len(all_todos) - MAX_DISPLAY_TODOS)
    if hidden_todos:
        draw.text(
            (194, 744),
            f"还有 {hidden_todos} 项，请扫码查看",
            fill=RED,
            font=todo_note_font,
        )

    # GDEM075F53 的传输分辨率固定为 800x480。外壳把屏幕顺时针竖放，
    # 因此服务端先按 480x800 排版，再逆时针旋转为面板原生帧。
    image = portrait.transpose(Image.Transpose.ROTATE_90)

    return _to_four_colors(image)


def render_almanac_image(
    almanac: AlmanacDay,
    weather: "WeatherSummary | None" = None,
) -> Image.Image:
    """Render the approved full-screen compact almanac layout."""
    portrait = Image.new("RGB", (PORTRAIT_WIDTH, PORTRAIT_HEIGHT), WHITE)
    draw = ImageDraw.Draw(portrait)

    date_font = _font(25, bold=True)
    weekday_font = _font(23)
    day_font = _font(148, bold=True)
    lunar_font = _font(38, bold=True)
    ganzhi_font = _font(22)
    note_font = _font(20, bold=True)
    badge_font = _font(34, bold=True)
    item_font = _font(28, bold=True)
    chong_font = _font(23, bold=True)
    disclaimer_font = _font(15)

    date_text = almanac.displayed_on.strftime("%Y年%m月%d日")
    if weather is None:
        draw.text((24, 20), date_text, fill=BLACK, font=date_font)
        weekday_width = draw.textlength(almanac.weekday, font=weekday_font)
        draw.text(
            (PORTRAIT_WIDTH - 24 - weekday_width, 23),
            almanac.weekday,
            fill=BLACK,
            font=weekday_font,
        )
    else:
        weather_title_font = _font(22, bold=True)
        weather_detail_font = _font(16)
        compact_date_font = _font(18, bold=True)
        compact_weekday_font = _font(16)
        weather_title = _fit_text(
            draw,
            f"{weather.location_name}  {weather.condition_text}",
            font=weather_title_font,
            max_width=270,
        )
        detail_parts = [f"{weather.temp_min}~{weather.temp_max}℃"]
        if weather.precip_probability is not None:
            detail_parts.append(f"降雨 {weather.precip_probability}%")
        draw.text((24, 10), weather_title, fill=BLACK, font=weather_title_font)
        draw.text(
            (24, 42),
            " · ".join(detail_parts),
            fill=RED,
            font=weather_detail_font,
        )
        date_width = draw.textlength(date_text, font=compact_date_font)
        weekday_width = draw.textlength(
            almanac.weekday,
            font=compact_weekday_font,
        )
        draw.text(
            (PORTRAIT_WIDTH - 24 - date_width, 11),
            date_text,
            fill=BLACK,
            font=compact_date_font,
        )
        draw.text(
            (PORTRAIT_WIDTH - 24 - weekday_width, 42),
            almanac.weekday,
            fill=BLACK,
            font=compact_weekday_font,
        )
    draw.line((24, 70, PORTRAIT_WIDTH - 24, 70), fill=BLACK, width=2)

    day_text = str(almanac.displayed_on.day)
    _center_text(draw, day_text, y=67, font=day_font, fill=RED)
    _center_text(
        draw,
        f"农历 {almanac.lunar_date}",
        y=236,
        font=lunar_font,
        fill=BLACK,
    )
    _center_text(draw, almanac.ganzhi, y=294, font=ganzhi_font, fill=BLACK)
    note_parts = [f"生肖 {almanac.zodiac}"]
    if almanac.seasonal_note:
        note_parts.append(almanac.seasonal_note)
    _center_text(
        draw,
        " · ".join(note_parts),
        y=334,
        font=note_font,
        fill=RED if almanac.seasonal_note else BLACK,
    )

    cards = (
        (24, 382, 228, 654, YELLOW, "宜", almanac.yi),
        (252, 382, 456, 654, RED, "忌", almanac.ji),
    )
    for left, top, right, bottom, color, label, items in cards:
        draw.rounded_rectangle(
            (left, top, right, bottom),
            radius=18,
            fill=WHITE,
            outline=color,
            width=4,
        )
        badge_left = (left + right) // 2 - 31
        draw.ellipse(
            (badge_left, top + 20, badge_left + 62, top + 82),
            fill=color,
        )
        _center_text(
            draw,
            label,
            y=top + 28,
            font=badge_font,
            fill=WHITE,
            left=left,
            right=right,
        )
        for index, item in enumerate(items):
            fitted = _fit_text(
                draw,
                item,
                font=item_font,
                max_width=right - left - 24,
            )
            _center_text(
                draw,
                fitted,
                y=top + 100 + index * 39,
                font=item_font,
                fill=BLACK,
                left=left,
                right=right,
            )

    draw.rounded_rectangle(
        (24, 678, PORTRAIT_WIDTH - 24, 738),
        radius=14,
        fill=WHITE,
        outline=RED,
        width=3,
    )
    _center_text(
        draw,
        almanac.chong_sha,
        y=693,
        font=chong_font,
        fill=RED,
        left=24,
        right=PORTRAIT_WIDTH - 24,
    )
    _center_text(
        draw,
        almanac.disclaimer,
        y=758,
        font=disclaimer_font,
        fill=BLACK,
    )

    native = portrait.transpose(Image.Transpose.ROTATE_90)
    return _to_four_colors(native)


def _market_price_text(item: "MarketSnapshotItem") -> str:
    if item.price is None:
        return "--"
    prefix = {"USD": "$", "CNY": "¥", "HKD": "HK$"}.get(
        item.currency,
        f"{item.currency} ",
    )
    absolute = abs(item.price)
    decimal_places = 4 if absolute < 1 else 2
    return f"{prefix}{item.price:,.{decimal_places}f}"


def _market_change_text(item: "MarketSnapshotItem") -> str:
    if item.change_percent is None:
        return "--"
    return f"{item.change_percent:+.2f}%"


def render_market_image(snapshot: "MarketSnapshot") -> Image.Image:
    """Render the six-row household market dashboard."""
    portrait = Image.new("RGB", (PORTRAIT_WIDTH, PORTRAIT_HEIGHT), WHITE)
    draw = ImageDraw.Draw(portrait)

    title_font = _font(33, bold=True)
    header_font = _font(16)
    name_font = _font(24, bold=True)
    symbol_font = _font(15)
    price_font = _font(28, bold=True)
    change_font = _font(22, bold=True)
    status_font = _font(14, bold=True)
    footer_font = _font(14)

    draw.rectangle((24, 21, 31, 60), fill=RED)
    draw.text((43, 18), "行情看板", fill=BLACK, font=title_font)
    local_updated_at = display_datetime(snapshot.updated_at)
    date_text = local_updated_at.strftime("%Y-%m-%d")
    update_text = f"更新 {local_updated_at.strftime('%H:%M')}"
    date_width = draw.textlength(date_text, font=header_font)
    update_width = draw.textlength(update_text, font=header_font)
    draw.text((456 - date_width, 18), date_text, fill=BLACK, font=header_font)
    draw.text((456 - update_width, 45), update_text, fill=BLACK, font=header_font)
    draw.line((24, 82, 456, 82), fill=BLACK, width=3)
    draw.line((24, 86, 148, 86), fill=YELLOW, width=4)

    visible_items = snapshot.items[:6]
    row_top = 98
    row_height = 104
    left = 24
    right = 456
    type_labels = {
        "crypto": "数字货币",
        "us_stock": "美股",
        "cn_stock": "A股",
        "hk_stock": "港股",
        "index": "指数",
    }
    for index, item in enumerate(visible_items):
        top = row_top + index * row_height
        bottom = top + 90
        is_up = item.change_percent is not None and item.change_percent > 0
        color = RED if is_up else BLACK
        draw.rounded_rectangle(
            (left, top, right, bottom),
            radius=12,
            fill=WHITE,
            outline=BLACK,
            width=2,
        )
        draw.rounded_rectangle(
            (left, top, left + 8, bottom),
            radius=4,
            fill=color,
        )
        name = _fit_text(draw, item.name, font=name_font, max_width=170)
        symbol_text = f"{item.symbol} · {type_labels[item.asset_type.value]}"
        symbol = _fit_text(draw, symbol_text, font=symbol_font, max_width=178)
        draw.text((43, top + 11), name, fill=BLACK, font=name_font)
        draw.text((43, top + 53), symbol, fill=BLACK, font=symbol_font)

        price = _fit_text(
            draw,
            _market_price_text(item),
            font=price_font,
            max_width=228,
        )
        price_width = draw.textlength(price, font=price_font)
        draw.text(
            (right - 14 - price_width, top + 7),
            price,
            fill=BLACK,
            font=price_font,
        )

        change = _market_change_text(item)
        change_width = draw.textlength(change, font=change_font)
        draw.text(
            (right - 14 - change_width, top + 48),
            change,
            fill=color,
            font=change_font,
        )
        status_width = draw.textlength(item.status, font=status_font)
        badge_right = right - 28 - change_width
        badge_left = badge_right - status_width - 18
        draw.rounded_rectangle(
            (badge_left, top + 52, badge_right, top + 77),
            radius=8,
            fill=WHITE,
            outline=YELLOW,
            width=3,
        )
        draw.text(
            (badge_left + 9, top + 54),
            item.status,
            fill=BLACK,
            font=status_font,
        )

    if not visible_items:
        empty_font = _font(24, bold=True)
        _center_text(
            draw,
            "请在小程序添加自选资产",
            y=340,
            font=empty_font,
            fill=BLACK,
            left=24,
            right=456,
        )

    draw.line((24, 728, 456, 728), fill=BLACK, width=2)
    footer_text = f"每{snapshot.refresh_minutes}分钟更新 · 行情仅供参考"
    _center_text(
        draw,
        footer_text,
        y=748,
        font=footer_font,
        fill=BLACK,
        left=24,
        right=456,
    )
    native = portrait.transpose(Image.Transpose.ROTATE_90)
    return _to_four_colors(native)


def native_image_to_portrait(image: Image.Image) -> Image.Image:
    """Convert an 800x480 native frame back to the upright 480x800 view."""
    if image.size != (DISPLAY_WIDTH, DISPLAY_HEIGHT):
        raise ValueError(
            f"expected {DISPLAY_WIDTH}x{DISPLAY_HEIGHT}, "
            f"got {image.size[0]}x{image.size[1]}"
        )
    return image.transpose(Image.Transpose.ROTATE_270)


def _prepare_mini_program_code(
    raw_png: bytes | None,
    *,
    size: int,
) -> Image.Image | None:
    if not raw_png:
        return None
    try:
        with Image.open(BytesIO(raw_png)) as source:
            source.load()
            rgba = source.convert("RGBA")
    except (UnidentifiedImageError, OSError, ValueError):
        return None
    background = Image.new("RGBA", rgba.size, "white")
    background.alpha_composite(rgba)
    grayscale = ImageOps.grayscale(background.convert("RGB"))
    black_white = grayscale.point(lambda value: 0 if value < 180 else 255, "1")
    return black_white.resize((size, size), Image.Resampling.NEAREST).convert(
        "RGB"
    )


def render_display_preview(
    *,
    household_name: str,
    items: Iterable[DisplayFoodItem],
    rendered_at: datetime,
    output_path: Path,
    displayed_on: date | None = None,
    mini_program_code_png: bytes | None = None,
) -> Path:
    four_color_image = render_display_image(
        household_name=household_name,
        items=items,
        rendered_at=rendered_at,
        displayed_on=displayed_on,
        mini_program_code_png=mini_program_code_png,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    four_color_image.save(output_path, format="PNG", optimize=True)
    return output_path


def demo_items(today: date) -> list[DisplayFoodItem]:
    del today
    return [
        DisplayFoodItem("鲜牛奶", "1 盒", FoodStatus.EAT_TODAY, "今天吃"),
        DisplayFoodItem("菠菜", "1 把", FoodStatus.OVERDUE, "超期 1 天"),
        DisplayFoodItem("西红柿", "3 个", FoodStatus.EAT_SOON, "剩 2 天"),
        DisplayFoodItem("鸡胸肉", "2 袋", FoodStatus.EAT_SOON, "剩 3 天"),
        DisplayFoodItem("酸奶", "4 杯", FoodStatus.NORMAL, "剩 6 天"),
        DisplayFoodItem("鸡蛋", "8 个", FoodStatus.NORMAL, "剩 8 天"),
        DisplayFoodItem("速冻水饺", "1 袋", FoodStatus.NORMAL, "剩 20 天"),
        DisplayFoodItem("胡萝卜", "2 根", FoodStatus.NORMAL, "剩 10 天"),
        DisplayFoodItem("西兰花", "1 颗", FoodStatus.NORMAL, "剩 4 天"),
        DisplayFoodItem("蓝莓", "2 盒", FoodStatus.NORMAL, "剩 5 天"),
        DisplayFoodItem("豆腐", "1 盒", FoodStatus.NORMAL, "剩 5 天"),
        DisplayFoodItem("香菇", "1 袋", FoodStatus.NORMAL, "剩 6 天"),
        DisplayFoodItem("黄瓜", "2 根", FoodStatus.NORMAL, "剩 7 天"),
        DisplayFoodItem("苹果", "4 个", FoodStatus.NORMAL, "剩 12 天"),
        DisplayFoodItem("奶酪片", "6 片", FoodStatus.NORMAL, "剩 15 天"),
        DisplayFoodItem("玉米", "2 根", FoodStatus.NORMAL, "剩 18 天"),
        DisplayFoodItem("冷冻虾仁", "1 袋", FoodStatus.NORMAL, "剩 25 天"),
        DisplayFoodItem("番茄酱", "1 瓶", FoodStatus.NO_DATE, "待补日期"),
    ]
