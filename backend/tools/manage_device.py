from __future__ import annotations

import argparse
import asyncio
import os
import secrets
from pathlib import Path

from sqlalchemy import select

from app.db.models import Device, DeviceStatus
from app.db.session import AsyncSessionFactory
from app.services.device_secrets import (
    device_secret_hash,
    encrypt_device_secret,
)


def _write_factory_header(path: Path, device_code: str, secret: str) -> None:
    if path.exists():
        raise RuntimeError(f"refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        output.write(
            "#pragma once\n\n"
            "// Generated locally. Never commit or share this file.\n"
            f'constexpr char kDeviceCode[] = "{device_code}";\n'
            f'constexpr char kDeviceSecret[] = "{secret}";\n'
        )


async def _manage(args: argparse.Namespace) -> None:
    secret = secrets.token_hex(32)
    async with AsyncSessionFactory() as session:
        device = await session.scalar(
            select(Device)
            .where(Device.device_code == args.device_code)
            .with_for_update()
        )
        if args.action == "register":
            if device is not None:
                raise RuntimeError("device code is already registered")
            device = Device(
                device_code=args.device_code,
                device_secret_hash=device_secret_hash(secret),
                device_secret_ciphertext=encrypt_device_secret(
                    secret,
                    args.device_code,
                ),
                status=DeviceStatus.UNBOUND,
            )
            session.add(device)
        else:
            if device is None:
                raise RuntimeError("device code is not registered")
            if not args.confirm_device_offline:
                raise RuntimeError(
                    "rotation requires --confirm-device-offline; "
                    "the old firmware stops authenticating immediately"
                )
            device.device_secret_hash = device_secret_hash(secret)
            device.device_secret_ciphertext = encrypt_device_secret(
                secret,
                args.device_code,
            )
            device.secret_version += 1
            device.status = DeviceStatus.OFFLINE
        _write_factory_header(args.header_output, args.device_code, secret)
        await session.commit()
    print(
        f"{args.action} complete for {args.device_code}; "
        f"factory header written with mode 0600 to {args.header_output}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Register or rotate one ESP32 device identity.",
    )
    parser.add_argument("action", choices=("register", "rotate"))
    parser.add_argument(
        "--device-code",
        required=True,
        help="1-32 character factory code used as the mini-program scene",
    )
    parser.add_argument(
        "--header-output",
        required=True,
        type=Path,
        help="new non-existing path for device_secrets.h",
    )
    parser.add_argument(
        "--confirm-device-offline",
        action="store_true",
        help="required for rotation because the old firmware is invalidated",
    )
    args = parser.parse_args()
    if (
        not args.device_code.isascii()
        or not 3 <= len(args.device_code) <= 32
        or any(character.isspace() for character in args.device_code)
    ):
        parser.error("device code must be 3-32 non-whitespace ASCII characters")
    asyncio.run(_manage(args))


if __name__ == "__main__":
    main()
