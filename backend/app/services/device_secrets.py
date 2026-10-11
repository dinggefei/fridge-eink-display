from __future__ import annotations

import base64
import hashlib
import hmac
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.db.models import Device
from app.settings import get_settings


SECRET_ENVELOPE_VERSION = "v1"
SECRET_ENCRYPTION_CONTEXT = b"rfm-device-secret-kek-v1"


class DeviceSecretError(ValueError):
    pass


def device_secret_hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(value + padding)
    except (ValueError, TypeError) as error:
        raise DeviceSecretError("device secret envelope is invalid") from error


def _encryption_key() -> bytes:
    settings = get_settings()
    configured = settings.device_secret_encryption_key.get_secret_value()
    master_secret = (
        configured or settings.auth_token_secret.get_secret_value()
    ).encode("utf-8")
    return hmac.new(
        master_secret,
        SECRET_ENCRYPTION_CONTEXT,
        hashlib.sha256,
    ).digest()


def encrypt_device_secret(secret: str, device_code: str) -> str:
    if len(secret) < 32:
        raise DeviceSecretError("device secret must contain at least 32 characters")
    nonce = os.urandom(12)
    ciphertext = AESGCM(_encryption_key()).encrypt(
        nonce,
        secret.encode("utf-8"),
        device_code.encode("utf-8"),
    )
    return f"{SECRET_ENVELOPE_VERSION}.{_b64encode(nonce + ciphertext)}"


def decrypt_device_secret(ciphertext: str, device_code: str) -> str:
    try:
        version, encoded = ciphertext.split(".", maxsplit=1)
    except ValueError as error:
        raise DeviceSecretError("device secret envelope is invalid") from error
    if version != SECRET_ENVELOPE_VERSION:
        raise DeviceSecretError("device secret envelope version is unsupported")
    raw = _b64decode(encoded)
    if len(raw) < 12 + 16:
        raise DeviceSecretError("device secret envelope is truncated")
    try:
        plaintext = AESGCM(_encryption_key()).decrypt(
            raw[:12],
            raw[12:],
            device_code.encode("utf-8"),
        )
    except (InvalidTag, ValueError) as error:
        raise DeviceSecretError("device secret envelope cannot be decrypted") from error
    try:
        return plaintext.decode("utf-8")
    except UnicodeDecodeError as error:
        raise DeviceSecretError("device secret is not valid UTF-8") from error


def resolve_device_secret(device: Device) -> tuple[str, bool]:
    """Return the device secret and whether a legacy row needs encryption."""
    if device.device_secret_ciphertext:
        secret = decrypt_device_secret(
            device.device_secret_ciphertext,
            device.device_code,
        )
        if not hmac.compare_digest(
            device.device_secret_hash,
            device_secret_hash(secret),
        ):
            raise DeviceSecretError("device secret fingerprint does not match")
        return secret, False

    settings = get_settings()
    legacy_secret = settings.device_secret
    if (
        device.device_code != settings.device_code
        or not legacy_secret
        or not hmac.compare_digest(
            device.device_secret_hash,
            device_secret_hash(legacy_secret),
        )
    ):
        raise DeviceSecretError("device has no usable encrypted secret")
    return legacy_secret, True
