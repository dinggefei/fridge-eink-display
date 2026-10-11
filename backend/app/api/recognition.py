from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, File, Header, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.api.dependencies import CurrentUser, DbSession, require_household_member
from app.db.models import (
    Household,
    ImportImage,
    ImportTask,
    ImportTaskStatus,
    MembershipRole,
)
from app.services.recognition import RecognitionAction, RecognitionResult
from app.services.recognition_tasks import (
    ConfirmationConflict,
    InvalidImage,
    confirm_actions,
    delete_task_images,
    parse_quick_entry,
    process_order_task,
    store_import_image,
)
from app.settings import get_settings


router = APIRouter(
    prefix="/v1/households/{household_id}",
    tags=["recognition"],
)


class QuickEntryWrite(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    text: str = Field(min_length=1, max_length=300)


class ConfirmActionsWrite(BaseModel):
    actions: list[RecognitionAction] = Field(min_length=1, max_length=100)


class RecognitionTaskResponse(BaseModel):
    id: str
    source: str
    status: ImportTaskStatus
    input_text: str | None
    base_inventory_revision: int
    result: RecognitionResult | None
    error_message: str | None
    image_count: int
    created_at: datetime
    updated_at: datetime
    confirmed_at: datetime | None


class ImportImageResponse(BaseModel):
    id: str
    sequence: int
    byte_size: int


class ConfirmationResponse(BaseModel):
    task_id: str
    status: ImportTaskStatus
    inventory_revision: int


class RecognitionHistoryItem(BaseModel):
    id: str
    source: str
    status: ImportTaskStatus
    input_text: str | None
    image_count: int
    recognized_action_count: int
    confirmed_action_count: int
    corrected_action_count: int
    average_confidence: Decimal | None
    recognition_duration_ms: int | None
    created_at: datetime
    confirmed_at: datetime | None


class RecognitionHistoryResponse(BaseModel):
    items: list[RecognitionHistoryItem]
    total: int
    page: int
    page_size: int


class RecognitionMetricsResponse(BaseModel):
    scope: str
    task_count: int
    source_counts: dict[str, int]
    status_counts: dict[str, int]
    image_count: int
    recognized_action_count: int
    confirmed_action_count: int
    corrected_action_count: int
    success_rate: float
    average_confidence: float | None
    average_duration_ms: float | None
    correction_rate: float


async def _household(
    session: DbSession,
    user: CurrentUser,
    household_id: str,
) -> Household:
    await require_household_member(
        session,
        household_id=household_id,
        user_id=user.id,
    )
    household = await session.get(Household, household_id)
    if household is None:
        raise HTTPException(status_code=404, detail="household not found")
    return household


async def _task(
    session: DbSession,
    *,
    household_id: str,
    task_id: str,
    user_id: str,
) -> ImportTask:
    task = await session.scalar(
        select(ImportTask).where(
            ImportTask.id == task_id,
            ImportTask.household_id == household_id,
            ImportTask.created_by_user_id == user_id,
        )
    )
    if task is None:
        raise HTTPException(status_code=404, detail="recognition task not found")
    return task


async def _task_response(
    session: DbSession,
    task: ImportTask,
) -> RecognitionTaskResponse:
    image_count = await session.scalar(
        select(func.count(ImportImage.id)).where(ImportImage.task_id == task.id)
    )
    result = None
    if task.recognition_result is not None:
        result = RecognitionResult.model_validate(task.recognition_result)
    return RecognitionTaskResponse(
        id=task.id,
        source=task.source,
        status=task.status,
        input_text=task.input_text,
        base_inventory_revision=task.base_inventory_revision,
        result=result,
        error_message=task.error_message,
        image_count=image_count or 0,
        created_at=task.created_at,
        updated_at=task.updated_at,
        confirmed_at=task.confirmed_at,
    )


@router.post(
    "/quick-entry/parse",
    response_model=RecognitionTaskResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_quick_entry_draft(
    household_id: str,
    payload: QuickEntryWrite,
    session: DbSession,
    user: CurrentUser,
) -> RecognitionTaskResponse:
    household = await _household(session, user, household_id)
    task = ImportTask(
        household_id=household_id,
        created_by_user_id=user.id,
        source="quick_entry",
        input_text=payload.text,
        base_inventory_revision=household.inventory_revision,
        status=ImportTaskStatus.PENDING,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    task = await parse_quick_entry(session, task)
    if task.status == ImportTaskStatus.FAILED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=task.error_message or "recognition failed",
        )
    return await _task_response(session, task)


@router.get(
    "/recognition/history",
    response_model=RecognitionHistoryResponse,
)
async def list_recognition_history(
    household_id: str,
    session: DbSession,
    user: CurrentUser,
    page: int = 1,
    page_size: int = 30,
) -> RecognitionHistoryResponse:
    await _household(session, user, household_id)
    page = max(1, page)
    page_size = min(100, max(1, page_size))
    filters = (
        ImportTask.household_id == household_id,
        ImportTask.created_by_user_id == user.id,
    )
    total = await session.scalar(
        select(func.count(ImportTask.id)).where(*filters)
    )
    tasks = (
        await session.scalars(
            select(ImportTask)
            .where(*filters)
            .order_by(ImportTask.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return RecognitionHistoryResponse(
        items=[
            RecognitionHistoryItem(
                id=task.id,
                source=task.source,
                status=task.status,
                input_text=task.input_text,
                image_count=task.recognition_image_count,
                recognized_action_count=task.recognized_action_count,
                confirmed_action_count=task.confirmed_action_count,
                corrected_action_count=task.corrected_action_count,
                average_confidence=task.average_confidence,
                recognition_duration_ms=task.recognition_duration_ms,
                created_at=task.created_at,
                confirmed_at=task.confirmed_at,
            )
            for task in tasks
        ],
        total=total or 0,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/recognition/metrics",
    response_model=RecognitionMetricsResponse,
)
async def read_recognition_metrics(
    household_id: str,
    session: DbSession,
    user: CurrentUser,
) -> RecognitionMetricsResponse:
    membership = await require_household_member(
        session,
        household_id=household_id,
        user_id=user.id,
    )
    statement = select(ImportTask).where(
        ImportTask.household_id == household_id
    )
    scope = "household"
    if membership.role != MembershipRole.ADMIN:
        statement = statement.where(ImportTask.created_by_user_id == user.id)
        scope = "personal"
    tasks = list((await session.scalars(statement)).all())
    source_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    for task in tasks:
        source_counts[task.source] = source_counts.get(task.source, 0) + 1
        key = task.status.value
        status_counts[key] = status_counts.get(key, 0) + 1
    recognized = sum(task.recognized_action_count for task in tasks)
    confirmed = sum(task.confirmed_action_count for task in tasks)
    corrected = sum(task.corrected_action_count for task in tasks)
    confidence_weight = sum(
        float(task.average_confidence) * task.recognized_action_count
        for task in tasks
        if task.average_confidence is not None
    )
    confidence_count = sum(
        task.recognized_action_count
        for task in tasks
        if task.average_confidence is not None
    )
    durations = [
        task.recognition_duration_ms
        for task in tasks
        if task.recognition_duration_ms is not None
    ]
    successful = sum(
        task.status
        in {
            ImportTaskStatus.NEEDS_CONFIRMATION,
            ImportTaskStatus.CONFIRMED,
        }
        for task in tasks
    )
    return RecognitionMetricsResponse(
        scope=scope,
        task_count=len(tasks),
        source_counts=source_counts,
        status_counts=status_counts,
        image_count=sum(task.recognition_image_count for task in tasks),
        recognized_action_count=recognized,
        confirmed_action_count=confirmed,
        corrected_action_count=corrected,
        success_rate=(successful / len(tasks) if tasks else 0),
        average_confidence=(
            confidence_weight / confidence_count
            if confidence_count
            else None
        ),
        average_duration_ms=(
            sum(durations) / len(durations) if durations else None
        ),
        correction_rate=(
            corrected / max(recognized, confirmed)
            if max(recognized, confirmed)
            else 0
        ),
    )


@router.post(
    "/quick-entry/{task_id}/confirm",
    response_model=ConfirmationResponse,
)
async def confirm_quick_entry(
    household_id: str,
    task_id: str,
    payload: ConfirmActionsWrite,
    session: DbSession,
    user: CurrentUser,
    idempotency_key: str = Header(alias="X-Idempotency-Key"),
) -> ConfirmationResponse:
    household = await _household(session, user, household_id)
    task = await _task(
        session,
        household_id=household_id,
        task_id=task_id,
        user_id=user.id,
    )
    if task.source != "quick_entry":
        raise HTTPException(status_code=404, detail="quick entry task not found")
    try:
        task = await confirm_actions(
            session,
            task_id=task.id,
            household_id=household_id,
            user_id=user.id,
            actions=payload.actions,
            idempotency_key=idempotency_key,
        )
    except ConfirmationConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    await session.refresh(household)
    return ConfirmationResponse(
        task_id=task.id,
        status=task.status,
        inventory_revision=household.inventory_revision,
    )


@router.post(
    "/imports",
    response_model=RecognitionTaskResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_order_import(
    household_id: str,
    session: DbSession,
    user: CurrentUser,
) -> RecognitionTaskResponse:
    household = await _household(session, user, household_id)
    task = ImportTask(
        household_id=household_id,
        created_by_user_id=user.id,
        source="order_images",
        base_inventory_revision=household.inventory_revision,
        status=ImportTaskStatus.PENDING,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return await _task_response(session, task)


@router.post(
    "/imports/{task_id}/images",
    response_model=ImportImageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_order_image(
    household_id: str,
    task_id: str,
    session: DbSession,
    user: CurrentUser,
    image: UploadFile = File(...),
) -> ImportImageResponse:
    await _household(session, user, household_id)
    task = await _task(
        session,
        household_id=household_id,
        task_id=task_id,
        user_id=user.id,
    )
    if task.source != "order_images":
        raise HTTPException(status_code=404, detail="order import not found")
    if task.status != ImportTaskStatus.PENDING:
        raise HTTPException(status_code=409, detail="task no longer accepts images")
    limit = get_settings().recognition_max_image_bytes
    raw = await image.read(limit + 1)
    try:
        row = await store_import_image(
            session,
            task=task,
            original_filename=image.filename or "order.jpg",
            raw=raw,
        )
    except InvalidImage as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return ImportImageResponse(
        id=row.id,
        sequence=row.sequence,
        byte_size=row.byte_size,
    )


@router.post(
    "/imports/{task_id}/start",
    response_model=RecognitionTaskResponse,
)
async def start_order_import(
    household_id: str,
    task_id: str,
    session: DbSession,
    user: CurrentUser,
) -> RecognitionTaskResponse:
    await _household(session, user, household_id)
    task = await _task(
        session,
        household_id=household_id,
        task_id=task_id,
        user_id=user.id,
    )
    if task.source != "order_images":
        raise HTTPException(status_code=404, detail="order import not found")
    image_count = await session.scalar(
        select(func.count(ImportImage.id)).where(ImportImage.task_id == task.id)
    )
    if not image_count:
        raise HTTPException(status_code=422, detail="upload at least one image")
    if task.status not in {
        ImportTaskStatus.PENDING,
        ImportTaskStatus.FAILED,
    }:
        raise HTTPException(status_code=409, detail="task already started")
    task.status = ImportTaskStatus.PENDING
    task.error_message = None
    await session.commit()
    if get_settings().recognition_execution_mode == "inline":
        task = await process_order_task(session, task)
    else:
        task.status = ImportTaskStatus.PROCESSING
        await session.commit()
        await session.refresh(task)
    return await _task_response(session, task)


@router.get(
    "/imports/{task_id}",
    response_model=RecognitionTaskResponse,
)
async def get_order_import(
    household_id: str,
    task_id: str,
    session: DbSession,
    user: CurrentUser,
) -> RecognitionTaskResponse:
    await _household(session, user, household_id)
    task = await _task(
        session,
        household_id=household_id,
        task_id=task_id,
        user_id=user.id,
    )
    if task.source != "order_images":
        raise HTTPException(status_code=404, detail="order import not found")
    return await _task_response(session, task)


@router.post(
    "/imports/{task_id}/confirm",
    response_model=ConfirmationResponse,
)
async def confirm_order_import(
    household_id: str,
    task_id: str,
    payload: ConfirmActionsWrite,
    session: DbSession,
    user: CurrentUser,
    idempotency_key: str = Header(alias="X-Idempotency-Key"),
) -> ConfirmationResponse:
    household = await _household(session, user, household_id)
    task = await _task(
        session,
        household_id=household_id,
        task_id=task_id,
        user_id=user.id,
    )
    if task.source != "order_images":
        raise HTTPException(status_code=404, detail="order import not found")
    if any(action.type != "add" for action in payload.actions):
        raise HTTPException(
            status_code=422,
            detail="order imports can only add inventory",
        )
    try:
        task = await confirm_actions(
            session,
            task_id=task.id,
            household_id=household_id,
            user_id=user.id,
            actions=payload.actions,
            idempotency_key=idempotency_key,
        )
    except ConfirmationConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    await session.refresh(household)
    return ConfirmationResponse(
        task_id=task.id,
        status=task.status,
        inventory_revision=household.inventory_revision,
    )


@router.post(
    "/imports/{task_id}/cancel",
    response_model=RecognitionTaskResponse,
)
async def cancel_order_import(
    household_id: str,
    task_id: str,
    session: DbSession,
    user: CurrentUser,
) -> RecognitionTaskResponse:
    await _household(session, user, household_id)
    task = await _task(
        session,
        household_id=household_id,
        task_id=task_id,
        user_id=user.id,
    )
    if task.status == ImportTaskStatus.CONFIRMED:
        raise HTTPException(status_code=409, detail="confirmed task cannot cancel")
    await delete_task_images(session, task.id)
    task.status = ImportTaskStatus.CANCELLED
    task.original_files_expires_at = None
    await session.commit()
    await session.refresh(task)
    return await _task_response(session, task)
