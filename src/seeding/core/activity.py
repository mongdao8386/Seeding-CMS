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
# Ghi de duoc theo TUNG NGAY TRONG TUAN qua bang platform_windows. Hai ly do:
#   - Gio cao diem cua TikTok va Facebook khac han nhau, va mot tai khoan hoat dong
#     lech han voi nhip cua nen tang do la mot dau vet.
#   - Nguoi that khong thuc day va di ngu dung mot khung gio bay ngay lien. Dung mot
#     khung cho ca tuan cung la mot mau hinh, chi la kin dao hon gio 3 gio sang.
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


def _at(day: date, hour: int) -> datetime:
    """Moc thoi gian cua `hour` trong `day`.

    Nhan ca gio 24 = nua dem ket thuc ngay. `time(24, 0)` khong ton tai trong Python,
    nen neu chi dung `time` thi khong co cach nao dien ta "hoat dong den nua dem" - va
    do la khung gio binh thuong nhat cua buoi toi.
    """
    return datetime.combine(day, time.min, tzinfo=UTC) + timedelta(hours=hour)


async def window_for(
    session: AsyncSession, platform: Platform, day: date
) -> tuple[datetime, datetime]:
    """Khung gio thuc cua mot nen tang trong MOT NGAY cu the, da thanh moc thoi gian.

    Tra cuu theo (nen tang, thu trong tuan). Khong co ban ghi thi dung mac dinh.

    Nhan `day` chu khong tu lay hom nay: ham lap lich chay truoc mot ngay, va lay nham
    thu cua hom nay de rai lich cho ngay mai la mot loi khong bao gio lo ra thanh loi -
    lich van duoc tao, chi la sai gio, va no lang le lam mong tai khoan di.
    """
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


def _slots(
    day: date,
    count: int,
    rng: random.Random,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[datetime]:
    """Rai `count` moc gio trong khung gio thuc cua mot ngay.

    Chia deu thanh cac o roi lech ngau nhien trong o, thay vi random tu do: random
    tu do hay tao ra cum ba bon lan lien tiep roi im lang ca buoi.
    """
    start = start or _at(day, ACTIVE_FROM.hour)
    end = end or _at(day, ACTIVE_TO.hour)
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

    start, end = await window_for(session, account.platform, day)

    jobs = []
    for when in _slots(day, count, rng, start, end):
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
