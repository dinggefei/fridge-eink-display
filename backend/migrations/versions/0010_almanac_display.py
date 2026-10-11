"""Add the independent almanac display mode.

Revision ID: 0010_almanac_display
Revises: 0009_device_ota
Create Date: 2026-09-07
"""

from typing import Sequence

from alembic import op


revision: str = "0010_almanac_display"
down_revision: str | None = "0009_device_ota"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("display_mode", "households", type_="check")
    op.create_check_constraint(
        "display_mode",
        "households",
        "display_mode IN ('inventory', 'almanac', 'album')",
    )


def downgrade() -> None:
    op.execute(
        "UPDATE households SET display_mode = 'inventory' "
        "WHERE display_mode = 'almanac'"
    )
    op.drop_constraint("display_mode", "households", type_="check")
    op.create_check_constraint(
        "display_mode",
        "households",
        "display_mode IN ('inventory', 'album')",
    )
