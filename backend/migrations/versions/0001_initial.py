"""Create the MVP data model.

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-26
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("openid", sa.String(length=128), nullable=False),
        sa.Column("nickname", sa.String(length=100)),
        sa.Column("avatar_url", sa.String(length=500)),
        sa.Column("recent_household_id", sa.String(length=36)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("openid"),
    )

    op.create_table(
        "households",
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("admin_user_id", sa.String(length=36), nullable=False),
        sa.Column("reminder_threshold_days", sa.Integer(), nullable=False),
        sa.Column(
            "include_room_temperature_on_display",
            sa.Boolean(),
            nullable=False,
        ),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "reminder_threshold_days BETWEEN 1 AND 7",
            name="ck_households_reminder_threshold_days",
        ),
        sa.ForeignKeyConstraint(
            ["admin_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_households_admin_user_id",
        "households",
        ["admin_user_id"],
    )

    op.create_table(
        "memberships",
        sa.Column("household_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "role IN ('admin', 'member')",
            name="ck_memberships_role",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'invited', 'removed')",
            name="ck_memberships_status",
        ),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["households.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("household_id", "user_id"),
    )

    op.create_table(
        "devices",
        sa.Column("device_code", sa.String(length=64), nullable=False),
        sa.Column("device_secret_hash", sa.String(length=255), nullable=False),
        sa.Column("household_id", sa.String(length=36)),
        sa.Column(
            "panel_model",
            sa.String(length=64),
            nullable=False,
            server_default="GDEM075F53",
        ),
        sa.Column(
            "orientation",
            sa.String(length=16),
            nullable=False,
            server_default="landscape",
        ),
        sa.Column(
            "poll_interval_seconds",
            sa.Integer(),
            nullable=False,
            server_default="300",
        ),
        sa.Column("frame_version", sa.String(length=64)),
        sa.Column("frame_etag", sa.String(length=128)),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="unbound",
        ),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('unbound', 'online', 'offline')",
            name="ck_devices_status",
        ),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["households.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("device_code"),
    )
    op.create_index("ix_devices_household_id", "devices", ["household_id"])

    op.create_table(
        "food_batches",
        sa.Column("household_id", sa.String(length=36), nullable=False),
        sa.Column("standard_name", sa.String(length=200), nullable=False),
        sa.Column("original_name", sa.String(length=300)),
        sa.Column("quantity", sa.Numeric(12, 3), nullable=False),
        sa.Column("unit", sa.String(length=20), nullable=False),
        sa.Column("location", sa.String(length=32), nullable=False),
        sa.Column("stocked_on", sa.Date(), nullable=False),
        sa.Column("suggested_use_by", sa.Date()),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "location IN ('refrigerated', 'frozen', 'room_temperature')",
            name="ck_food_batches_location",
        ),
        sa.CheckConstraint("quantity >= 0", name="ck_food_batches_quantity"),
        sa.CheckConstraint(
            "status IN ('normal', 'eat_soon', 'eat_today', 'overdue', 'no_date')",
            name="ck_food_batches_status",
        ),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["households.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_food_batches_household_id",
        "food_batches",
        ["household_id"],
    )
    op.create_index(
        "ix_food_batches_household_location_use_by",
        "food_batches",
        ["household_id", "location", "suggested_use_by"],
    )

    op.create_table(
        "import_tasks",
        sa.Column("household_id", sa.String(length=36), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("recognition_result", sa.JSON()),
        sa.Column("error_message", sa.Text()),
        sa.Column("original_files_expires_at", sa.DateTime(timezone=True)),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'needs_confirmation', "
            "'confirmed', 'failed', 'cancelled')",
            name="ck_import_tasks_status",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["households.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_import_tasks_household_id",
        "import_tasks",
        ["household_id"],
    )

    op.create_table(
        "inventory_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("household_id", sa.String(length=36), nullable=False),
        sa.Column("batch_id", sa.String(length=36), nullable=False),
        sa.Column("actor_user_id", sa.String(length=36), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 3), nullable=False),
        sa.Column("idempotency_key", sa.String(length=100), nullable=False),
        sa.Column("metadata", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "action IN ('add', 'edit', 'consume', 'discard', "
            "'restore', 'delete')",
            name="ck_inventory_events_action",
        ),
        sa.CheckConstraint(
            "quantity > 0",
            name="ck_inventory_events_quantity",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["food_batches.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["households.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "household_id",
            "idempotency_key",
            name="uq_inventory_events_household_idempotency",
        ),
    )
    op.create_index(
        "ix_inventory_events_batch_id",
        "inventory_events",
        ["batch_id"],
    )
    op.create_index(
        "ix_inventory_events_created_at",
        "inventory_events",
        ["created_at"],
    )
    op.create_index(
        "ix_inventory_events_household_id",
        "inventory_events",
        ["household_id"],
    )

    op.create_table(
        "reminder_preferences",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("household_id", sa.String(length=36), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("reminder_time", sa.Time(), nullable=False),
        sa.Column("threshold_days", sa.Integer(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "threshold_days BETWEEN 1 AND 7",
            name="ck_reminder_preferences_threshold_days",
        ),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["households.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "household_id",
            name="uq_reminder_preferences_user_household",
        ),
    )

    op.create_table(
        "shelf_life_preferences",
        sa.Column("household_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36)),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("location", sa.String(length=32), nullable=False),
        sa.Column("suggested_days", sa.Integer(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "location IN ('refrigerated', 'frozen', 'room_temperature')",
            name="ck_shelf_life_preferences_location",
        ),
        sa.CheckConstraint(
            "suggested_days >= 0",
            name="ck_shelf_life_preferences_suggested_days",
        ),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["households.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "household_id",
            "user_id",
            "category",
            "location",
            name="uq_shelf_life_preference_scope",
        ),
    )


def downgrade() -> None:
    op.drop_table("shelf_life_preferences")
    op.drop_table("reminder_preferences")
    op.drop_index("ix_inventory_events_household_id", table_name="inventory_events")
    op.drop_index("ix_inventory_events_created_at", table_name="inventory_events")
    op.drop_index("ix_inventory_events_batch_id", table_name="inventory_events")
    op.drop_table("inventory_events")
    op.drop_index("ix_import_tasks_household_id", table_name="import_tasks")
    op.drop_table("import_tasks")
    op.drop_index(
        "ix_food_batches_household_location_use_by",
        table_name="food_batches",
    )
    op.drop_index("ix_food_batches_household_id", table_name="food_batches")
    op.drop_table("food_batches")
    op.drop_index("ix_devices_household_id", table_name="devices")
    op.drop_table("devices")
    op.drop_table("memberships")
    op.drop_index("ix_households_admin_user_id", table_name="households")
    op.drop_table("households")
    op.drop_table("users")
