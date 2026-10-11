from datetime import date, datetime, timezone

from PIL import ImageChops

from app.domain.inventory import FoodStatus
from app.services.device_frame import FRAME_SIZE, encode_f53
from app.services.display_renderer import (
    DISPLAY_HEIGHT,
    DISPLAY_WIDTH,
    FOOD_DETAIL_FONT_SIZE,
    FOOD_NAME_FONT_SIZE,
    MAX_DISPLAY_ITEMS,
    MAX_DISPLAY_TODOS,
    PORTRAIT_HEIGHT,
    PORTRAIT_WIDTH,
    RED_RGB,
    TODO_ITEM_FONT_SIZE,
    TODO_NOTE_FONT_SIZE,
    TODO_TITLE_FONT_SIZE,
    DisplayFoodItem,
    current_display_date,
    demo_items,
    display_header_text,
    native_image_to_portrait,
    render_display_image,
)


RENDERED_AT = datetime(2026, 8, 2, 9, 30, tzinfo=timezone.utc)


def test_display_header_converts_utc_to_shanghai_time() -> None:
    date_text, update_text = display_header_text(
        datetime(2026, 8, 11, 15, 44, tzinfo=timezone.utc)
    )

    assert date_text == "2026-08-11"
    assert update_text == "更新 23:44"


def test_display_date_rolls_over_at_shanghai_midnight() -> None:
    utc_after_shanghai_midnight = datetime(
        2026,
        8,
        11,
        16,
        1,
        tzinfo=timezone.utc,
    )

    assert current_display_date(utc_after_shanghai_midnight) == date(
        2026,
        8,
        12,
    )
    assert display_header_text(utc_after_shanghai_midnight) == (
        "2026-08-12",
        "更新 00:01",
    )


def test_portrait_layout_is_returned_in_panel_native_dimensions() -> None:
    native = render_display_image(
        household_name="小明的冰箱",
        items=demo_items(RENDERED_AT.date()),
        rendered_at=RENDERED_AT,
        displayed_on=date(2026, 8, 2),
    )

    assert native.size == (DISPLAY_WIDTH, DISPLAY_HEIGHT)
    assert native_image_to_portrait(native).size == (
        PORTRAIT_WIDTH,
        PORTRAIT_HEIGHT,
    )
    assert len(encode_f53(native)) == FRAME_SIZE


def test_approved_food_and_todo_font_sizes_are_used() -> None:
    assert FOOD_NAME_FONT_SIZE == 20
    assert FOOD_DETAIL_FONT_SIZE == 16
    assert TODO_TITLE_FONT_SIZE == 22
    assert TODO_ITEM_FONT_SIZE == 20
    assert TODO_NOTE_FONT_SIZE == 14


def test_date_and_update_time_are_stacked_in_the_top_right() -> None:
    first = native_image_to_portrait(
        render_display_image(
            household_name="小明的冰箱",
            items=[],
            rendered_at=datetime(2026, 8, 2, 9, 30, tzinfo=timezone.utc),
            displayed_on=date(2026, 8, 2),
        )
    )
    changed = native_image_to_portrait(
        render_display_image(
            household_name="小明的冰箱",
            items=[],
            rendered_at=datetime(2026, 8, 3, 10, 31, tzinfo=timezone.utc),
            displayed_on=date(2026, 8, 3),
        )
    )

    difference = ImageChops.difference(first, changed)
    changed_bounds = difference.getbbox()

    assert changed_bounds is not None
    assert changed_bounds[0] >= 320
    assert changed_bounds[1] < 30
    assert changed_bounds[2] <= PORTRAIT_WIDTH - 20
    assert changed_bounds[3] <= 70


def test_configured_household_name_changes_the_native_frame() -> None:
    first = render_display_image(
        household_name="我的冰箱",
        items=[],
        rendered_at=RENDERED_AT,
    )
    renamed = render_display_image(
        household_name="小明的冰箱",
        items=[],
        rendered_at=RENDERED_AT,
    )

    assert first.tobytes() != renamed.tobytes()
    assert set(first.get_flattened_data()) <= {
        (255, 255, 255),
        (17, 17, 17),
        (196, 43, 37),
        (224, 160, 0),
    }


def test_native_to_portrait_rejects_non_native_image() -> None:
    portrait = render_display_image(
        household_name="我的冰箱",
        items=[],
        rendered_at=RENDERED_AT,
    ).resize((PORTRAIT_WIDTH, PORTRAIT_HEIGHT))

    try:
        native_image_to_portrait(portrait)
    except ValueError as error:
        assert "expected 800x480" in str(error)
    else:
        raise AssertionError("non-native image should be rejected")


def test_portrait_displays_first_fifteen_items_and_hides_the_rest() -> None:
    assert MAX_DISPLAY_ITEMS == 15
    items = [
        DisplayFoodItem(
            name=f"食材 {index + 1}",
            quantity_text="1 份",
            status=FoodStatus.NORMAL,
            status_text="剩 10 天",
        )
        for index in range(16)
    ]
    baseline = render_display_image(
        household_name="我的冰箱",
        items=items,
        rendered_at=RENDERED_AT,
    )

    changed_visible_item = list(items)
    changed_visible_item[14] = DisplayFoodItem(
        name="第十五项已显示",
        quantity_text="1 份",
        status=FoodStatus.NORMAL,
        status_text="剩 10 天",
    )
    visible_changed = render_display_image(
        household_name="我的冰箱",
        items=changed_visible_item,
        rendered_at=RENDERED_AT,
    )

    changed_hidden_item = list(items)
    changed_hidden_item[15] = DisplayFoodItem(
        name="第十六项仍隐藏",
        quantity_text="1 份",
        status=FoodStatus.NORMAL,
        status_text="剩 10 天",
    )
    hidden_changed = render_display_image(
        household_name="我的冰箱",
        items=changed_hidden_item,
        rendered_at=RENDERED_AT,
    )

    assert baseline.tobytes() != visible_changed.tobytes()
    assert baseline.tobytes() == hidden_changed.tobytes()


def test_portrait_displays_three_todos_and_only_counts_the_rest() -> None:
    assert MAX_DISPLAY_TODOS == 3
    todos = ["买牛奶", "清理冷藏室", "补充鸡蛋", "第四条隐藏内容"]
    baseline = render_display_image(
        household_name="我的冰箱",
        items=[],
        rendered_at=RENDERED_AT,
        display_todos=todos,
    )

    visible_changed = render_display_image(
        household_name="我的冰箱",
        items=[],
        rendered_at=RENDERED_AT,
        display_todos=["改买酸奶", *todos[1:]],
    )
    hidden_text_changed = render_display_image(
        household_name="我的冰箱",
        items=[],
        rendered_at=RENDERED_AT,
        display_todos=[*todos[:3], "另一条隐藏内容"],
    )
    hidden_count_changed = render_display_image(
        household_name="我的冰箱",
        items=[],
        rendered_at=RENDERED_AT,
        display_todos=[*todos, "第五条隐藏内容"],
    )

    assert baseline.tobytes() != visible_changed.tobytes()
    assert baseline.tobytes() == hidden_text_changed.tobytes()
    assert baseline.tobytes() != hidden_count_changed.tobytes()

    portrait = native_image_to_portrait(baseline)
    todo_area = portrait.crop((176, 588, PORTRAIT_WIDTH - 24, 772))
    assert sum(pixel == RED_RGB for pixel in todo_area.get_flattened_data()) > 100
