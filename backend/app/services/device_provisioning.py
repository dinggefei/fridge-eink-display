from __future__ import annotations

import base64
import hashlib
import hmac
import os
import struct
from dataclasses import dataclass
from datetime import datetime

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


PROVISIONING_VERSION = 1
PROVISIONING_MAGIC = b"RFM1"
PROVISIONING_KEY_CONTEXT = b"rfm-provisioning-key-v1"
PROVISIONING_NONCE_BYTES = 12
PROVISIONING_TAG_BYTES = 16


class ProvisioningPayloadError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ProvisioningPayload:
    session_id: str
    binding_token: str
    api_base_url: str
    wifi_ssid: str
    wifi_password: str
    expires_at: int


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(value + padding)
    except (ValueError, TypeError) as error:
        raise ProvisioningPayloadError(
            "provisioning payload encoding is invalid"
        ) from error


def _derive_key(device_secret: str) -> bytes:
    return hmac.new(
        device_secret.encode("utf-8"),
        PROVISIONING_KEY_CONTEXT,
        hashlib.sha256,
    ).digest()


def _aad(device_code: str, challenge_hex: str) -> bytes:
    return f"{device_code}\n{challenge_hex.lower()}".encode("ascii")


def _pack_field(value: str, *, maximum: int) -> bytes:
    raw = value.encode("utf-8")
    if len(raw) > maximum:
        raise ProvisioningPayloadError("provisioning field is too long")
    return struct.pack("!H", len(raw)) + raw


def pack_provisioning_payload(payload: ProvisioningPayload) -> bytes:
    return b"".join(
        (
            PROVISIONING_MAGIC,
            struct.pack("!I", payload.expires_at),
            _pack_field(payload.session_id, maximum=64),
            _pack_field(payload.binding_token, maximum=128),
            _pack_field(payload.api_base_url, maximum=255),
            _pack_field(payload.wifi_ssid, maximum=128),
            _pack_field(payload.wifi_password, maximum=128),
        )
    )


def _read_field(raw: bytes, offset: int) -> tuple[str, int]:
    if offset + 2 > len(raw):
        raise ProvisioningPayloadError("provisioning payload is truncated")
    length = struct.unpack("!H", raw[offset : offset + 2])[0]
    offset += 2
    if offset + length > len(raw):
        raise ProvisioningPayloadError("provisioning payload is truncated")
    try:
        value = raw[offset : offset + length].decode("utf-8")
    except UnicodeDecodeError as error:
        raise ProvisioningPayloadError(
            "provisioning field is not valid UTF-8"
        ) from error
    return value, offset + length


def unpack_provisioning_payload(raw: bytes) -> ProvisioningPayload:
    if len(raw) < 8 or raw[:4] != PROVISIONING_MAGIC:
        raise ProvisioningPayloadError("provisioning payload magic is invalid")
    expires_at = struct.unpack("!I", raw[4:8])[0]
    offset = 8
    fields = []
    for _ in range(5):
        value, offset = _read_field(raw, offset)
        fields.append(value)
    if offset != len(raw):
        raise ProvisioningPayloadError("provisioning payload has trailing bytes")
    return ProvisioningPayload(
        session_id=fields[0],
        binding_token=fields[1],
        api_base_url=fields[2],
        wifi_ssid=fields[3],
        wifi_password=fields[4],
        expires_at=expires_at,
    )


def encrypt_provisioning_payload(
    *,
    device_code: str,
    device_secret: str,
    challenge_hex: str,
    payload: ProvisioningPayload,
) -> tuple[str, str]:
    nonce = os.urandom(PROVISIONING_NONCE_BYTES)
    ciphertext = AESGCM(_derive_key(device_secret)).encrypt(
        nonce,
        pack_provisioning_payload(payload),
        _aad(device_code, challenge_hex),
    )
    envelope = bytes((PROVISIONING_VERSION,)) + nonce + ciphertext
    encoded = _b64encode(envelope)
    return encoded, hashlib.sha256(encoded.encode("ascii")).hexdigest()


def decrypt_provisioning_payload(
    *,
    device_code: str,
    device_secret: str,
    challenge_hex: str,
    encrypted_payload: str,
) -> ProvisioningPayload:
    envelope = _b64decode(encrypted_payload)
    minimum = 1 + PROVISIONING_NONCE_BYTES + PROVISIONING_TAG_BYTES
    if len(envelope) < minimum:
        raise ProvisioningPayloadError("provisioning envelope is truncated")
    if envelope[0] != PROVISIONING_VERSION:
        raise ProvisioningPayloadError(
            "provisioning envelope version is unsupported"
        )
    nonce_start = 1
    ciphertext_start = nonce_start + PROVISIONING_NONCE_BYTES
    try:
        plaintext = AESGCM(_derive_key(device_secret)).decrypt(
            envelope[nonce_start:ciphertext_start],
            envelope[ciphertext_start:],
            _aad(device_code, challenge_hex),
        )
    except (InvalidTag, ValueError) as error:
        raise ProvisioningPayloadError(
            "provisioning envelope authentication failed"
        ) from error
    return unpack_provisioning_payload(plaintext)


def unix_timestamp(value: datetime) -> int:
    return int(value.timestamp())
