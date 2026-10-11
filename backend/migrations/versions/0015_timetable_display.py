"""Add the household weekly timetable display mode.

Revision ID: 0015_timetable_display
Revises: 0014_weather_display
Create Date: 2026-09-16
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0015_timetable_display"
down_revision: str | None = "0014_weather_display"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("display_mode", "households", type_="check")
    op.create_check_constraint(
        "display_mode",
        "households",
        "display_mode IN ('inventory', 'almanac', 'album', 'market', 'weather', 'timetable')",
    )
    op.add_column(
        "households",
        sa.Column("timetable_periods", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "households",
        sa.Column("timetable_entries", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.execute("UPDATE households SET display_mode = 'inventory' WHERE display_mode = 'timetable'")
    op.drop_column("households", "timetable_entries")
    op.drop_column("households", "timetable_periods")
    op.drop_constraint("display_mode", "households", type_="check")
    op.create_check_constraint(
        "display_mode",
        "households",
        "display_mode IN ('inventory', 'almanac', 'album', 'market', 'weather')",
    )
