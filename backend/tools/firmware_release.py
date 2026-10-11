from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import select

from app.db.models import FirmwareRelease, FirmwareReleaseStatus
from app.db.session import AsyncSessionFactory
from app.settings import get_settings


VERSION_PATTERN = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._+-]{0,31}$")
HARDWARE_PATTERN = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._-]{0,63}$")
SIGNATURE_TRAILER_BYTES = 512


def verify_signed_firmware(binary: Path, public_key_path: Path) -> bytes:
    signed = binary.read_bytes()
    if len(signed) <= SIGNATURE_TRAILER_BYTES:
        raise ValueError("signed firmware is too small to contain an image")
    trailer = signed[-SIGNATURE_TRAILER_BYTES:]
    if len(trailer) < 2 or trailer[0] != 0x30:
        raise ValueError("firmware signature is not DER-encoded ECDSA")
    if trailer[1] & 0x80:
        length_bytes = trailer[1] & 0x7F
        if length_bytes == 0 or length_bytes > 2:
            raise ValueError("invalid ECDSA signature length")
        signature_length = 2 + length_bytes + int.from_bytes(
            trailer[2 : 2 + length_bytes], "big"
        )
    else:
        signature_length = 2 + trailer[1]
    if signature_length > len(trailer):
        raise ValueError("truncated ECDSA signature")
    signature = trailer[:signature_length]
    if any(trailer[signature_length:]):
        raise ValueError("firmware signature padding must contain only zeroes")
    image = signed[:-SIGNATURE_TRAILER_BYTES]
    public_key = serialization.load_pem_public_key(public_key_path.read_bytes())
    if not isinstance(public_key, ec.EllipticCurvePublicKey):
        raise ValueError("OTA public key must be an ECDSA key")
    if not isinstance(public_key.curve, ec.SECP256R1):
        raise ValueError("OTA public key must use the P-256 curve")
    try:
        public_key.verify(signature, image, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature as error:
        raise ValueError("firmware ECDSA signature is invalid") from error
    return signed


def _validate_metadata(version: str, hardware: str, build: int) -> None:
    if VERSION_PATTERN.fullmatch(version) is None:
        raise ValueError("invalid firmware version")
    if HARDWARE_PATTERN.fullmatch(hardware) is None:
        raise ValueError("invalid hardware model")
    if build <= 0:
        raise ValueError("build number must be greater than zero")


async def import_release(args: argparse.Namespace) -> None:
    _validate_metadata(args.version, args.hardware, args.build)
    signed = verify_signed_firmware(args.binary, args.public_key)
    settings = get_settings()
    if len(signed) > settings.ota_max_signed_binary_bytes:
        raise ValueError(
            "signed firmware exceeds OTA_MAX_SIGNED_BINARY_BYTES"
        )
    digest = hashlib.sha256(signed).hexdigest()
    relative_path = Path(args.hardware) / f"{args.build}-{digest[:16]}.bin"
    destination = settings.ota_firmware_storage_dir / relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)

    async with AsyncSessionFactory() as session:
        existing = await session.scalar(
            select(FirmwareRelease).where(
                FirmwareRelease.hardware_model == args.hardware,
                FirmwareRelease.build_number == args.build,
            )
        )
        if existing is not None:
            raise ValueError(
                "a release with this hardware model and build already exists"
            )

        temporary = destination.with_suffix(".tmp")
        try:
            with temporary.open("xb") as output:
                output.write(signed)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, destination)
            release = FirmwareRelease(
                version=args.version,
                build_number=args.build,
                hardware_model=args.hardware,
                min_build_number=args.min_build,
                binary_path=str(relative_path),
                binary_size=len(signed),
                sha256=digest,
                release_notes=args.notes,
            )
            session.add(release)
            await session.commit()
            print(
                f"Imported draft release {release.id}: "
                f"{args.version} build {args.build}, sha256={digest}"
            )
        except Exception:
            temporary.unlink(missing_ok=True)
            if destination.exists():
                destination.unlink()
            raise


async def set_release_status(args: argparse.Namespace) -> None:
    targets = sorted(set(args.device or []))
    async with AsyncSessionFactory() as session:
        release = await session.get(FirmwareRelease, args.release_id)
        if release is None:
            raise ValueError("firmware release not found")
        new_status = FirmwareReleaseStatus(args.status)
        if new_status == FirmwareReleaseStatus.CANARY and not targets:
            raise ValueError("canary release requires at least one --device")
        if (
            new_status == FirmwareReleaseStatus.PUBLISHED
            and args.rollout == 0
            and not targets
        ):
            raise ValueError(
                "published release requires rollout > 0 or an explicit device"
            )
        release.status = new_status
        release.rollout_percent = args.rollout
        release.target_device_codes = targets
        release.published_at = (
            datetime.now(timezone.utc)
            if new_status
            in (
                FirmwareReleaseStatus.CANARY,
                FirmwareReleaseStatus.PUBLISHED,
            )
            else None
        )
        await session.commit()
        print(
            f"Release {release.id} -> {release.status.value}, "
            f"rollout={release.rollout_percent}%, targets={targets}"
        )


async def list_releases() -> None:
    async with AsyncSessionFactory() as session:
        releases = list(
            await session.scalars(
                select(FirmwareRelease).order_by(
                    FirmwareRelease.build_number.desc()
                )
            )
        )
    for release in releases:
        print(
            f"{release.id}  {release.hardware_model}  {release.version}  "
            f"build={release.build_number}  {release.status.value}  "
            f"rollout={release.rollout_percent}%"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import and stage signed ESP32 OTA releases."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    import_parser = subparsers.add_parser("import")
    import_parser.add_argument("--binary", type=Path, required=True)
    import_parser.add_argument("--public-key", type=Path, required=True)
    import_parser.add_argument("--version", required=True)
    import_parser.add_argument("--build", type=int, required=True)
    import_parser.add_argument(
        "--hardware",
        default="esp32-s3-dev-kit-n16r8",
    )
    import_parser.add_argument("--min-build", type=int, default=0)
    import_parser.add_argument("--notes")

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("release_id")
    status_parser.add_argument(
        "status",
        choices=[item.value for item in FirmwareReleaseStatus],
    )
    status_parser.add_argument("--rollout", type=int, choices=range(101), default=0)
    status_parser.add_argument("--device", action="append")

    subparsers.add_parser("list")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "import":
        asyncio.run(import_release(args))
    elif args.command == "status":
        asyncio.run(set_release_status(args))
    else:
        asyncio.run(list_releases())


if __name__ == "__main__":
    main()
