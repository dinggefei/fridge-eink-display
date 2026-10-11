from datetime import date
from pathlib import Path
import argparse

from app.services.almanac import calculate_almanac
from app.services.display_renderer import (
    native_image_to_portrait,
    render_almanac_image,
)
from app.services.weather import WeatherSummary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render a real-date four-color almanac preview."
    )
    parser.add_argument(
        "--date",
        type=date.fromisoformat,
        default=date.today(),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("../docs/assets/almanac_preview_f53.png"),
    )
    parser.add_argument(
        "--portrait-output",
        type=Path,
        default=Path("../docs/assets/almanac_preview_f53_portrait.png"),
    )
    parser.add_argument("--weather-city")
    parser.add_argument("--weather-condition", default="多云")
    parser.add_argument("--weather-min", type=int, default=18)
    parser.add_argument("--weather-max", type=int, default=27)
    parser.add_argument("--weather-rain", type=int, default=20)
    args = parser.parse_args()

    weather = None
    if args.weather_city:
        weather = WeatherSummary(
            location_name=args.weather_city,
            condition_text=args.weather_condition,
            temp_min=args.weather_min,
            temp_max=args.weather_max,
            precip_probability=args.weather_rain,
        )
    native = render_almanac_image(calculate_almanac(args.date), weather)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.portrait_output.parent.mkdir(parents=True, exist_ok=True)
    native.save(args.output, format="PNG", optimize=True)
    native_image_to_portrait(native).save(
        args.portrait_output,
        format="PNG",
        optimize=True,
    )
    print(args.output.resolve())
    print(args.portrait_output.resolve())


if __name__ == "__main__":
    main()
