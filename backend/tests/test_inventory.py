import unittest
from datetime import date
from decimal import Decimal

from app.domain.inventory import (
    FoodBatch,
    FoodStatus,
    StorageLocation,
    allocate_fefo,
    calculate_food_status,
    sort_batches_for_display,
)


TODAY = date(2026, 7, 26)


def make_batch(
    batch_id: str,
    *,
    quantity: str = "1",
    suggested_use_by: date | None,
) -> FoodBatch:
    return FoodBatch(
        batch_id=batch_id,
        name=batch_id,
        quantity=Decimal(quantity),
        unit="盒",
        location=StorageLocation.REFRIGERATED,
        stocked_on=date(2026, 7, 20),
        suggested_use_by=suggested_use_by,
    )


class FoodStatusTests(unittest.TestCase):
    def test_prd_status_boundaries(self) -> None:
        cases = [
            (date(2026, 7, 30), FoodStatus.NORMAL),
            (date(2026, 7, 29), FoodStatus.EAT_SOON),
            (TODAY, FoodStatus.EAT_TODAY),
            (date(2026, 7, 25), FoodStatus.OVERDUE),
            (None, FoodStatus.NO_DATE),
        ]

        for suggested_use_by, expected in cases:
            with self.subTest(suggested_use_by=suggested_use_by):
                self.assertEqual(
                    calculate_food_status(suggested_use_by, today=TODAY),
                    expected,
                )

    def test_display_priority(self) -> None:
        batches = [
            make_batch("no-date", suggested_use_by=None),
            make_batch("normal", suggested_use_by=date(2026, 8, 1)),
            make_batch("soon", suggested_use_by=date(2026, 7, 28)),
            make_batch("overdue", suggested_use_by=date(2026, 7, 25)),
            make_batch("today", suggested_use_by=TODAY),
        ]

        ordered = sort_batches_for_display(batches, today=TODAY)

        self.assertEqual(
            [batch.batch_id for batch in ordered],
            ["today", "overdue", "soon", "normal", "no-date"],
        )


class FefoTests(unittest.TestCase):
    def test_deduction_uses_earliest_expiry_first(self) -> None:
        batches = [
            make_batch(
                "later",
                quantity="3",
                suggested_use_by=date(2026, 8, 5),
            ),
            make_batch(
                "earlier",
                quantity="2",
                suggested_use_by=date(2026, 7, 28),
            ),
        ]

        deductions = allocate_fefo(batches, Decimal("4"))

        self.assertEqual(
            [(item.batch_id, item.quantity) for item in deductions],
            [
                ("earlier", Decimal("2")),
                ("later", Decimal("2")),
            ],
        )

    def test_deduction_rejects_insufficient_inventory(self) -> None:
        batches = [
            make_batch(
                "only",
                quantity="1",
                suggested_use_by=date(2026, 7, 28),
            )
        ]

        with self.assertRaisesRegex(ValueError, "exceeds available"):
            allocate_fefo(batches, Decimal("2"))


if __name__ == "__main__":
    unittest.main()
