from datetime import datetime, timedelta, timezone
from io import BytesIO

from PIL import Image

from app.db.models import (
    DisplayMode,
    DisplayPhoto,
    DisplayPhotoStatus,
    Household,
)
from app.services.device_frame import FRAME_SIZE, load_album_frame
from app.services.display_photos import (
    DISPLAY_PALETTE,
    active_display_photo,
    process_display_photo,
)


def _image_bytes(
    *,
    size: tuple[int, int],
    color: tuple[int, int, int],
    image_format: str,
) -> bytes:
    output = BytesIO()
    Image.new("RGB", size, color).save(output, format=image_format)
    return output.getvalue()


def test_display_photo_is_center_cropped_and_converted_to_four_colors() -> None:
    processed = process_display_photo(
        _image_bytes(size=(1200, 800), color=(70, 150, 100), image_format="JPEG"),
        max_bytes=5 * 1024 * 1024,
    )

    with Image.open(BytesIO(processed.png_bytes)) as image:
        assert image.size == (480, 800)
        colors = image.convert("RGB").getcolors(maxcolors=480 * 800)
        assert colors is not None
        assert {color for _, color in colors} <= set(DISPLAY_PALETTE)

    frame = load_album_frame(processed.png_bytes)
    assert len(frame.data) == FRAME_SIZE
    assert frame.version.startswith("photo-")


def test_rotation_uses_selected_photo_as_anchor() -> None:
    start = datetime(2026, 9, 3, 0, 0, tzinfo=timezone.utc)
    household = Household(
        id="household-1",
        name="家庭",
        admin_user_id="user-1",
        display_mode=DisplayMode.ALBUM,
        photo_rotation_hours=6,
        photo_rotation_started_at=start,
        active_display_photo_id="photo-2",
    )
    photos = [
        DisplayPhoto(
            id=f"photo-{index}",
            household_id="household-1",
            status=DisplayPhotoStatus.CONFIRMED,
            sequence=index - 1,
            object_key=f"{index}.png",
            original_filename=f"{index}.png",
            sha256="0" * 64,
            byte_size=1,
            created_at=start,
            updated_at=start,
        )
        for index in range(1, 4)
    ]

    assert active_display_photo(household, photos, now=start).id == "photo-2"
    assert active_display_photo(
        household,
        photos,
        now=start + timedelta(hours=6),
    ).id == "photo-3"
    assert active_display_photo(
        household,
        photos,
        now=start + timedelta(hours=12),
    ).id == "photo-1"
