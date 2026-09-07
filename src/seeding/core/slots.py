"""Khung gio vang dang bai: chon MOC cho mot bai tu bang post_slots.

Bang: nen tang -> thu trong tuan -> danh sach gio (theo settings.schedule_timezone).
Planner goi `choose()` cho tung job. Hai tinh chat quan trong:

  - On dinh: cung RNG (seed theo campaign/group/account) thi cung moc. Lap ke hoach
    lai khong xao lich.
  - Tra deu: trong mot ngay co nhieu moc thi moi tai khoan boc NGAU NHIEN mot moc con
    lai, thay vi tat ca dang chung moc dau tien - bay tai khoan cung dang mot video
    luc 6h00 la mot mau hinh; rai qua 6h/10h/22h thi khong.
"""

from __future__ import annotations

import random
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from seeding.config import get_settings
from seeding.models import Platform, PostSlot

# Rai bai quanh moc toi da bao nhieu giay. Cua so rai cua chien dich (mac dinh 1 gio)
# la de tranh dang cung giay; nhung "6h00" ma dang luc 6h58 thi khong con la 6h00 nua.
JITTER_MAX_SECONDS = 15 * 60
# Nhin truoc bao nhieu ngay. Bang co it nhat mot moc thi trong 7 ngay chac chan gap.
LOOKAHEAD_DAYS = 14

SlotTable = dict[int, list[time]]


def tz() -> ZoneInfo:
    return ZoneInfo(get_settings().schedule_timezone)


async def load(session: AsyncSession) -> dict[Platform, SlotTable]:
    """Toan bo bang, mot lan cho ca ma tran job."""
    out: dict[Platform, SlotTable] = {}
    for row in (await session.execute(select(PostSlot))).scalars():
        out.setdefault(row.platform, {}).setdefault(row.weekday, []).append(
            time(row.hour, row.minute)
        )
    for table in out.values():
        for times in table.values():
            times.sort()
    return out


def choose(
    table: SlotTable, *, not_before: datetime, rng: random.Random, zone: ZoneInfo
) -> datetime:
    """Moc dang bai gan nhat tu `not_before`, tinh trong `zone`, tra ve UTC.

    Ngay dau tien co moc con lai thi chon ngau nhien MOT trong cac moc do (tra deu).
    """
    if not any(table.values()):
        raise ValueError("the slot table is empty")

    local = not_before.astimezone(zone)
    for ahead in range(LOOKAHEAD_DAYS):
        day: date = (local + timedelta(days=ahead)).date()
        candidates = [
            when
            for t in sorted(table.get(day.weekday()) or [])
            if (when := datetime.combine(day, t, tzinfo=zone)) >= local
        ]
        if candidates:
            return rng.choice(candidates).astimezone(UTC)

    raise ValueError(f"no slot within {LOOKAHEAD_DAYS} days")  # pragma: no cover


# Khi rate governor chan mot job, thu lai som nhat sau bao lau. Mot tieng: du de tran
# 24h truot di, va khong quet DB moi 30 giay cho mot job chac chan van bi chan.
DEFER_MIN = timedelta(hours=1)


def defer(
    table: SlotTable | None, *, now: datetime, rng: random.Random, zone: ZoneInfo
) -> datetime:
    """Moc chay lai cho mot job vua bi governor chan.

    Co bang khung gio vang thi bam vao moc ke tiep (cach it nhat DEFER_MIN) - job bi
    chan luc 6h00 vi chua het quiet period thi khi duoc tha phai len vao 7h00 cua
    ngay duoc phep, chu khong phai 6h00 + n tieng roi roi vao 3 gio sang. Khong co
    bang thi lui DEFER_MIN nhu truoc.
    """
    earliest = now + DEFER_MIN
    if not table or not any(table.values()):
        return earliest
    return choose(table, not_before=earliest, rng=rng, zone=zone)
