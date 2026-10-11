from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass

from app.settings import get_settings


class InvalidAccessToken(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    user_id: str
    expires_at: int


def _encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(value + padding)
    except (ValueError, TypeError) as error:
        raise InvalidAccessToken("token encoding is invalid") from error


def create_access_token(user_id: str, *, now: int | None = None) -> str:
    settings = get_settings()
    issued_at = int(time.time()) if now is None else now
    payload = {
        "sub": user_id,
        "iat": issued_at,
        "exp": issued_at + settings.auth_token_ttl_seconds,
        "v": 1,
    }
    encoded_payload = _encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    )
    signature = hmac.new(
        settings.auth_token_secret.get_secret_value().encode(),
        encoded_payload.encode(),
        hashlib.sha256,
    ).digest()
    return f"{encoded_payload}.{_encode(signature)}"


def decode_access_token(
    token: str,
    *,
    now: int | None = None,
) -> AccessTokenClaims:
    try:
        encoded_payload, encoded_signature = token.split(".", maxsplit=1)
    except ValueError as error:
        raise InvalidAccessToken("token structure is invalid") from error

    settings = get_settings()
    expected_signature = hmac.new(
        settings.auth_token_secret.get_secret_value().encode(),
        encoded_payload.encode(),
        hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(_decode(encoded_signature), expected_signature):
        raise InvalidAccessToken("token signature is invalid")

    try:
        payload = json.loads(_decode(encoded_payload))
        user_id = str(payload["sub"])
        expires_at = int(payload["exp"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise InvalidAccessToken("token payload is invalid") from error

    current_time = int(time.time()) if now is None else now
    if expires_at <= current_time:
        raise InvalidAccessToken("token has expired")
    if not user_id:
        raise InvalidAccessToken("token user is missing")
    return AccessTokenClaims(user_id=user_id, expires_at=expires_at)
