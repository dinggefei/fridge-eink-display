from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.settings import get_settings


CODE_TO_SESSION_URL = "https://api.weixin.qq.com/sns/jscode2session"


class WechatLoginError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class WechatIdentity:
    openid: str
    unionid: str | None = None


async def exchange_login_code(code: str) -> WechatIdentity:
    settings = get_settings()
    app_secret = settings.wechat_app_secret.get_secret_value()
    if not settings.wechat_app_id or not app_secret:
        raise WechatLoginError(
            "WeChat login is not configured on the backend"
        )

    async with httpx.AsyncClient(timeout=8.0) as client:
        try:
            response = await client.get(
                CODE_TO_SESSION_URL,
                params={
                    "appid": settings.wechat_app_id,
                    "secret": app_secret,
                    "js_code": code,
                    "grant_type": "authorization_code",
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise WechatLoginError(
                "WeChat login service is temporarily unavailable"
            ) from error

    payload = response.json()
    if payload.get("errcode"):
        raise WechatLoginError(
            f"WeChat rejected the login code ({payload['errcode']})"
        )
    openid = payload.get("openid")
    if not openid:
        raise WechatLoginError("WeChat response did not contain openid")
    return WechatIdentity(
        openid=str(openid),
        unionid=str(payload["unionid"]) if payload.get("unionid") else None,
    )
