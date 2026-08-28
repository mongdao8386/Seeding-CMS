"""Lap lich hoat dong nen.

Mot tai khoan chi dang bai roi bien mat la mau hinh bot ro nhat. Moi acc can nhieu
lan "song" tren nen tang ma khong dang gi ca: mo feed, cuon vai phut, tha cam xuc,
xem het mot video, vao roi ra.

So job loai nay nen nhieu gap 5-10 lan job dang bai. Day la chi phi tinh toan ma hau
het nguoi tu xay deu quen dua vao du toan - no la phan lon tai cua he thong, khong
phai phan phu.
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from seeding.models import (
    Account,
    AccountStatus,
    ActivityJob,
    ActivityKind,
    JobStatus,
    Platform,
    PlatformWindow,
)

# Bao nhieu lan hoat dong nen cho moi bai dang.
ACTIVITY_PER_POST = 6

# Gio thuc mac dinh (theo UTC cua he thong). Tai khoan hoat dong luc 4 gio sang moi
# ngay la bat thuong ro hon la tai khoan it hoat dong.
#
# Moi nen tang ghi de duoc bang bang platform_windows: gio cao diem cua TikTok va
# Facebook khac han nhau, va mot tai khoan hoat dong lech han voi nhip cua nen tang do
# la mot dau vet - it ro hon fingerprint, nhung van la mot dau vet.
ACTIVE_FROM = time(7, 0)
ACTIVE_TO = time(23, 0)

# Ty trong cac loai. Cuon feed la viec pho bien nhat cua nguoi that.
_WEIGHTS: list[tuple[ActivityKind, int]] = [
    (ActivityKind.BROWSE_FEED, 55),
    (ActivityKind.READ_POST, 25),
    (ActivityKind.REACT, 15),
    (ActivityKind.WATCH_VIDEO, 5),
]

_DURATIONS: dict[ActivityKind, tuple[int, int]] = {
    ActivityKind.BROWSE_FEED: (60, 300),
    ActivityKind.READ_POST: (25, 120),
    ActivityKind.REACT: (20, 90),
    ActivityKind.WATCH_VIDEO: (45, 240),
}


def _pick_kind(rng: random.Random) -> ActivityKind:
    total = sum(w for _, w in _WEIGHTS)
    roll = rng.randrange(total)
    upto = 0
    for kind, weight in _WEIGHTS:
        upto += weight
        if roll < upto:
            return kind
    return ActivityKind.BROWSE_FEED


async def window_for(session: AsyncSession, platform: Platform) -> tuple[time, time]:
    """Khung gio thuc cua mot nen tang. Khong co ban ghi thi dung mac dinh."""
    row = (
        await session.execute(select(PlatformWindow).where(PlatformWindow.platform == platform))
    ).scalar_one_or_none()
    if row is None:
        return ACTIVE_FROM, ACTIVE_TO
    return time(row.active_from_hour, 0), time(row.active_to_hour, 0)


def _slots(
    day: date,
    count: int,
    rng: random.Random,
    active_from: time = ACTIVE_FROM,
    active_to: time = ACTIVE_TO,
) -> list[datetime]:
    """Rai `count` moc gio trong khung gio thuc cua mot ngay.

    Chia deu thanh cac o roi lech ngau nhien trong o, thay vi random tu do: random
    tu do hay tao ra cum ba bon lan lien tiep roi im lang ca buoi.
    """
    start = datetime.combine(day, active_from, tzinfo=UTC)
    end = datetime.combine(day, active_to, tzinfo=UTC)
    span = (end - start).total_seconds()
    if count <= 0 or span <= 0:
        return []

    bucket = span / count
    return [
        start + timedelta(seconds=i * bucket + rng.uniform(0, bucket * 0.9)) for i in range(count)
    ]


async def plan_for_account(
    session: AsyncSession,
    account: Account,
    *,
    day: date | None = None,
    count: int | None = None,
    rng: random.Random | None = None,
) -> list[ActivityJob]:
    """Sinh lich hoat dong nen cho mot tai khoan trong mot ngay.

    Goi lai cho cung mot ngay se khong nhan doi lich - da co job cho ngay do thi bo qua.
    """
    rng = rng or random.Random()
    day = day or datetime.now(UTC).date()
    count = count if count is not None else max(1, account.daily_cap * ACTIVITY_PER_POST)

    if await count_for_day(session, account.id, day):
        return []

    active_from, active_to = await window_for(session, account.platform)

    jobs = []
    for when in _slots(day, count, rng, active_from, active_to):
        kind = _pick_kind(rng)
        low, high = _DURATIONS[kind]
        job = ActivityJob(
            account_id=account.id,
            kind=kind,
            scheduled_at=when,
            duration_seconds=rng.randint(low, high),
        )
        session.add(job)
        jobs.append(job)

    await session.commit()
    return jobs


async def count_for_day(session: AsyncSession, account_id: uuid.UUID, day: date) -> int:
    start = datetime.combine(day, time.min, tzinfo=UTC)
    stmt = (
        select(func.count())
        .select_from(ActivityJob)
        .where(
            ActivityJob.account_id == account_id,
            ActivityJob.scheduled_at >= start,
            ActivityJob.scheduled_at < start + timedelta(days=1),
        )
    )
    return int((await session.execute(stmt)).scalar_one())


async def plan_all(
    session: AsyncSession, *, day: date | None = None, rng: random.Random | None = None
) -> int:
    """Lap lich cho moi tai khoan dang hoat dong. Chay mot lan moi ngay.

    Bo qua tai khoan dang cho nguoi xu ly: bat chung cuon feed khong giup gi, ma con
    lam ban nhat ky vong doi phien.
    """
    stmt = select(Account).where(Account.status.in_([AccountStatus.WARMING, AccountStatus.ACTIVE]))
    accounts = list((await session.execute(stmt)).scalars().all())

    total = 0
    for account in accounts:
        total += len(await plan_for_account(session, account, day=day, rng=rng))
    return total


async def due_activity(
    session: AsyncSession, now: datetime | None = None, limit: int = 20
) -> list[ActivityJob]:
    """Job hoat dong nen toi gio, cua nhung tai khoan con chay duoc.

    Loc theo trang thai tai khoan ngay trong cau truy van thay vi don dep bang UPDATE
    khi tai khoan chet: lich da lap nam rai ca ngay, va tai khoan co the quay lai
    trang thai chay duoc bat cu luc nao sau khi nguoi giai xong checkpoint.
    """
    now = now or datetime.now(UTC)
    stmt = (
        select(ActivityJob)
        .join(Account, Account.id == ActivityJob.account_id)
        .where(
            ActivityJob.status == JobStatus.SCHEDULED,
            ActivityJob.scheduled_at <= now,
            Account.status.in_([AccountStatus.WARMING, AccountStatus.ACTIVE]),
        )
        .order_by(ActivityJob.scheduled_at)
        .limit(limit)
    )
    return list((await session.execute(stmt)).unique().scalars().all())
