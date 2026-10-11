"""Add household tasks shown on the e-paper display.

Revision ID: 0007_display_todos
Revises: 0006_portrait_display
Create Date: 2026-08-31
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0007_display_todos"
down_revision: str | None = "0006_portrait_display"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "households",
        sa.Column(
            "display_todos",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
    )


def downgrade() -> None:
    op.drop_column("households", "display_todos")
