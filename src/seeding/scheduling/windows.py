"""Khung gio THUC cua mot nen tang trong ngay - de rai viec nuoi vao gio nguoi that thuc.

Khac gio vang (slots.py, cho DANG BAI): day la khoang tu luc "day" den luc "ngu" cua
tai khoan tren nen tang do. Ghi de theo tung thu trong tuan qua bang platform_windows;
khong co ban ghi thi 7h-23h.
"""

from __future__ import annotations

import random
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from seeding.domain.models import Platform, PlatformWindow

ACTIVE_FROM = time(7, 0)
ACTIVE_TO = time(23, 0)


def _at(day: date, hour: int) -> datetime:
    """`hour` trong `day` theo GIO DIA PHUONG (SCHEDULE_TIMEZONE), tra ve UTC. Nhan ca
    24 = nua dem ket thuc ngay (time(24) khong ton tai). 7h-23h phai la 7h-23h Viet Nam,
    khong phai 7h-23h UTC = 14h-6h sang hom sau."""
    from seeding.scheduling.slots import tz

    local = datetime.combine(day, time.min, tzinfo=tz()) + timedelta(hours=hour)
    return local.astimezone(UTC)


async def window_for(
    session: AsyncSession, platform: Platform, day: date
) -> tuple[datetime, datetime]:
    """Khung gio thuc cua (nen tang, thu). Nhan `day` chu khong tu lay hom nay: lap lich
    chay truoc mot ngay, lay nham thu la sai gio ma khong bao loi."""
    row = (
        await session.execute(
            select(PlatformWindow).where(
                PlatformWindow.platform == platform,
                PlatformWindow.weekday == day.weekday(),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return _at(day, ACTIVE_FROM.hour), _at(day, ACTIVE_TO.hour)
    return _at(day, row.active_from_hour), _at(day, row.active_to_hour)


def spread(
    day: date,
    count: int,
    rng: random.Random,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[datetime]:
    """Rai `count` moc trong khung gio: chia deu thanh o roi lech ngau nhien trong o.
    Random tu do hay tao cum ba bon lan lien tiep roi im lang ca buoi."""
    start = start or _at(day, ACTIVE_FROM.hour)
    end = end or _at(day, ACTIVE_TO.hour)
    span = (end - start).total_seconds()
    if count <= 0 or span <= 0:
        return []
    bucket = span / count
    return [
        start + timedelta(seconds=i * bucket + rng.uniform(0, bucket * 0.9)) for i in range(count)
    ]


# Ten cu ma warm.py (port tu legacy) goi.
_slots = spread
