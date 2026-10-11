"""Track a stable revision for each household inventory.

Revision ID: 0002_household_revision
Revises: 0001_initial
Create Date: 2026-07-27
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0002_household_revision"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "households",
        sa.Column(
            "inventory_revision",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )


def downgrade() -> None:
    op.drop_column("households", "inventory_revision")
