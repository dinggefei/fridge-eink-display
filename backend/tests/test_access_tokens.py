from __future__ import annotations

import pytest

from app.services.access_tokens import (
    InvalidAccessToken,
    create_access_token,
    decode_access_token,
)
from app.settings import get_settings


@pytest.fixture(autouse=True)
def token_settings(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(
        "AUTH_TOKEN_SECRET",
        "test-secret-with-at-least-thirty-two-characters",
    )
    monkeypatch.setenv("AUTH_TOKEN_TTL_SECONDS", "60")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_access_token_round_trip() -> None:
    token = create_access_token("user-123", now=1_000)

    claims = decode_access_token(token, now=1_001)

    assert claims.user_id == "user-123"
    assert claims.expires_at == 1_060


def test_access_token_rejects_tampering() -> None:
    token = create_access_token("user-123", now=1_000)
    payload, signature = token.split(".")
    tampered = f"{payload[:-1]}A.{signature}"

    with pytest.raises(InvalidAccessToken, match="signature"):
        decode_access_token(tampered, now=1_001)


def test_access_token_rejects_expiration() -> None:
    token = create_access_token("user-123", now=1_000)

    with pytest.raises(InvalidAccessToken, match="expired"):
        decode_access_token(token, now=1_060)
