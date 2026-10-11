"""Allow one-hour and three-hour photo rotation intervals.

Revision ID: 0011_short_rotation
Revises: 0010_almanac_display
Create Date: 2026-09-07
"""

from typing import Sequence

from alembic import op


revision: str = "0011_short_rotation"
down_revision: str | None = "0010_almanac_display"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_households_photo_rotation_hours",
        "households",
        type_="check",
    )
    op.create_check_constraint(
        "ck_households_photo_rotation_hours",
        "households",
        "photo_rotation_hours IN (1, 3, 6, 12, 24)",
    )


def downgrade() -> None:
    op.execute(
        "UPDATE households SET photo_rotation_hours = 6 "
        "WHERE photo_rotation_hours IN (1, 3)"
    )
    op.drop_constraint(
        "ck_households_photo_rotation_hours",
        "households",
        type_="check",
    )
    op.create_check_constraint(
        "ck_households_photo_rotation_hours",
        "households",
        "photo_rotation_hours IN (6, 12, 24)",
    )
