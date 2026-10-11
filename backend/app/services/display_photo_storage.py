from __future__ import annotations

import asyncio
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Protocol

from app.settings import get_settings


class DisplayPhotoStorage(Protocol):
    async def put(self, key: str, data: bytes, *, content_type: str) -> None: ...

    async def get(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...


def _safe_object_key(key: str) -> PurePosixPath:
    path = PurePosixPath(key)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ValueError("invalid display photo object key")
    return path


class LocalDisplayPhotoStorage:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def _path(self, key: str) -> Path:
        relative = _safe_object_key(key)
        path = self._root.joinpath(*relative.parts).resolve()
        if self._root not in path.parents:
            raise ValueError("display photo object key escapes storage root")
        return path

    async def put(self, key: str, data: bytes, *, content_type: str) -> None:
        del content_type

        def write() -> None:
            path = self._path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(f"{path.suffix}.tmp")
            temporary.write_bytes(data)
            temporary.replace(path)

        await asyncio.to_thread(write)

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(self._path(key).read_bytes)

    async def delete(self, key: str) -> None:
        def remove() -> None:
            path = self._path(key)
            path.unlink(missing_ok=True)

        await asyncio.to_thread(remove)


class CosDisplayPhotoStorage:
    def __init__(
        self,
        *,
        region: str,
        bucket: str,
        secret_id: str,
        secret_key: str,
    ) -> None:
        from qcloud_cos import CosConfig, CosS3Client

        config = CosConfig(
            Region=region,
            SecretId=secret_id,
            SecretKey=secret_key,
            Scheme="https",
        )
        self._client = CosS3Client(config)
        self._bucket = bucket

    async def put(self, key: str, data: bytes, *, content_type: str) -> None:
        normalized = str(_safe_object_key(key))
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self._bucket,
            Key=normalized,
            Body=data,
            ContentType=content_type,
        )

    async def get(self, key: str) -> bytes:
        normalized = str(_safe_object_key(key))

        def read() -> bytes:
            response = self._client.get_object(
                Bucket=self._bucket,
                Key=normalized,
            )
            return response["Body"].get_raw_stream().read()

        return await asyncio.to_thread(read)

    async def delete(self, key: str) -> None:
        normalized = str(_safe_object_key(key))
        await asyncio.to_thread(
            self._client.delete_object,
            Bucket=self._bucket,
            Key=normalized,
        )


@lru_cache(maxsize=1)
def get_display_photo_storage() -> DisplayPhotoStorage:
    settings = get_settings()
    if settings.display_photo_storage_backend == "cos":
        return CosDisplayPhotoStorage(
            region=settings.cos_region,
            bucket=settings.cos_bucket,
            secret_id=settings.cos_secret_id.get_secret_value(),
            secret_key=settings.cos_secret_key.get_secret_value(),
        )
    return LocalDisplayPhotoStorage(settings.display_photo_local_dir)
