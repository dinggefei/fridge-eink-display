"""Add per-device secrets, provisioning sessions and mini program codes.

Revision ID: 0004_device_provisioning
Revises: 0003_recognition_tasks
Create Date: 2026-07-29
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0004_device_provisioning"
down_revision: str | None = "0003_recognition_tasks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "devices",
        sa.Column("device_secret_ciphertext", sa.Text()),
    )
    op.add_column(
        "devices",
        sa.Column(
            "secret_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column(
        "devices",
        sa.Column("mini_program_code_png", sa.LargeBinary()),
    )
    op.add_column(
        "devices",
        sa.Column(
            "mini_program_code_updated_at",
            sa.DateTime(timezone=True),
        ),
    )
    op.create_table(
        "device_provisioning_sessions",
        sa.Column("device_id", sa.String(length=36), nullable=False),
        sa.Column("household_id", sa.String(length=36), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("challenge_hash", sa.String(length=64), nullable=False),
        sa.Column("binding_token_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'completed', 'cancelled', 'expired')",
            name="ck_device_provisioning_sessions_status",
        ),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["households.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_device_provisioning_sessions_device_status",
        "device_provisioning_sessions",
        ["device_id", "status"],
    )
    op.create_index(
        "ix_device_provisioning_sessions_expires_at",
        "device_provisioning_sessions",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_device_provisioning_sessions_expires_at",
        table_name="device_provisioning_sessions",
    )
    op.drop_index(
        "ix_device_provisioning_sessions_device_status",
        table_name="device_provisioning_sessions",
    )
    op.drop_table("device_provisioning_sessions")
    op.drop_column("devices", "mini_program_code_updated_at")
    op.drop_column("devices", "mini_program_code_png")
    op.drop_column("devices", "secret_version")
    op.drop_column("devices", "device_secret_ciphertext")
