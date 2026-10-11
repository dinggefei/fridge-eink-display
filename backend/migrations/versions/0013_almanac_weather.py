"""Add household weather settings and cached daily forecast.

Revision ID: 0013_almanac_weather
Revises: 0012_market_display
Create Date: 2026-09-10
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0013_almanac_weather"
down_revision: str | None = "0012_market_display"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "households",
        sa.Column(
            "almanac_weather_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column("households", sa.Column("weather_location_id", sa.String(32)))
    op.add_column("households", sa.Column("weather_location_name", sa.String(80)))
    op.add_column("households", sa.Column("weather_adm1", sa.String(80)))
    op.add_column(
        "households",
        sa.Column("weather_latitude", sa.Numeric(precision=8, scale=5)),
    )
    op.add_column(
        "households",
        sa.Column("weather_longitude", sa.Numeric(precision=8, scale=5)),
    )
    op.add_column(
        "households",
        sa.Column("weather_condition_text", sa.String(40)),
    )
    op.add_column("households", sa.Column("weather_temp_min", sa.Integer()))
    op.add_column("households", sa.Column("weather_temp_max", sa.Integer()))
    op.add_column(
        "households",
        sa.Column("weather_precip_probability", sa.Integer()),
    )
    op.add_column("households", sa.Column("weather_forecast_date", sa.Date()))
    op.add_column(
        "households",
        sa.Column("weather_last_attempted_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "households",
        sa.Column("weather_last_success_at", sa.DateTime(timezone=True)),
    )
    op.create_check_constraint(
        "ck_households_weather_precip_probability",
        "households",
        "weather_precip_probability IS NULL OR "
        "weather_precip_probability BETWEEN 0 AND 100",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_households_weather_precip_probability",
        "households",
        type_="check",
    )
    for column in (
        "weather_last_success_at",
        "weather_last_attempted_at",
        "weather_forecast_date",
        "weather_precip_probability",
        "weather_temp_max",
        "weather_temp_min",
        "weather_condition_text",
        "weather_longitude",
        "weather_latitude",
        "weather_adm1",
        "weather_location_name",
        "weather_location_id",
        "almanac_weather_enabled",
    ):
        op.drop_column("households", column)
