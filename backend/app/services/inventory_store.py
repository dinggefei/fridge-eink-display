from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Iterable
from uuid import uuid4

from app.domain.inventory import StorageLocation
from app.settings import get_settings


@dataclass(frozen=True, slots=True)
class InventoryItem:
    id: str
    name: str
    quantity: Decimal
    unit: str
    location: StorageLocation
    stocked_on: date
    suggested_use_by: date | None


@dataclass(frozen=True, slots=True)
class InventoryItemValues:
    name: str
    quantity: Decimal
    unit: str
    location: StorageLocation
    stocked_on: date
    suggested_use_by: date | None


@dataclass(frozen=True, slots=True)
class InventorySnapshot:
    household_name: str
    revision: int
    updated_at: datetime
    items: tuple[InventoryItem, ...]
    display_todos: tuple[str, ...] = ()


class InventoryStore:
    """Small durable store for local end-to-end development.

    The API and domain objects are intentionally independent of the storage
    format, so this implementation can later be replaced by PostgreSQL without
    changing the miniapp or device-frame contract.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.RLock()
        with self._lock:
            if not self._path.exists():
                self._write(_default_snapshot())
            self._snapshot = self._read()

    def snapshot(self) -> InventorySnapshot:
        with self._lock:
            return self._snapshot

    def add(self, values: InventoryItemValues) -> InventoryItem:
        with self._lock:
            item = InventoryItem(id=str(uuid4()), **asdict(values))
            self._commit((*self._snapshot.items, item))
            return item

    def replace(self, item_id: str, values: InventoryItemValues) -> InventoryItem:
        with self._lock:
            replacement = InventoryItem(id=item_id, **asdict(values))
            items = list(self._snapshot.items)
            for index, item in enumerate(items):
                if item.id == item_id:
                    items[index] = replacement
                    self._commit(items)
                    return replacement
            raise KeyError(item_id)

    def delete(self, item_id: str) -> None:
        with self._lock:
            items = tuple(item for item in self._snapshot.items if item.id != item_id)
            if len(items) == len(self._snapshot.items):
                raise KeyError(item_id)
            self._commit(items)

    def rename_household(self, name: str) -> InventorySnapshot:
        with self._lock:
            self._snapshot = InventorySnapshot(
                household_name=name,
                revision=self._snapshot.revision + 1,
                updated_at=datetime.now(UTC),
                items=self._snapshot.items,
                display_todos=self._snapshot.display_todos,
            )
            self._write(self._snapshot)
            return self._snapshot

    def _commit(self, items: Iterable[InventoryItem]) -> None:
        self._snapshot = InventorySnapshot(
            household_name=self._snapshot.household_name,
            revision=self._snapshot.revision + 1,
            updated_at=datetime.now(UTC),
            items=tuple(items),
            display_todos=self._snapshot.display_todos,
        )
        self._write(self._snapshot)

    def _read(self) -> InventorySnapshot:
        payload = json.loads(self._path.read_text(encoding="utf-8"))
        return InventorySnapshot(
            household_name=str(payload["household_name"]),
            revision=int(payload["revision"]),
            updated_at=datetime.fromisoformat(payload["updated_at"]),
            display_todos=tuple(
                str(item) for item in payload.get("display_todos", [])
            ),
            items=tuple(
                InventoryItem(
                    id=str(item["id"]),
                    name=str(item["name"]),
                    quantity=Decimal(str(item["quantity"])),
                    unit=str(item["unit"]),
                    location=StorageLocation(item["location"]),
                    stocked_on=date.fromisoformat(item["stocked_on"]),
                    suggested_use_by=(
                        date.fromisoformat(item["suggested_use_by"])
                        if item.get("suggested_use_by")
                        else None
                    ),
                )
                for item in payload["items"]
            ),
        )

    def _write(self, snapshot: InventorySnapshot) -> None:
        payload = {
            "household_name": snapshot.household_name,
            "revision": snapshot.revision,
            "updated_at": snapshot.updated_at.isoformat(),
            "display_todos": list(snapshot.display_todos),
            "items": [
                {
                    "id": item.id,
                    "name": item.name,
                    "quantity": str(item.quantity),
                    "unit": item.unit,
                    "location": item.location.value,
                    "stocked_on": item.stocked_on.isoformat(),
                    "suggested_use_by": (
                        item.suggested_use_by.isoformat()
                        if item.suggested_use_by
                        else None
                    ),
                }
                for item in snapshot.items
            ],
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self._path.with_name(f"{self._path.name}.tmp")
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(self._path)


def _default_snapshot() -> InventorySnapshot:
    today = date.today()
    stocked_on = today - timedelta(days=3)
    defaults = (
        ("seed-milk", "鲜牛奶", "1", "盒", StorageLocation.REFRIGERATED, today),
        (
            "seed-spinach",
            "菠菜",
            "1",
            "把",
            StorageLocation.REFRIGERATED,
            today - timedelta(days=1),
        ),
        (
            "seed-tomato",
            "西红柿",
            "3",
            "个",
            StorageLocation.REFRIGERATED,
            today + timedelta(days=2),
        ),
        (
            "seed-chicken",
            "鸡胸肉",
            "2",
            "袋",
            StorageLocation.FROZEN,
            today + timedelta(days=3),
        ),
        (
            "seed-yogurt",
            "酸奶",
            "4",
            "杯",
            StorageLocation.REFRIGERATED,
            today + timedelta(days=6),
        ),
        (
            "seed-eggs",
            "鸡蛋",
            "8",
            "个",
            StorageLocation.REFRIGERATED,
            today + timedelta(days=8),
        ),
        (
            "seed-dumplings",
            "速冻水饺",
            "1",
            "袋",
            StorageLocation.FROZEN,
            today + timedelta(days=20),
        ),
        (
            "seed-carrot",
            "胡萝卜",
            "2",
            "根",
            StorageLocation.REFRIGERATED,
            today + timedelta(days=10),
        ),
    )
    return InventorySnapshot(
        household_name="我的冰箱",
        revision=1,
        updated_at=datetime.now(UTC),
        items=tuple(
            InventoryItem(
                id=item_id,
                name=name,
                quantity=Decimal(quantity),
                unit=unit,
                location=location,
                stocked_on=stocked_on,
                suggested_use_by=suggested_use_by,
            )
            for item_id, name, quantity, unit, location, suggested_use_by in defaults
        ),
    )


@lru_cache(maxsize=1)
def get_inventory_store() -> InventoryStore:
    return InventoryStore(get_settings().inventory_data_path)
