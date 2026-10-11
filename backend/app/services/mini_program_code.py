from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from io import BytesIO

import httpx
from PIL import Image, UnidentifiedImageError

from app.settings import get_settings


class MiniProgramCodeError(RuntimeError):
    pass


@dataclass(slots=True)
class _AccessToken:
    value: str = ""
    expires_at: float = 0


_access_token = _AccessToken()
_access_token_lock = asyncio.Lock()


async def _get_access_token(*, force_refresh: bool = False) -> str:
    settings = get_settings()
    app_secret = settings.wechat_app_secret.get_secret_value()
    if not settings.wechat_app_id or not app_secret:
        raise MiniProgramCodeError("WeChat mini program is not configured")

    async with _access_token_lock:
        now = time.monotonic()
        if (
            not force_refresh
            and _access_token.value
            and _access_token.expires_at > now + 60
        ):
            return _access_token.value
        async with httpx.AsyncClient(timeout=8.0) as client:
            try:
                response = await client.get(
                    f"{settings.wechat_api_base_url.rstrip('/')}/cgi-bin/token",
                    params={
                        "grant_type": "client_credential",
                        "appid": settings.wechat_app_id,
                        "secret": app_secret,
                    },
                )
                response.raise_for_status()
            except httpx.HTTPError as error:
                raise MiniProgramCodeError(
                    "WeChat access token service is unavailable"
                ) from error
        payload = response.json()
        token = payload.get("access_token")
        if not token:
            raise MiniProgramCodeError(
                f"WeChat access token request failed ({payload.get('errcode', 'unknown')})"
            )
        expires_in = max(300, int(payload.get("expires_in", 7200)))
        _access_token.value = str(token)
        _access_token.expires_at = now + expires_in
        return _access_token.value


async def get_wechat_access_token(*, force_refresh: bool = False) -> str:
    """Return the shared mini-program access token for WeChat APIs."""
    return await _get_access_token(force_refresh=force_refresh)


def _normalize_code_png(raw: bytes) -> bytes:
    if len(raw) > 2 * 1024 * 1024:
        raise MiniProgramCodeError("WeChat mini program code image is too large")
    try:
        with Image.open(BytesIO(raw)) as image:
            image.load()
            if image.width < 100 or image.height < 100:
                raise MiniProgramCodeError(
                    "WeChat mini program code image is unexpectedly small"
                )
            normalized = image.convert("RGB")
    except (UnidentifiedImageError, OSError) as error:
        raise MiniProgramCodeError(
            "WeChat returned an invalid mini program code image"
        ) from error
    output = BytesIO()
    normalized.save(output, format="PNG", optimize=True)
    return output.getvalue()


async def generate_mini_program_code(device_code: str) -> bytes:
    if not device_code or len(device_code) > 32 or not device_code.isascii():
        raise MiniProgramCodeError(
            "device code must be 1-32 ASCII characters for WeChat scene"
        )
    settings = get_settings()
    for attempt in range(2):
        token = await _get_access_token(force_refresh=attempt > 0)
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                response = await client.post(
                    (
                        f"{settings.wechat_api_base_url.rstrip('/')}"
                        "/wxa/getwxacodeunlimit"
                    ),
                    params={"access_token": token},
                    json={
                        "scene": device_code,
                        "page": settings.mini_program_code_page,
                        "width": settings.mini_program_code_width,
                        "check_path": False,
                    },
                )
                response.raise_for_status()
            except httpx.HTTPError as error:
                raise MiniProgramCodeError(
                    "WeChat mini program code service is unavailable"
                ) from error
        if response.headers.get("content-type", "").startswith("image/"):
            return _normalize_code_png(response.content)
        try:
            payload = response.json()
        except ValueError as error:
            raise MiniProgramCodeError(
                "WeChat returned an unexpected mini program code response"
            ) from error
        if payload.get("errcode") in {40001, 40014, 42001} and attempt == 0:
            continue
        raise MiniProgramCodeError(
            f"WeChat mini program code request failed ({payload.get('errcode', 'unknown')})"
        )
    raise MiniProgramCodeError("WeChat mini program code request failed")


def reset_access_token_cache() -> None:
    _access_token.value = ""
    _access_token.expires_at = 0
