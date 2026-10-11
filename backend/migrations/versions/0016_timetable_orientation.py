"""Add portrait and landscape timetable display orientation.

Revision ID: 0016_timetable_orientation
Revises: 0015_timetable_display
Create Date: 2026-09-18
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0016_timetable_orientation"
down_revision: str | None = "0015_timetable_display"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "households",
        sa.Column(
            "timetable_orientation",
            sa.String(length=16),
            nullable=False,
            server_default="portrait",
        ),
    )
    op.create_check_constraint(
        "ck_households_timetable_orientation",
        "households",
        "timetable_orientation IN ('portrait', 'landscape')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_households_timetable_orientation",
        "households",
        type_="check",
    )
    op.drop_column("households", "timetable_orientation")
