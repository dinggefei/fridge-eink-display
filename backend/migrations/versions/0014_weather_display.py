"""Seven-day weather display mode and shared forecast cache."""
import sqlalchemy as sa
from alembic import op

revision = "0014_weather_display"
down_revision = "0013_almanac_weather"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("display_mode", "households", type_="check")
    op.create_check_constraint("display_mode", "households",
        "display_mode IN ('inventory', 'almanac', 'album', 'market', 'weather')")
    op.create_table("weather_forecast_cache",
        sa.Column("cache_key", sa.String(96), primary_key=True),
        sa.Column("days", sa.JSON(), nullable=False),
        sa.Column("last_attempted_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)))


def downgrade():
    op.execute("UPDATE households SET display_mode = 'inventory' WHERE display_mode = 'weather'")
    op.drop_table("weather_forecast_cache")
    op.drop_constraint("display_mode", "households", type_="check")
    op.create_check_constraint("display_mode", "households",
        "display_mode IN ('inventory', 'almanac', 'album', 'market')")
