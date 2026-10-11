"""Add recognition draft and temporary image fields.

Revision ID: 0003_recognition_tasks
Revises: 0002_household_revision
Create Date: 2026-07-28
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0003_recognition_tasks"
down_revision: str | None = "0002_household_revision"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("import_tasks", sa.Column("input_text", sa.Text()))
    op.add_column(
        "import_tasks",
        sa.Column(
            "base_inventory_revision",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column(
        "import_tasks",
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "import_images",
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=50), nullable=False),
        sa.Column("object_path", sa.String(length=500), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["import_tasks.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "task_id",
            "sequence",
            name="uq_import_images_task_sequence",
        ),
    )
    op.create_index(
        "ix_import_images_task_id",
        "import_images",
        ["task_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_import_images_task_id", table_name="import_images")
    op.drop_table("import_images")
    op.drop_column("import_tasks", "confirmed_at")
    op.drop_column("import_tasks", "base_inventory_revision")
    op.drop_column("import_tasks", "input_text")
