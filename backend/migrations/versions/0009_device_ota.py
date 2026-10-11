"""Add signed A/B OTA firmware releases and device status.

Revision ID: 0009_device_ota
Revises: 0008_display_album
Create Date: 2026-09-06
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0009_device_ota"
down_revision: str | None = "0008_display_album"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "firmware_releases",
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("build_number", sa.Integer(), nullable=False),
        sa.Column("hardware_model", sa.String(length=64), nullable=False),
        sa.Column(
            "min_build_number",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("binary_path", sa.String(length=500), nullable=False),
        sa.Column("binary_size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "draft",
                "canary",
                "published",
                "paused",
                name="firmware_release_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
            server_default="draft",
        ),
        sa.Column(
            "rollout_percent",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "target_device_codes",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("release_notes", sa.Text()),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "build_number > 0",
            name="ck_firmware_releases_build_number",
        ),
        sa.CheckConstraint(
            "min_build_number >= 0",
            name="ck_firmware_releases_min_build_number",
        ),
        sa.CheckConstraint(
            "rollout_percent BETWEEN 0 AND 100",
            name="ck_firmware_releases_rollout_percent",
        ),
        sa.CheckConstraint(
            "binary_size > 512",
            name="ck_firmware_releases_binary_size",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "hardware_model",
            "build_number",
            name="uq_firmware_releases_hardware_build",
        ),
    )

    op.add_column("devices", sa.Column("firmware_version", sa.String(32)))
    op.add_column("devices", sa.Column("firmware_build_number", sa.Integer()))
    op.add_column("devices", sa.Column("firmware_hardware", sa.String(64)))
    op.add_column(
        "devices",
        sa.Column("last_ota_check_at", sa.DateTime(timezone=True)),
    )
    op.add_column("devices", sa.Column("last_ota_result", sa.String(32)))
    op.add_column("devices", sa.Column("last_ota_error", sa.String(255)))
    op.add_column("devices", sa.Column("last_ota_release_id", sa.String(36)))
    op.create_foreign_key(
        "fk_devices_last_ota_release_id",
        "devices",
        "firmware_releases",
        ["last_ota_release_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "firmware_update_events",
        sa.Column("device_id", sa.String(length=36), nullable=False),
        sa.Column("release_id", sa.String(length=36), nullable=False),
        sa.Column(
            "event",
            sa.Enum(
                "downloaded",
                "installed",
                "failed",
                "rolled_back",
                name="firmware_update_event_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("detail", sa.String(length=255)),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["device_id"], ["devices.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["release_id"], ["firmware_releases.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_firmware_update_events_device_created",
        "firmware_update_events",
        ["device_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_firmware_update_events_device_created",
        table_name="firmware_update_events",
    )
    op.drop_table("firmware_update_events")
    op.drop_constraint(
        "fk_devices_last_ota_release_id",
        "devices",
        type_="foreignkey",
    )
    op.drop_column("devices", "last_ota_release_id")
    op.drop_column("devices", "last_ota_error")
    op.drop_column("devices", "last_ota_result")
    op.drop_column("devices", "last_ota_check_at")
    op.drop_column("devices", "firmware_hardware")
    op.drop_column("devices", "firmware_build_number")
    op.drop_column("devices", "firmware_version")
    op.drop_table("firmware_releases")
