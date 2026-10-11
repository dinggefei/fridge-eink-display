from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utc_now
from app.db.models import (
    FoodBatch as FoodBatchModel,
    Household,
    ImportImage,
    ImportTask,
    ImportTaskStatus,
    InventoryAction,
    InventoryEvent,
)
from app.domain.inventory import (
    FoodBatch,
    StorageLocation,
    allocate_fefo,
    calculate_food_status,
)
from app.services.recognition import (
    InventoryCandidate,
    RecognitionAction,
    RecognitionProviderError,
    RecognitionQueryItem,
    RecognitionQueryResult,
    RecognitionResult,
    get_recognition_provider,
    merge_order_results,
    parse_full_inventory_entry,
)
from app.services.shelf_life import suggested_use_by_date
from app.settings import get_settings


logger = logging.getLogger("uvicorn.error.recognition-tasks")


class InvalidImage(ValueError):
    pass


class ConfirmationConflict(ValueError):
    pass


def _task_expiry() -> datetime:
    return utc_now() + timedelta(
        seconds=get_settings().recognition_task_ttl_seconds
    )


async def inventory_candidates(
    session: AsyncSession,
    household_id: str,
) -> list[InventoryCandidate]:
    rows = (
        await session.scalars(
            select(FoodBatchModel).where(
                FoodBatchModel.household_id == household_id,
                FoodBatchModel.deleted_at.is_(None),
                FoodBatchModel.quantity > 0,
            )
        )
    ).all()
    return [
        InventoryCandidate(
            id=row.id,
            name=row.standard_name,
            quantity=row.quantity,
            unit=row.unit,
            location=row.location,
            stocked_on=row.stocked_on,
            suggested_use_by=row.suggested_use_by,
        )
        for row in rows
    ]


async def normalize_quick_result(
    session: AsyncSession,
    household_id: str,
    result: RecognitionResult,
    candidates: list[InventoryCandidate],
) -> RecognitionResult:
    candidates_by_id = {candidate.id: candidate for candidate in candidates}
    today = date.today()
    normalized_actions: list[RecognitionAction] = []
    edit_actions: dict[str, RecognitionAction] = {}
    for action in result.actions:
        if action.type == "add":
            action.target_batch_id = None
            action.location = action.location or StorageLocation.REFRIGERATED
            action.stocked_on = action.stocked_on or today
            action.suggested_use_by, _, _ = await suggested_use_by_date(
                session,
                household_id=household_id,
                food_name=action.name,
                location=action.location,
                stocked_on=action.stocked_on,
            )
            normalized_actions.append(action)
            continue
        target = candidates_by_id.get(action.target_batch_id or "")
        if target is None or target.name != action.name:
            exact = [
                candidate
                for candidate in candidates
                if candidate.name == action.name
                and (
                    action.type == "edit"
                    or action.unit is None
                    or candidate.unit == action.unit
                )
            ]
            action.target_batch_id = exact[0].id if len(exact) == 1 else None
        action.needs_confirmation = action.target_batch_id is None
        if action.type == "edit":
            key = action.target_batch_id or f"name:{action.name}"
            existing = edit_actions.get(key)
            if existing is None:
                edit_actions[key] = action
                normalized_actions.append(action)
            else:
                for field in (
                    "quantity",
                    "unit",
                    "location",
                    "stocked_on",
                    "suggested_use_by",
                ):
                    value = getattr(action, field)
                    if value is not None:
                        setattr(existing, field, value)
                existing.needs_confirmation = (
                    existing.needs_confirmation or action.needs_confirmation
                )
                existing.confidence = min(
                    existing.confidence,
                    action.confidence,
                )
        else:
            action.location = None
            action.stocked_on = None
            action.suggested_use_by = None
            normalized_actions.append(action)

    for action in edit_actions.values():
        if not action.target_batch_id:
            continue
        target = candidates_by_id[action.target_batch_id]
        action.quantity = action.quantity or target.quantity
        action.unit = action.unit or target.unit
        action.location = action.location or target.location
        action.stocked_on = action.stocked_on or target.stocked_on
        action.suggested_use_by = (
            action.suggested_use_by or target.suggested_use_by
        )
    result.actions = normalized_actions

    query_results: list[RecognitionQueryResult] = []
    location_labels = {
        StorageLocation.REFRIGERATED: "冷藏",
        StorageLocation.FROZEN: "冷冻",
        StorageLocation.ROOM_TEMPERATURE: "常温",
    }
    for query in result.queries:
        matches: list[InventoryCandidate]
        title: str
        if query.type == "named_quantity":
            matches = [
                candidate
                for candidate in candidates
                if candidate.name == (query.name or "")
            ]
            title = f"{query.name or '该食材'}的库存"
        elif query.type == "location_items":
            matches = [
                candidate
                for candidate in candidates
                if candidate.location == query.location
            ]
            title = f"{location_labels.get(query.location, '该位置')}的食材"
        elif query.type == "expiring_soon":
            limit = today + timedelta(days=query.days)
            matches = [
                candidate
                for candidate in candidates
                if candidate.suggested_use_by is not None
                and today < candidate.suggested_use_by <= limit
            ]
            title = f"{query.days} 天内临期的食材"
        elif query.type == "due_today":
            matches = [
                candidate
                for candidate in candidates
                if candidate.suggested_use_by == today
            ]
            title = "今天到期的食材"
        else:
            matches = [
                candidate
                for candidate in candidates
                if candidate.suggested_use_by is not None
                and candidate.suggested_use_by < today
            ]
            title = "已过期的食材"
        query_results.append(
            RecognitionQueryResult(
                query_id=query.query_id,
                type=query.type,
                title=title,
                items=[
                    RecognitionQueryItem(
                        id=candidate.id,
                        name=candidate.name,
                        quantity=candidate.quantity,
                        unit=candidate.unit,
                        location=candidate.location,
                        suggested_use_by=candidate.suggested_use_by,
                        days_remaining=(
                            (candidate.suggested_use_by - today).days
                            if candidate.suggested_use_by
                            else None
                        ),
                    )
                    for candidate in matches
                ],
            )
        )
    result.query_results = query_results
    return result


async def parse_quick_entry(
    session: AsyncSession,
    task: ImportTask,
) -> ImportTask:
    started_at = perf_counter()
    candidates = await inventory_candidates(session, task.household_id)
    task.status = ImportTaskStatus.PROCESSING
    await session.commit()
    try:
        result = parse_full_inventory_entry(
            task.input_text or "",
            candidates,
        )
        if result is None:
            result = await get_recognition_provider().parse_quick_entry(
                task.input_text or "",
                candidates,
            )
        result = await normalize_quick_result(
            session,
            task.household_id,
            result,
            candidates,
        )
        task.recognition_result = result.model_dump(mode="json")
        task.status = (
            ImportTaskStatus.NEEDS_CONFIRMATION
            if result.actions
            else ImportTaskStatus.CONFIRMED
        )
        if not result.actions:
            task.confirmed_at = utc_now()
        task.recognition_duration_ms = round(
            (perf_counter() - started_at) * 1000
        )
        task.recognized_action_count = len(result.actions)
        confidences = [action.confidence for action in result.actions]
        task.average_confidence = (
            Decimal(str(sum(confidences) / len(confidences)))
            if confidences
            else None
        )
        task.error_message = None
    except RecognitionProviderError as error:
        task.status = ImportTaskStatus.FAILED
        task.error_message = str(error)
    if task.recognition_duration_ms is None:
        task.recognition_duration_ms = round(
            (perf_counter() - started_at) * 1000
        )
    await session.commit()
    await session.refresh(task)
    return task


def _safe_task_dir(task_id: str) -> Path:
    base = get_settings().recognition_upload_dir.resolve()
    target = (base / task_id).resolve()
    if target.parent != base:
        raise InvalidImage("invalid task storage path")
    target.mkdir(parents=True, exist_ok=True)
    return target


def normalize_image(
    raw: bytes,
    *,
    task_id: str,
    image_id: str,
) -> tuple[Path, bytes]:
    settings = get_settings()
    if not raw:
        raise InvalidImage("image is empty")
    if len(raw) > settings.recognition_max_image_bytes:
        raise InvalidImage("image exceeds the 5 MB limit")
    Image.MAX_IMAGE_PIXELS = 20_000_000
    try:
        with Image.open(BytesIO(raw)) as opened:
            opened.verify()
        with Image.open(BytesIO(raw)) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
            image.thumbnail((3000, 3000), Image.Resampling.LANCZOS)
            output = BytesIO()
            image.save(
                output,
                format="JPEG",
                quality=90,
                optimize=True,
            )
    except (
        UnidentifiedImageError,
        Image.DecompressionBombError,
        OSError,
    ) as error:
        raise InvalidImage("unsupported or damaged image") from error
    normalized = output.getvalue()
    target = _safe_task_dir(task_id) / f"{image_id}.jpg"
    target.write_bytes(normalized)
    return target, normalized


async def store_import_image(
    session: AsyncSession,
    *,
    task: ImportTask,
    original_filename: str,
    raw: bytes,
) -> ImportImage:
    started_at = perf_counter()
    settings = get_settings()
    existing = (
        await session.scalars(
            select(ImportImage)
            .where(ImportImage.task_id == task.id)
            .order_by(ImportImage.sequence)
        )
    ).all()
    if len(existing) >= settings.recognition_max_images:
        raise InvalidImage("a task can contain at most 9 images")
    image_id = str(uuid4())
    target, normalized = normalize_image(
        raw,
        task_id=task.id,
        image_id=image_id,
    )
    row = ImportImage(
        id=image_id,
        task_id=task.id,
        sequence=len(existing),
        original_filename=(original_filename or "order.jpg")[:255],
        content_type="image/jpeg",
        object_path=str(target),
        sha256=hashlib.sha256(normalized).hexdigest(),
        byte_size=len(normalized),
        expires_at=_task_expiry(),
    )
    session.add(row)
    task.original_files_expires_at = row.expires_at
    await session.commit()
    await session.refresh(row)
    logger.info(
        "recognition_image_stored task_id=%s sequence=%d "
        "input_bytes=%d normalized_bytes=%d duration_ms=%.1f",
        task.id,
        row.sequence,
        len(raw),
        len(normalized),
        (perf_counter() - started_at) * 1000,
    )
    return row


async def delete_task_images(
    session: AsyncSession,
    task_id: str,
) -> None:
    images = (
        await session.scalars(
            select(ImportImage).where(ImportImage.task_id == task_id)
        )
    ).all()
    directories: set[Path] = set()
    for image in images:
        path = Path(image.object_path)
        directories.add(path.parent)
        path.unlink(missing_ok=True)
    await session.execute(
        delete(ImportImage).where(ImportImage.task_id == task_id)
    )
    for directory in directories:
        try:
            directory.rmdir()
        except OSError:
            pass


async def process_order_task(
    session: AsyncSession,
    task: ImportTask,
) -> ImportTask:
    task_started_at = perf_counter()
    images = (
        await session.scalars(
            select(ImportImage)
            .where(ImportImage.task_id == task.id)
            .order_by(ImportImage.sequence)
        )
    ).all()
    if not images:
        task.status = ImportTaskStatus.FAILED
        task.error_message = "no images were uploaded"
        await session.commit()
        return task

    task.status = ImportTaskStatus.PROCESSING
    task.error_message = None
    await session.commit()
    results: list[RecognitionResult] = []
    try:
        provider = get_recognition_provider()
        concurrency = min(
            get_settings().recognition_image_concurrency,
            len(images),
        )
        semaphore = asyncio.Semaphore(concurrency)

        async def recognize_image(image: ImportImage) -> RecognitionResult:
            image_bytes = Path(image.object_path).read_bytes()
            model_started_at = perf_counter()
            async with semaphore:
                result = await provider.recognize_order_image(
                    image_bytes=image_bytes,
                    content_type=image.content_type,
                    image_index=image.sequence,
                )
            logger.info(
                "recognition_image_completed task_id=%s sequence=%d "
                "duration_ms=%.1f actions=%d",
                task.id,
                image.sequence,
                (perf_counter() - model_started_at) * 1000,
                len(result.actions),
            )
            return result

        results = await asyncio.gather(
            *(recognize_image(image) for image in images)
        )
        merge_started_at = perf_counter()
        result = merge_order_results(results)
        for action in result.actions:
            if action.type != "add":
                continue
            location = action.location or StorageLocation.REFRIGERATED
            stocked_on = action.stocked_on or date.today()
            action.location = location
            action.stocked_on = stocked_on
            action.suggested_use_by, _, _ = await suggested_use_by_date(
                session,
                household_id=task.household_id,
                food_name=action.name,
                location=location,
                stocked_on=stocked_on,
            )
        logger.info(
            "recognition_results_merged task_id=%s duration_ms=%.1f "
            "actions=%d",
            task.id,
            (perf_counter() - merge_started_at) * 1000,
            len(result.actions),
        )
        task.recognition_result = result.model_dump(mode="json")
        task.status = ImportTaskStatus.NEEDS_CONFIRMATION
        task.recognition_duration_ms = round(
            (perf_counter() - task_started_at) * 1000
        )
        task.recognition_image_count = len(images)
        task.recognized_action_count = len(result.actions)
        confidences = [action.confidence for action in result.actions]
        task.average_confidence = (
            Decimal(str(sum(confidences) / len(confidences)))
            if confidences
            else None
        )
        await delete_task_images(session, task.id)
        task.original_files_expires_at = None
    except (OSError, RecognitionProviderError) as error:
        task.status = ImportTaskStatus.FAILED
        task.error_message = str(error)
    if task.recognition_duration_ms is None:
        task.recognition_duration_ms = round(
            (perf_counter() - task_started_at) * 1000
        )
    task.recognition_image_count = len(images)
    await session.commit()
    await session.refresh(task)
    logger.info(
        "recognition_task_completed task_id=%s status=%s images=%d "
        "concurrency=%d duration_ms=%.1f",
        task.id,
        task.status.value,
        len(images),
        min(get_settings().recognition_image_concurrency, len(images)),
        (perf_counter() - task_started_at) * 1000,
    )
    return task


async def cleanup_expired_images(session: AsyncSession) -> int:
    images = (
        await session.scalars(
            select(ImportImage).where(ImportImage.expires_at <= utc_now())
        )
    ).all()
    for image in images:
        Path(image.object_path).unlink(missing_ok=True)
        await session.delete(image)
    await session.commit()
    return len(images)


def _inventory_event(
    *,
    household_id: str,
    batch_id: str,
    actor_user_id: str,
    action: InventoryAction,
    quantity: Decimal,
    idempotency_key: str,
    task_id: str,
    event_data: dict | None = None,
) -> InventoryEvent:
    metadata = {"recognition_task_id": task_id}
    if event_data:
        metadata.update(event_data)
    return InventoryEvent(
        household_id=household_id,
        batch_id=batch_id,
        actor_user_id=actor_user_id,
        action=action,
        quantity=quantity,
        idempotency_key=idempotency_key[:100],
        event_data=metadata,
    )


def _batch_snapshot(batch: FoodBatchModel) -> dict[str, str | None]:
    return {
        "standard_name": batch.standard_name,
        "original_name": batch.original_name,
        "quantity": str(batch.quantity),
        "unit": batch.unit,
        "location": batch.location.value,
        "stocked_on": batch.stocked_on.isoformat(),
        "suggested_use_by": (
            batch.suggested_use_by.isoformat()
            if batch.suggested_use_by
            else None
        ),
        "status": batch.status.value,
        "deleted_at": (
            batch.deleted_at.isoformat() if batch.deleted_at else None
        ),
    }


def _action_signature(action: RecognitionAction) -> dict:
    return action.model_dump(
        mode="json",
        include={
            "action_id",
            "type",
            "name",
            "quantity",
            "unit",
            "location",
            "stocked_on",
            "suggested_use_by",
            "target_batch_id",
        },
    )


async def confirm_actions(
    session: AsyncSession,
    *,
    task_id: str,
    household_id: str,
    user_id: str,
    actions: list[RecognitionAction],
    idempotency_key: str,
) -> ImportTask:
    task = await session.scalar(
        select(ImportTask)
        .where(
            ImportTask.id == task_id,
            ImportTask.household_id == household_id,
        )
        .with_for_update()
    )
    if task is None:
        raise KeyError("task not found")
    if task.status == ImportTaskStatus.CONFIRMED:
        return task
    if task.status != ImportTaskStatus.NEEDS_CONFIRMATION:
        raise ConfirmationConflict("task is not ready for confirmation")

    household = await session.scalar(
        select(Household)
        .where(Household.id == household_id)
        .with_for_update()
    )
    if household is None:
        raise KeyError("household not found")
    if household.inventory_revision != task.base_inventory_revision:
        raise ConfirmationConflict(
            "inventory changed after recognition; please recognize again"
        )
    if not actions:
        raise ConfirmationConflict("at least one action must be selected")

    today = date.today()
    event_index = 0
    for action in actions:
        if action.type == "add":
            location = action.location or StorageLocation.REFRIGERATED
            stocked_on = action.stocked_on or today
            suggested_use_by = action.suggested_use_by
            if suggested_use_by is not None and suggested_use_by < stocked_on:
                raise ConfirmationConflict(
                    f"{action.name}: suggested date is before stocked date"
                )
            batch = FoodBatchModel(
                household_id=household_id,
                standard_name=action.name,
                original_name=action.name,
                quantity=action.quantity,
                unit=action.unit,
                location=location,
                stocked_on=stocked_on,
                suggested_use_by=suggested_use_by,
                status=calculate_food_status(
                    suggested_use_by,
                    today=today,
                ),
            )
            session.add(batch)
            await session.flush()
            session.add(
                _inventory_event(
                    household_id=household_id,
                    batch_id=batch.id,
                    actor_user_id=user_id,
                    action=InventoryAction.ADD,
                    quantity=action.quantity,
                    idempotency_key=f"{idempotency_key}:{event_index}",
                    task_id=task.id,
                )
            )
            event_index += 1
            continue

        if action.type == "edit":
            target = None
            if action.target_batch_id:
                target = await session.scalar(
                    select(FoodBatchModel)
                    .where(
                        FoodBatchModel.id == action.target_batch_id,
                        FoodBatchModel.household_id == household_id,
                        FoodBatchModel.deleted_at.is_(None),
                        FoodBatchModel.quantity > 0,
                    )
                    .with_for_update()
                )
            else:
                matches = list(
                    (
                        await session.scalars(
                            select(FoodBatchModel)
                            .where(
                                FoodBatchModel.household_id == household_id,
                                FoodBatchModel.deleted_at.is_(None),
                                FoodBatchModel.quantity > 0,
                                FoodBatchModel.standard_name == action.name,
                            )
                            .with_for_update()
                        )
                    ).all()
                )
                target = matches[0] if len(matches) == 1 else None
            if target is None or target.standard_name != action.name:
                raise ConfirmationConflict(
                    f"{action.name}: selected inventory batch no longer exists"
                )
            before = _batch_snapshot(target)
            if action.quantity is not None:
                target.quantity = action.quantity
            if action.unit is not None:
                target.unit = action.unit
            if action.location is not None:
                target.location = action.location
            if action.stocked_on is not None:
                target.stocked_on = action.stocked_on
            if action.suggested_use_by is not None:
                target.suggested_use_by = action.suggested_use_by
            if (
                target.suggested_use_by is not None
                and target.suggested_use_by < target.stocked_on
            ):
                raise ConfirmationConflict(
                    f"{action.name}: suggested date is before stocked date"
                )
            target.status = calculate_food_status(
                target.suggested_use_by,
                today=today,
            )
            session.add(
                _inventory_event(
                    household_id=household_id,
                    batch_id=target.id,
                    actor_user_id=user_id,
                    action=InventoryAction.EDIT,
                    quantity=target.quantity,
                    idempotency_key=f"{idempotency_key}:{event_index}",
                    task_id=task.id,
                    event_data={
                        "before": before,
                        "after": _batch_snapshot(target),
                    },
                )
            )
            event_index += 1
            continue

        query = select(FoodBatchModel).where(
            FoodBatchModel.household_id == household_id,
            FoodBatchModel.deleted_at.is_(None),
            FoodBatchModel.quantity > 0,
            FoodBatchModel.standard_name == action.name,
            FoodBatchModel.unit == action.unit,
        )
        rows = list((await session.scalars(query)).all())
        if action.target_batch_id:
            target = next(
                (
                    row
                    for row in rows
                    if row.id == action.target_batch_id
                ),
                None,
            )
            if target is None:
                raise ConfirmationConflict(
                    f"{action.name}: selected inventory batch no longer exists"
                )
        try:
            deductions = allocate_fefo(
                [
                    FoodBatch(
                        batch_id=row.id,
                        name=row.standard_name,
                        quantity=row.quantity,
                        unit=row.unit,
                        location=row.location,
                        stocked_on=row.stocked_on,
                        suggested_use_by=row.suggested_use_by,
                    )
                    for row in rows
                ],
                action.quantity or Decimal("0"),
            )
        except ValueError as error:
            raise ConfirmationConflict(
                f"{action.name}: available quantity is insufficient"
            ) from error
        rows_by_id = {row.id: row for row in rows}
        event_action = (
            InventoryAction.CONSUME
            if action.type == "consume"
            else InventoryAction.DISCARD
        )
        for deduction in deductions:
            row = rows_by_id[deduction.batch_id]
            before = _batch_snapshot(row)
            row.quantity -= deduction.quantity
            session.add(
                _inventory_event(
                    household_id=household_id,
                    batch_id=row.id,
                    actor_user_id=user_id,
                    action=event_action,
                    quantity=deduction.quantity,
                    idempotency_key=f"{idempotency_key}:{event_index}",
                    task_id=task.id,
                    event_data={
                        "before": before,
                        "after": _batch_snapshot(row),
                    },
                )
            )
            event_index += 1

    household.inventory_revision += 1
    original_result = RecognitionResult.model_validate(
        task.recognition_result or {}
    )
    original_by_id = {
        action.action_id: action for action in original_result.actions
    }
    corrected_count = sum(
        1
        for action in actions
        if action.action_id not in original_by_id
        or _action_signature(action)
        != _action_signature(original_by_id[action.action_id])
    )
    corrected_count += len(
        set(original_by_id) - {action.action_id for action in actions}
    )
    task.confirmed_action_count = len(actions)
    task.corrected_action_count = corrected_count
    task.status = ImportTaskStatus.CONFIRMED
    task.confirmed_at = utc_now()
    await session.commit()
    await session.refresh(task)
    return task
