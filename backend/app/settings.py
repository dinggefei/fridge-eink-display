from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEVELOPMENT_TOKEN_SECRET = (
    "development-only-token-secret-change-before-production"
)


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str = "postgresql+asyncpg://rfm:rfm@127.0.0.1:5432/rfm"
    device_code: str
    device_secret: str
    device_api_base_url: str = "http://127.0.0.1:8000"
    device_provisioning_ttl_seconds: int = Field(default=600, ge=60, le=1800)
    device_secret_encryption_key: SecretStr = SecretStr("")
    inventory_data_path: Path = Path("data/inventory.json")
    auth_token_secret: SecretStr = SecretStr(DEVELOPMENT_TOKEN_SECRET)
    auth_token_ttl_seconds: int = 30 * 24 * 60 * 60
    wechat_app_id: str = ""
    wechat_app_secret: SecretStr = SecretStr("")
    wechat_api_base_url: str = "https://api.weixin.qq.com"
    mini_program_code_page: str = "pages/device/index"
    mini_program_code_width: int = Field(default=280, ge=280, le=1280)
    reminder_delivery_mode: Literal["disabled", "mock", "wechat"] = "mock"
    wechat_reminder_template_id: str = ""
    wechat_reminder_items_key: str = "thing1"
    wechat_reminder_count_key: str = "number2"
    wechat_reminder_date_key: str = "date3"
    wechat_reminder_page: str = "pages/today/index"
    allow_dev_login: bool = True
    database_inventory_enabled: bool = False
    recognition_provider: Literal["mock", "hunyuan"] = "mock"
    recognition_execution_mode: Literal["inline", "worker"] = "inline"
    recognition_upload_dir: Path = Path("data/recognition")
    recognition_max_image_bytes: int = 5 * 1024 * 1024
    recognition_max_images: int = 9
    recognition_image_concurrency: int = Field(default=2, ge=1, le=4)
    recognition_task_ttl_seconds: int = 24 * 60 * 60
    display_photo_storage_backend: Literal["local", "cos"] = "local"
    display_photo_local_dir: Path = Path("data/display-photos")
    display_photo_max_image_bytes: int = 5 * 1024 * 1024
    display_photo_max_photos: int = Field(default=6, ge=1, le=20)
    market_data_provider: Literal["mock", "live"] = "mock"
    market_security_provider: Literal["twelve_data", "longbridge"] = "twelve_data"
    twelve_data_api_key: SecretStr = SecretStr("")
    twelve_data_api_base_url: str = "https://api.twelvedata.com"
    coingecko_api_key: SecretStr = SecretStr("")
    coingecko_api_key_type: Literal["demo", "pro"] = "demo"
    coingecko_api_base_url: str = "https://api.coingecko.com/api/v3"
    longbridge_app_key: SecretStr = SecretStr("")
    longbridge_app_secret: SecretStr = SecretStr("")
    longbridge_access_token: SecretStr = SecretStr("")
    longbridge_http_url: str = "https://openapi.longbridge.com"
    longbridge_quote_ws_url: str = "wss://openapi-quote.longbridge.com/v2"
    longbridge_enable_overnight: bool = False
    longbridge_paper_trading: bool = True
    market_data_timeout_seconds: float = Field(default=12.0, gt=0, le=60)
    weather_data_provider: Literal["disabled", "mock", "qweather"] = "disabled"
    weather_refresh_hours: int = Field(default=3, ge=1, le=24)
    weather_failure_retry_minutes: int = Field(default=15, ge=5, le=120)
    weather_stale_hours: int = Field(default=12, ge=3, le=48)
    weather_data_timeout_seconds: float = Field(default=12.0, gt=0, le=60)
    qweather_api_host: str = ""
    qweather_credential_id: str = ""
    qweather_developer_id: str = ""
    qweather_project_id: str = ""
    qweather_private_key_base64: SecretStr = SecretStr("")
    ota_firmware_storage_dir: Path = Path("data/firmware-releases")
    ota_max_signed_binary_bytes: int = Field(
        default=3 * 1024 * 1024,
        gt=512,
        le=16 * 1024 * 1024,
    )
    cos_region: str = ""
    cos_bucket: str = ""
    cos_secret_id: SecretStr = SecretStr("")
    cos_secret_key: SecretStr = SecretStr("")
    hunyuan_api_key: SecretStr = SecretStr("")
    hunyuan_base_url: str = "https://tokenhub.tencentmaas.com/v1"
    hunyuan_text_model: str = "hy3"
    hunyuan_vision_model: str = "hy-vision-2.0-instruct"
    hunyuan_timeout_seconds: float = 60.0

    @model_validator(mode="after")
    def validate_production_secrets(self) -> "Settings":
        if self.app_env.lower() != "production":
            return self
        if self.allow_dev_login:
            raise ValueError("ALLOW_DEV_LOGIN must be false in production")
        if not self.wechat_app_id or not self.wechat_app_secret.get_secret_value():
            raise ValueError(
                "WECHAT_APP_ID and WECHAT_APP_SECRET are required in production"
            )
        token_secret = self.auth_token_secret.get_secret_value()
        if len(token_secret) < 32 or token_secret == DEVELOPMENT_TOKEN_SECRET:
            raise ValueError(
                "AUTH_TOKEN_SECRET must be replaced with at least 32 characters"
            )
        if len(self.device_secret_encryption_key.get_secret_value()) < 32:
            raise ValueError(
                "DEVICE_SECRET_ENCRYPTION_KEY must contain at least 32 characters"
            )
        if (
            self.recognition_provider == "hunyuan"
            and not self.hunyuan_api_key.get_secret_value()
        ):
            raise ValueError(
                "HUNYUAN_API_KEY is required when "
                "RECOGNITION_PROVIDER=hunyuan"
            )
        if self.recognition_provider == "mock":
            raise ValueError(
                "RECOGNITION_PROVIDER=mock is not allowed in production"
            )
        if self.reminder_delivery_mode == "mock":
            raise ValueError(
                "REMINDER_DELIVERY_MODE=mock is not allowed in production"
            )
        if (
            self.reminder_delivery_mode == "wechat"
            and not self.wechat_reminder_template_id
        ):
            raise ValueError(
                "WECHAT_REMINDER_TEMPLATE_ID is required when "
                "REMINDER_DELIVERY_MODE=wechat"
            )
        if self.display_photo_storage_backend != "cos":
            raise ValueError(
                "DISPLAY_PHOTO_STORAGE_BACKEND=cos is required in production"
            )
        if (
            not self.cos_region
            or not self.cos_bucket
            or not self.cos_secret_id.get_secret_value()
            or not self.cos_secret_key.get_secret_value()
        ):
            raise ValueError(
                "COS_REGION, COS_BUCKET, COS_SECRET_ID and COS_SECRET_KEY "
                "are required for production display photo storage"
            )
        if not self.ota_firmware_storage_dir.is_absolute():
            raise ValueError(
                "OTA_FIRMWARE_STORAGE_DIR must be an absolute path in production"
            )
        if self.weather_data_provider == "mock":
            raise ValueError(
                "WEATHER_DATA_PROVIDER=mock is not allowed in production"
            )
        if self.weather_data_provider == "qweather" and not all(
            (
                self.qweather_api_host,
                self.qweather_credential_id,
                self.qweather_developer_id,
                self.qweather_project_id,
                self.qweather_private_key_base64.get_secret_value(),
            )
        ):
            raise ValueError(
                "QWeather API host and JWT credentials are required when "
                "WEATHER_DATA_PROVIDER=qweather"
            )
        if (
            self.market_data_provider == "live"
            and self.market_security_provider == "longbridge"
            and not all(
                (
                    self.longbridge_app_key.get_secret_value(),
                    self.longbridge_app_secret.get_secret_value(),
                    self.longbridge_access_token.get_secret_value(),
                )
            )
        ):
            raise ValueError(
                "Longbridge App Key, App Secret and Access Token are required "
                "when MARKET_SECURITY_PROVIDER=longbridge"
            )
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
