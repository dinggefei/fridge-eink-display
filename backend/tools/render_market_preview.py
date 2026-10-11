from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from app.db.models import MarketAssetType
from app.services.display_renderer import native_image_to_portrait, render_market_image
from app.services.market_data import MarketSnapshot, MarketSnapshotItem


DISPLAYED_AT = datetime(2026, 9, 9, 15, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
DEMO_ITEMS = (
    MarketSnapshotItem("btc", MarketAssetType.CRYPTO, "BTC", "比特币", "USD", Decimal("112480.50"), Decimal("1.82"), "24H", DISPLAYED_AT, False),
    MarketSnapshotItem("eth", MarketAssetType.CRYPTO, "ETH", "以太坊", "USD", Decimal("4398.20"), Decimal("-0.64"), "24H", DISPLAYED_AT, False),
    MarketSnapshotItem("aapl", MarketAssetType.US_STOCK, "AAPL", "苹果", "USD", Decimal("234.16"), Decimal("0.92"), "盘中", DISPLAYED_AT, False),
    MarketSnapshotItem("msft", MarketAssetType.US_STOCK, "MSFT", "微软", "USD", Decimal("512.44"), Decimal("0.31"), "盘中", DISPLAYED_AT, False),
    MarketSnapshotItem("nvda", MarketAssetType.US_STOCK, "NVDA", "英伟达", "USD", Decimal("182.76"), Decimal("-0.25"), "盘中", DISPLAYED_AT, False),
    MarketSnapshotItem("tsla", MarketAssetType.US_STOCK, "TSLA", "特斯拉", "USD", Decimal("346.82"), Decimal("1.08"), "盘中", DISPLAYED_AT, False),
)


def main() -> None:
    output_dir = Path(__file__).resolve().parents[2] / "docs" / "assets"
    output_dir.mkdir(parents=True, exist_ok=True)
    portrait_path = output_dir / "market_preview_f53_portrait.png"
    native_path = output_dir / "market_preview_f53.png"

    native = render_market_image(
        MarketSnapshot(DEMO_ITEMS, DISPLAYED_AT, 30, True)
    )
    portrait = native_image_to_portrait(native)
    portrait.save(portrait_path, format="PNG", optimize=True)
    native.save(native_path, format="PNG", optimize=True)
    print(portrait_path)
    print(native_path)


if __name__ == "__main__":
    main()
