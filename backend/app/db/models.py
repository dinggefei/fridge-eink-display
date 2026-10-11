from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin, new_id, utc_now
from app.domain.inventory import FoodStatus, StorageLocation


def string_enum(enum_type: type[StrEnum], name: str) -> Enum:
    return Enum(
        enum_type,
        name=name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda values: [item.value for item in values],
    )


class MembershipRole(StrEnum):
    ADMIN = "admin"
    MEMBER = "member"


class MembershipStatus(StrEnum):
    ACTIVE = "active"
    INVITED = "invited"
    REMOVED = "removed"


class DeviceStatus(StrEnum):
    UNBOUND = "unbound"
    ONLINE = "online"
    OFFLINE = "offline"


class FirmwareReleaseStatus(StrEnum):
    DRAFT = "draft"
    CANARY = "canary"
    PUBLISHED = "published"
    PAUSED = "paused"


class FirmwareUpdateEventType(StrEnum):
    DOWNLOADED = "downloaded"
    INSTALLED = "installed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class DeviceProvisioningStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class ImportTaskStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    NEEDS_CONFIRMATION = "needs_confirmation"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class InventoryAction(StrEnum):
    ADD = "add"
    EDIT = "edit"
    CONSUME = "consume"
    DISCARD = "discard"
    RESTORE = "restore"
    DELETE = "delete"


class DisplayMode(StrEnum):
    WEATHER = "weather"
    INVENTORY = "inventory"
    ALMANAC = "almanac"
    ALBUM = "album"
    MARKET = "market"
    TIMETABLE = "timetable"


class MarketAssetType(StrEnum):
    CRYPTO = "crypto"
    US_STOCK = "us_stock"
    CN_STOCK = "cn_stock"
    HK_STOCK = "hk_stock"
    INDEX = "index"


class DisplayPhotoStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"


class User(Base, IdMixin, TimestampMixin):
    __tablename__ = "users"

    openid: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    nickname: Mapped[str | None] = mapped_column(String(100))
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    recent_household_id: Mapped[str | None] = mapped_column(String(36))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Household(Base, IdMixin, TimestampMixin):
    __tablename__ = "households"
    __table_args__ = (
        CheckConstraint(
            "reminder_threshold_days BETWEEN 1 AND 7",
            name="ck_households_reminder_threshold_days",
        ),
        CheckConstraint(
            "photo_rotation_hours IN (1, 3, 6, 12, 24)",
            name="ck_households_photo_rotation_hours",
        ),
        CheckConstraint(
            "market_refresh_minutes IN (15, 30, 60)",
            name="ck_households_market_refresh_minutes",
        ),
        CheckConstraint(
            "timetable_orientation IN ('portrait', 'landscape')",
            name="ck_households_timetable_orientation",
        ),
        CheckConstraint(
            "weather_precip_probability IS NULL OR "
            "weather_precip_probability BETWEEN 0 AND 100",
            name="ck_households_weather_precip_probability",
        ),
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    admin_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    reminder_threshold_days: Mapped[int] = mapped_column(
        Integer,
        default=3,
        nullable=False,
    )
    include_room_temperature_on_display: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    display_todos: Mapped[list[str]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )
    display_mode: Mapped[DisplayMode] = mapped_column(
        string_enum(DisplayMode, "display_mode"),
        default=DisplayMode.INVENTORY,
        nullable=False,
    )
    timetable_periods: Mapped[list[dict]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )
    timetable_entries: Mapped[list[dict]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )
    timetable_orientation: Mapped[str] = mapped_column(
        String(16),
        default="portrait",
        server_default="portrait",
        nullable=False,
    )
    photo_rotation_hours: Mapped[int] = mapped_column(
        Integer,
        default=6,
        nullable=False,
    )
    photo_rotation_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    active_display_photo_id: Mapped[str | None] = mapped_column(String(36))
    market_refresh_minutes: Mapped[int] = mapped_column(
        Integer,
        default=30,
        nullable=False,
    )
    market_night_pause: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
    almanac_weather_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    weather_location_id: Mapped[str | None] = mapped_column(String(32))
    weather_location_name: Mapped[str | None] = mapped_column(String(80))
    weather_adm1: Mapped[str | None] = mapped_column(String(80))
    weather_latitude: Mapped[Decimal | None] = mapped_column(Numeric(8, 5))
    weather_longitude: Mapped[Decimal | None] = mapped_column(Numeric(8, 5))
    weather_condition_text: Mapped[str | None] = mapped_column(String(40))
    weather_temp_min: Mapped[int | None] = mapped_column(Integer)
    weather_temp_max: Mapped[int | None] = mapped_column(Integer)
    weather_precip_probability: Mapped[int | None] = mapped_column(Integer)
    weather_forecast_date: Mapped[date | None] = mapped_column(Date)
    weather_last_attempted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    weather_last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    inventory_revision: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
    )


class WeatherForecastCache(Base):
    """Shared seven-day forecast per provider and rounded coordinates."""

    __tablename__ = "weather_forecast_cache"
    cache_key: Mapped[str] = mapped_column(String(96), primary_key=True)
    days: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    last_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DisplayPhoto(Base, IdMixin, TimestampMixin):
    __tablename__ = "display_photos"
    __table_args__ = (
        CheckConstraint("sequence >= 0", name="ck_display_photos_sequence"),
        CheckConstraint("byte_size > 0", name="ck_display_photos_byte_size"),
        Index(
            "ix_display_photos_household_status_sequence",
            "household_id",
            "status",
            "sequence",
        ),
    )

    household_id: Mapped[str] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    status: Mapped[DisplayPhotoStatus] = mapped_column(
        string_enum(DisplayPhotoStatus, "display_photo_status"),
        default=DisplayPhotoStatus.PENDING,
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    object_key: Mapped[str] = mapped_column(String(500), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(
        String(50),
        default="image/png",
        nullable=False,
    )
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[int] = mapped_column(Integer, default=480, nullable=False)
    height: Mapped[int] = mapped_column(Integer, default=800, nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MarketAsset(Base, IdMixin, TimestampMixin):
    __tablename__ = "market_assets"
    __table_args__ = (
        CheckConstraint("sequence >= 0", name="ck_market_assets_sequence"),
        UniqueConstraint(
            "household_id",
            "asset_type",
            "symbol",
            name="uq_market_assets_household_type_symbol",
        ),
        Index(
            "ix_market_assets_household_sequence",
            "household_id",
            "sequence",
        ),
    )

    household_id: Mapped[str] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    asset_type: Mapped[MarketAssetType] = mapped_column(
        string_enum(MarketAssetType, "market_asset_type"),
        nullable=False,
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    provider_symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_mic_code: Mapped[str | None] = mapped_column(String(16))
    sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    last_change_percent: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    last_status: Mapped[str | None] = mapped_column(String(16))
    last_quoted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    last_fetched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    quote_stale: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )


class Membership(Base):
    __tablename__ = "memberships"

    household_id: Mapped[str] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role: Mapped[MembershipRole] = mapped_column(
        string_enum(MembershipRole, "membership_role"),
        nullable=False,
    )
    status: Mapped[MembershipStatus] = mapped_column(
        string_enum(MembershipStatus, "membership_status"),
        default=MembershipStatus.ACTIVE,
        nullable=False,
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )


class Device(Base, IdMixin, TimestampMixin):
    __tablename__ = "devices"

    device_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    device_secret_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    device_secret_ciphertext: Mapped[str | None] = mapped_column(Text)
    secret_version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
    )
    household_id: Mapped[str | None] = mapped_column(
        ForeignKey("households.id", ondelete="SET NULL"),
        index=True,
    )
    panel_model: Mapped[str] = mapped_column(
        String(64),
        default="GDEM075F53",
        nullable=False,
    )
    orientation: Mapped[str] = mapped_column(
        String(16),
        default="portrait",
        nullable=False,
    )
    display_mode_override: Mapped[DisplayMode | None] = mapped_column(
        string_enum(DisplayMode, "device_display_mode_override"),
        nullable=True,
    )
    poll_interval_seconds: Mapped[int] = mapped_column(
        Integer,
        default=300,
        nullable=False,
    )
    frame_version: Mapped[str | None] = mapped_column(String(64))
    frame_etag: Mapped[str | None] = mapped_column(String(128))
    mini_program_code_png: Mapped[bytes | None] = mapped_column(LargeBinary)
    mini_program_code_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    status: Mapped[DeviceStatus] = mapped_column(
        string_enum(DeviceStatus, "device_status"),
        default=DeviceStatus.UNBOUND,
        nullable=False,
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    firmware_version: Mapped[str | None] = mapped_column(String(32))
    firmware_build_number: Mapped[int | None] = mapped_column(Integer)
    firmware_hardware: Mapped[str | None] = mapped_column(String(64))
    last_ota_check_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    last_ota_result: Mapped[str | None] = mapped_column(String(32))
    last_ota_error: Mapped[str | None] = mapped_column(String(255))
    last_ota_release_id: Mapped[str | None] = mapped_column(
        ForeignKey("firmware_releases.id", ondelete="SET NULL")
    )


class FirmwareRelease(Base, IdMixin, TimestampMixin):
    __tablename__ = "firmware_releases"
    __table_args__ = (
        CheckConstraint(
            "build_number > 0",
            name="ck_firmware_releases_build_number",
        ),
        CheckConstraint(
            "min_build_number >= 0",
            name="ck_firmware_releases_min_build_number",
        ),
        CheckConstraint(
            "rollout_percent BETWEEN 0 AND 100",
            name="ck_firmware_releases_rollout_percent",
        ),
        CheckConstraint(
            "binary_size > 512",
            name="ck_firmware_releases_binary_size",
        ),
        UniqueConstraint(
            "hardware_model",
            "build_number",
            name="uq_firmware_releases_hardware_build",
        ),
    )

    version: Mapped[str] = mapped_column(String(32), nullable=False)
    build_number: Mapped[int] = mapped_column(Integer, nullable=False)
    hardware_model: Mapped[str] = mapped_column(String(64), nullable=False)
    min_build_number: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    binary_path: Mapped[str] = mapped_column(String(500), nullable=False)
    binary_size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[FirmwareReleaseStatus] = mapped_column(
        string_enum(FirmwareReleaseStatus, "firmware_release_status"),
        default=FirmwareReleaseStatus.DRAFT,
        nullable=False,
    )
    rollout_percent: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    target_device_codes: Mapped[list[str]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )
    release_notes: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )


class FirmwareUpdateEvent(Base, IdMixin):
    __tablename__ = "firmware_update_events"
    __table_args__ = (
        Index(
            "ix_firmware_update_events_device_created",
            "device_id",
            "created_at",
        ),
    )

    device_id: Mapped[str] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=False,
    )
    release_id: Mapped[str] = mapped_column(
        ForeignKey("firmware_releases.id", ondelete="CASCADE"),
        nullable=False,
    )
    event: Mapped[FirmwareUpdateEventType] = mapped_column(
        string_enum(FirmwareUpdateEventType, "firmware_update_event_type"),
        nullable=False,
    )
    detail: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )


class DeviceProvisioningSession(Base, IdMixin, TimestampMixin):
    __tablename__ = "device_provisioning_sessions"
    __table_args__ = (
        Index(
            "ix_device_provisioning_sessions_device_status",
            "device_id",
            "status",
        ),
    )

    device_id: Mapped[str] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=False,
    )
    household_id: Mapped[str] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    challenge_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    binding_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[DeviceProvisioningStatus] = mapped_column(
        string_enum(
            DeviceProvisioningStatus,
            "device_provisioning_status",
        ),
        default=DeviceProvisioningStatus.PENDING,
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )


class FoodBatch(Base, IdMixin, TimestampMixin):
    __tablename__ = "food_batches"
    __table_args__ = (
        CheckConstraint("quantity >= 0", name="ck_food_batches_quantity"),
        Index(
            "ix_food_batches_household_location_use_by",
            "household_id",
            "location",
            "suggested_use_by",
        ),
    )

    household_id: Mapped[str] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    standard_name: Mapped[str] = mapped_column(String(200), nullable=False)
    original_name: Mapped[str | None] = mapped_column(String(300))
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    location: Mapped[StorageLocation] = mapped_column(
        string_enum(StorageLocation, "storage_location"),
        nullable=False,
    )
    stocked_on: Mapped[date] = mapped_column(Date, nullable=False)
    suggested_use_by: Mapped[date | None] = mapped_column(Date)
    status: Mapped[FoodStatus] = mapped_column(
        string_enum(FoodStatus, "food_status"),
        nullable=False,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ImportTask(Base, IdMixin, TimestampMixin):
    __tablename__ = "import_tasks"

    household_id: Mapped[str] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    input_text: Mapped[str | None] = mapped_column(Text)
    base_inventory_revision: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )
    status: Mapped[ImportTaskStatus] = mapped_column(
        string_enum(ImportTaskStatus, "import_task_status"),
        default=ImportTaskStatus.PENDING,
        nullable=False,
    )
    recognition_result: Mapped[dict | list | None] = mapped_column(JSON)
    error_message: Mapped[str | None] = mapped_column(Text)
    recognition_duration_ms: Mapped[int | None] = mapped_column(Integer)
    recognition_image_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    recognized_action_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    confirmed_action_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    corrected_action_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    average_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    original_files_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ImportImage(Base, IdMixin, TimestampMixin):
    __tablename__ = "import_images"
    __table_args__ = (
        UniqueConstraint(
            "task_id",
            "sequence",
            name="uq_import_images_task_sequence",
        ),
    )

    task_id: Mapped[str] = mapped_column(
        ForeignKey("import_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(50), nullable=False)
    object_path: Mapped[str] = mapped_column(String(500), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class InventoryEvent(Base):
    __tablename__ = "inventory_events"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_inventory_events_quantity"),
        UniqueConstraint(
            "household_id",
            "idempotency_key",
            name="uq_inventory_events_household_idempotency",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=new_id,
    )
    household_id: Mapped[str] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    batch_id: Mapped[str] = mapped_column(
        ForeignKey("food_batches.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    actor_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    action: Mapped[InventoryAction] = mapped_column(
        string_enum(InventoryAction, "inventory_action"),
        nullable=False,
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    event_data: Mapped[dict | None] = mapped_column("metadata", JSON)
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reversed_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        index=True,
    )


class ReminderPreference(Base, IdMixin, TimestampMixin):
    __tablename__ = "reminder_preferences"
    __table_args__ = (
        CheckConstraint(
            "threshold_days BETWEEN 1 AND 7",
            name="ck_reminder_preferences_threshold_days",
        ),
        UniqueConstraint(
            "user_id",
            "household_id",
            name="uq_reminder_preferences_user_household",
        ),
    )

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    household_id: Mapped[str] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"),
        nullable=False,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    reminder_time: Mapped[time] = mapped_column(
        Time,
        default=lambda: time(hour=20),
        nullable=False,
    )
    threshold_days: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    subscription_grants: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    last_reminded_on: Mapped[date | None] = mapped_column(Date)


class ShelfLifePreference(Base, IdMixin, TimestampMixin):
    __tablename__ = "shelf_life_preferences"
    __table_args__ = (
        CheckConstraint(
            "suggested_days >= 0",
            name="ck_shelf_life_preferences_suggested_days",
        ),
        UniqueConstraint(
            "household_id",
            "user_id",
            "category",
            "location",
            name="uq_shelf_life_preference_scope",
        ),
    )

    household_id: Mapped[str] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    location: Mapped[StorageLocation] = mapped_column(
        string_enum(StorageLocation, "shelf_life_storage_location"),
        nullable=False,
    )
    suggested_days: Mapped[int] = mapped_column(Integer, nullable=False)


class HouseholdInvitation(Base, IdMixin, TimestampMixin):
    __tablename__ = "household_invitations"

    household_id: Mapped[str] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    code_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    used_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )


class SubscriptionDelivery(Base, IdMixin, TimestampMixin):
    __tablename__ = "subscription_deliveries"
    __table_args__ = (
        Index(
            "ix_subscription_deliveries_user_scheduled",
            "user_id",
            "scheduled_for",
        ),
    )

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    household_id: Mapped[str] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"),
        nullable=False,
    )
    template_id: Mapped[str | None] = mapped_column(String(128))
    scheduled_for: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default="pending",
        nullable=False,
    )
    item_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
