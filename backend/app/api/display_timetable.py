from __future__ import annotations

from datetime import datetime
from io import BytesIO
import re
from typing import Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select

from app.api.dependencies import CurrentUser, DbSession, require_household_member
from app.db.models import Household
from app.services.display_renderer import DISPLAY_TIMEZONE, native_image_to_portrait
from app.services.timetable_renderer import default_timetable_periods, render_timetable_image


router = APIRouter(
    prefix="/v1/households/{household_id}/display-timetable",
    tags=["display-timetable"],
)

TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def _minutes(value: str) -> int:
    hour, minute = value.split(":", 1)
    return int(hour) * 60 + int(minute)


class TimetablePeriod(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    id: str = Field(min_length=1, max_length=24, pattern=r"^[a-z0-9-]+$")
    section: Literal["morning", "afternoon"]
    start_time: str
    end_time: str

    @field_validator("start_time", "end_time")
    @classmethod
    def validate_time(cls, value: str) -> str:
        if not TIME_PATTERN.fullmatch(value):
            raise ValueError("time must use HH:MM")
        return value

    @model_validator(mode="after")
    def validate_range(self) -> TimetablePeriod:
        if _minutes(self.start_time) >= _minutes(self.end_time):
            raise ValueError("period start time must be before end time")
        return self


class TimetableEntry(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    weekday: int = Field(ge=1, le=7)
    period_id: str = Field(min_length=1, max_length=24)
    course_name: str = Field(min_length=1, max_length=6)
    note: str = Field(default="", max_length=8)


class TimetableWrite(BaseModel):
    orientation: Literal["portrait", "landscape"] = "portrait"
    periods: list[TimetablePeriod] = Field(min_length=1, max_length=10)
    entries: list[TimetableEntry] = Field(default_factory=list, max_length=70)

    @model_validator(mode="after")
    def validate_schedule(self) -> TimetableWrite:
        period_ids = [period.id for period in self.periods]
        if len(period_ids) != len(set(period_ids)):
            raise ValueError("period ids must be unique")
        morning = [period for period in self.periods if period.section == "morning"]
        afternoon = [period for period in self.periods if period.section == "afternoon"]
        if len(morning) > 6 or len(afternoon) > 6:
            raise ValueError("morning and afternoon may contain at most 6 periods each")
        if self.periods != morning + afternoon:
            raise ValueError("all morning periods must come before afternoon periods")
        previous_end = -1
        for period in self.periods:
            start = _minutes(period.start_time)
            if start < previous_end:
                raise ValueError("periods must be ordered and may not overlap")
            previous_end = _minutes(period.end_time)
        seen: set[tuple[int, str]] = set()
        valid_ids = set(period_ids)
        for entry in self.entries:
            if entry.period_id not in valid_ids:
                raise ValueError("entry references an unknown period")
            key = (entry.weekday, entry.period_id)
            if key in seen:
                raise ValueError("each weekday and period may contain only one course")
            seen.add(key)
        return self


class TimetableResponse(BaseModel):
    orientation: Literal["portrait", "landscape"]
    periods: list[TimetablePeriod]
    entries: list[TimetableEntry]
    ready: bool
    max_total_periods: int = 10
    max_periods_per_section: int = 6


async def _household(
    session: DbSession,
    user: CurrentUser,
    household_id: str,
    *,
    lock: bool = False,
) -> Household:
    await require_household_member(session, household_id=household_id, user_id=user.id)
    statement = select(Household).where(Household.id == household_id)
    if lock:
        statement = statement.with_for_update()
    household = await session.scalar(statement)
    if household is None:
        raise HTTPException(status_code=404, detail="household not found")
    return household


def _response(household: Household) -> TimetableResponse:
    periods = household.timetable_periods or default_timetable_periods()
    entries = household.timetable_entries or []
    return TimetableResponse(
        orientation=household.timetable_orientation,
        periods=[TimetablePeriod.model_validate(item) for item in periods],
        entries=[TimetableEntry.model_validate(item) for item in entries],
        ready=any(str(item.get("course_name", "")).strip() for item in entries),
    )


@router.get("", response_model=TimetableResponse)
async def read_timetable(
    household_id: str,
    session: DbSession,
    user: CurrentUser,
) -> TimetableResponse:
    return _response(await _household(session, user, household_id))


@router.put("", response_model=TimetableResponse)
async def replace_timetable(
    household_id: str,
    payload: TimetableWrite,
    session: DbSession,
    user: CurrentUser,
) -> TimetableResponse:
    household = await _household(session, user, household_id, lock=True)
    household.timetable_orientation = payload.orientation
    household.timetable_periods = [period.model_dump() for period in payload.periods]
    household.timetable_entries = [entry.model_dump() for entry in payload.entries]
    await session.commit()
    await session.refresh(household)
    return _response(household)


@router.get("/preview", response_class=Response)
async def preview_timetable(
    household_id: str,
    session: DbSession,
    user: CurrentUser,
) -> Response:
    household = await _household(session, user, household_id)
    response = _response(household)
    native_image = render_timetable_image(
        [period.model_dump() for period in response.periods],
        [entry.model_dump() for entry in response.entries],
        orientation=response.orientation,
        now=datetime.now(DISPLAY_TIMEZONE),
    )
    image = (
        native_image_to_portrait(native_image)
        if response.orientation == "portrait"
        else native_image
    )
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return Response(content=output.getvalue(), media_type="image/png")
