"""Add private display album and household display mode.

Revision ID: 0008_display_album
Revises: 0007_display_todos
Create Date: 2026-09-03
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0008_display_album"
down_revision: str | None = "0007_display_todos"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "households",
        sa.Column(
            "display_mode",
            sa.Enum(
                "inventory",
                "album",
                name="display_mode",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
            server_default="inventory",
        ),
    )
    op.add_column(
        "households",
        sa.Column(
            "photo_rotation_hours",
            sa.Integer(),
            nullable=False,
            server_default="6",
        ),
    )
    op.add_column(
        "households",
        sa.Column("photo_rotation_started_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "households",
        sa.Column("active_display_photo_id", sa.String(length=36)),
    )
    op.create_check_constraint(
        "ck_households_photo_rotation_hours",
        "households",
        "photo_rotation_hours IN (6, 12, 24)",
    )

    op.create_table(
        "display_photos",
        sa.Column("household_id", sa.String(length=36), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36)),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "confirmed",
                name="display_photo_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("object_key", sa.String(length=500), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column(
            "content_type",
            sa.String(length=50),
            nullable=False,
            server_default="image/png",
        ),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False, server_default="480"),
        sa.Column("height", sa.Integer(), nullable=False, server_default="800"),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("sequence >= 0", name="ck_display_photos_sequence"),
        sa.CheckConstraint("byte_size > 0", name="ck_display_photos_byte_size"),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["households.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_display_photos_household_id",
        "display_photos",
        ["household_id"],
    )
    op.create_index(
        "ix_display_photos_household_status_sequence",
        "display_photos",
        ["household_id", "status", "sequence"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_display_photos_household_status_sequence",
        table_name="display_photos",
    )
    op.drop_index(
        "ix_display_photos_household_id",
        table_name="display_photos",
    )
    op.drop_table("display_photos")
    op.drop_constraint(
        "ck_households_photo_rotation_hours",
        "households",
        type_="check",
    )
    op.drop_column("households", "active_display_photo_id")
    op.drop_column("households", "photo_rotation_started_at")
    op.drop_column("households", "photo_rotation_hours")
    op.drop_column("households", "display_mode")
