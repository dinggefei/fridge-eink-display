"""Add optional per-device display mode override.

Revision ID: 0017_device_display_mode
Revises: 0016_timetable_orientation
Create Date: 2026-09-20
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0017_device_display_mode"
down_revision: str | None = "0016_timetable_orientation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "devices",
        sa.Column("display_mode_override", sa.String(length=9), nullable=True),
    )
    op.create_check_constraint(
        "device_display_mode_override",
        "devices",
        "display_mode_override IS NULL OR display_mode_override IN "
        "('inventory', 'almanac', 'album', 'market', 'weather', 'timetable')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "device_display_mode_override",
        "devices",
        type_="check",
    )
    op.drop_column("devices", "display_mode_override")
