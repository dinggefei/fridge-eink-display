from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from lunar_python import Solar


ALMANAC_CALCULATION_VERSION = "lunar-python-1.4.8-sect1"
ALMANAC_DISCLAIMER = "传统民俗，仅供参考"
MAX_ALMANAC_ITEMS = 4


@dataclass(frozen=True, slots=True)
class AlmanacDay:
    displayed_on: date
    weekday: str
    lunar_date: str
    ganzhi: str
    zodiac: str
    seasonal_note: str
    yi: tuple[str, ...]
    ji: tuple[str, ...]
    chong_sha: str
    disclaimer: str = ALMANAC_DISCLAIMER


def _seasonal_note(solar: Solar, lunar) -> str:
    notes: list[str] = []
    jie_qi = lunar.getJieQi()
    if jie_qi:
        notes.append(f"节气 {jie_qi}")
    for festival in [
        *solar.getFestivals(),
        *solar.getOtherFestivals(),
        *lunar.getFestivals(),
        *lunar.getOtherFestivals(),
    ]:
        if festival and festival not in notes:
            notes.append(festival)
    return " · ".join(notes)


def calculate_almanac(displayed_on: date) -> AlmanacDay:
    """Calculate one Shanghai calendar day using lunar-python sect 1."""
    solar = Solar.fromYmd(
        displayed_on.year,
        displayed_on.month,
        displayed_on.day,
    )
    lunar = solar.getLunar()
    lunar_date = (
        f"{lunar.getYearInChinese()}年"
        f"{lunar.getMonthInChinese()}月"
        f"{lunar.getDayInChinese()}"
    )
    ganzhi = (
        f"{lunar.getYearInGanZhi()}年 "
        f"{lunar.getMonthInGanZhi()}月 "
        f"{lunar.getDayInGanZhi()}日"
    )
    chong = lunar.getDayChongDesc().replace("(", "（").replace(")", "）")
    return AlmanacDay(
        displayed_on=displayed_on,
        weekday=f"星期{solar.getWeekInChinese()}",
        lunar_date=lunar_date,
        ganzhi=ganzhi,
        zodiac=lunar.getYearShengXiao(),
        seasonal_note=_seasonal_note(solar, lunar),
        yi=tuple(lunar.getDayYi(1)[:MAX_ALMANAC_ITEMS]),
        ji=tuple(lunar.getDayJi(1)[:MAX_ALMANAC_ITEMS]),
        chong_sha=f"冲{chong} · 煞{lunar.getDaySha()}",
    )
