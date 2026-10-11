"""Add household collaboration, reminders, restoration and recognition metrics.

Revision ID: 0005_household_features
Revises: 0004_device_provisioning
Create Date: 2026-07-31
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0005_household_features"
down_revision: str | None = "0004_device_provisioning"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "household_invitations",
        sa.Column("household_id", sa.String(length=36), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("used_by_user_id", sa.String(length=36)),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["used_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code_hash"),
    )
    op.create_index(
        "ix_household_invitations_household_id",
        "household_invitations",
        ["household_id"],
    )
    op.create_index(
        "ix_household_invitations_expires_at",
        "household_invitations",
        ["expires_at"],
    )

    op.add_column(
        "reminder_preferences",
        sa.Column(
            "subscription_grants",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "reminder_preferences",
        sa.Column("last_reminded_on", sa.Date()),
    )
    op.create_table(
        "subscription_deliveries",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("household_id", sa.String(length=36), nullable=False),
        sa.Column("template_id", sa.String(length=128)),
        sa.Column(
            "scheduled_for",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "item_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("error_message", sa.Text()),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["households.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_subscription_deliveries_user_scheduled",
        "subscription_deliveries",
        ["user_id", "scheduled_for"],
    )

    op.add_column(
        "inventory_events",
        sa.Column("reversed_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "inventory_events",
        sa.Column("reversed_by_user_id", sa.String(length=36)),
    )
    op.create_foreign_key(
        "fk_inventory_events_reversed_by_user_id_users",
        "inventory_events",
        "users",
        ["reversed_by_user_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.add_column(
        "import_tasks",
        sa.Column("recognition_duration_ms", sa.Integer()),
    )
    for column_name in (
        "recognition_image_count",
        "recognized_action_count",
        "confirmed_action_count",
        "corrected_action_count",
    ):
        op.add_column(
            "import_tasks",
            sa.Column(
                column_name,
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )
    op.add_column(
        "import_tasks",
        sa.Column("average_confidence", sa.Numeric(5, 4)),
    )

    op.create_index(
        "uq_shelf_life_preference_household_rule",
        "shelf_life_preferences",
        ["household_id", "category", "location"],
        unique=True,
        postgresql_where=sa.text("user_id IS NULL"),
        sqlite_where=sa.text("user_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_shelf_life_preference_household_rule",
        table_name="shelf_life_preferences",
    )
    op.drop_column("import_tasks", "average_confidence")
    op.drop_column("import_tasks", "corrected_action_count")
    op.drop_column("import_tasks", "confirmed_action_count")
    op.drop_column("import_tasks", "recognized_action_count")
    op.drop_column("import_tasks", "recognition_duration_ms")
    op.drop_column("import_tasks", "recognition_image_count")
    op.drop_constraint(
        "fk_inventory_events_reversed_by_user_id_users",
        "inventory_events",
        type_="foreignkey",
    )
    op.drop_column("inventory_events", "reversed_by_user_id")
    op.drop_column("inventory_events", "reversed_at")
    op.drop_index(
        "ix_subscription_deliveries_user_scheduled",
        table_name="subscription_deliveries",
    )
    op.drop_table("subscription_deliveries")
    op.drop_column("reminder_preferences", "last_reminded_on")
    op.drop_column("reminder_preferences", "subscription_grants")
    op.drop_index(
        "ix_household_invitations_expires_at",
        table_name="household_invitations",
    )
    op.drop_index(
        "ix_household_invitations_household_id",
        table_name="household_invitations",
    )
    op.drop_table("household_invitations")
