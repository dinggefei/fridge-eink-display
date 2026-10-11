"""Switch GDEM075F53 devices to the portrait display layout.

Revision ID: 0006_portrait_display
Revises: 0005_household_features
Create Date: 2026-08-02
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0006_portrait_display"
down_revision: str | None = "0005_household_features"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text("UPDATE devices SET orientation = 'portrait'")
    )
    op.alter_column(
        "devices",
        "orientation",
        existing_type=sa.String(length=16),
        nullable=False,
        server_default="portrait",
    )


def downgrade() -> None:
    op.execute(
        sa.text("UPDATE devices SET orientation = 'landscape'")
    )
    op.alter_column(
        "devices",
        "orientation",
        existing_type=sa.String(length=16),
        nullable=False,
        server_default="landscape",
    )
