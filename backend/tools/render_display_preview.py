from datetime import datetime
from pathlib import Path
import argparse

from app.services.display_renderer import (
    demo_items,
    native_image_to_portrait,
    render_display_image,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render an 800x480 four-color e-paper preview."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("../docs/assets/screen_preview_f53.png"),
    )
    parser.add_argument(
        "--portrait-output",
        type=Path,
        default=Path("../docs/assets/screen_preview_f53_portrait.png"),
    )
    args = parser.parse_args()

    rendered_at = datetime.now()
    native_image = render_display_image(
        household_name="小明的冰箱",
        items=demo_items(rendered_at.date()),
        rendered_at=rendered_at,
        display_todos=("买牛奶", "清理冷藏室", "补充鸡蛋", "倒垃圾"),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.portrait_output.parent.mkdir(parents=True, exist_ok=True)
    native_image.save(args.output, format="PNG", optimize=True)
    native_image_to_portrait(native_image).save(
        args.portrait_output,
        format="PNG",
        optimize=True,
    )
    print(args.output.resolve())
    print(args.portrait_output.resolve())


if __name__ == "__main__":
    main()
