"""Add the household market dashboard and quote cache.

Revision ID: 0012_market_display
Revises: 0011_short_rotation
Create Date: 2026-09-09
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0012_market_display"
down_revision: str | None = "0011_short_rotation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("display_mode", "households", type_="check")
    op.create_check_constraint(
        "display_mode",
        "households",
        "display_mode IN ('inventory', 'almanac', 'album', 'market')",
    )
    op.add_column(
        "households",
        sa.Column(
            "market_refresh_minutes",
            sa.Integer(),
            nullable=False,
            server_default="30",
        ),
    )
    op.add_column(
        "households",
        sa.Column(
            "market_night_pause",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.create_check_constraint(
        "ck_households_market_refresh_minutes",
        "households",
        "market_refresh_minutes IN (15, 30, 60)",
    )

    op.create_table(
        "market_assets",
        sa.Column("household_id", sa.String(length=36), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36)),
        sa.Column(
            "asset_type",
            sa.Enum(
                "crypto",
                "us_stock",
                "cn_stock",
                "hk_stock",
                "index",
                name="market_asset_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("provider_symbol", sa.String(length=64), nullable=False),
        sa.Column("provider_mic_code", sa.String(length=16)),
        sa.Column("sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_price", sa.Numeric(precision=24, scale=8)),
        sa.Column("last_change_percent", sa.Numeric(precision=12, scale=4)),
        sa.Column("last_status", sa.String(length=16)),
        sa.Column("last_quoted_at", sa.DateTime(timezone=True)),
        sa.Column("last_fetched_at", sa.DateTime(timezone=True)),
        sa.Column(
            "quote_stale",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("sequence >= 0", name="ck_market_assets_sequence"),
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
        sa.UniqueConstraint(
            "household_id",
            "asset_type",
            "symbol",
            name="uq_market_assets_household_type_symbol",
        ),
    )
    op.create_index(
        "ix_market_assets_household_id",
        "market_assets",
        ["household_id"],
    )
    op.create_index(
        "ix_market_assets_household_sequence",
        "market_assets",
        ["household_id", "sequence"],
    )


def downgrade() -> None:
    op.execute(
        "UPDATE households SET display_mode = 'inventory' "
        "WHERE display_mode = 'market'"
    )
    op.drop_index(
        "ix_market_assets_household_sequence",
        table_name="market_assets",
    )
    op.drop_index("ix_market_assets_household_id", table_name="market_assets")
    op.drop_table("market_assets")
    op.drop_constraint(
        "ck_households_market_refresh_minutes",
        "households",
        type_="check",
    )
    op.drop_column("households", "market_night_pause")
    op.drop_column("households", "market_refresh_minutes")
    op.drop_constraint("display_mode", "households", type_="check")
    op.create_check_constraint(
        "display_mode",
        "households",
        "display_mode IN ('inventory', 'almanac', 'album')",
    )
