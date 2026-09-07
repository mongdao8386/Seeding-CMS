"""Nuoi tai khoan HUONG RA NGOAI: tha tim, theo doi, binh luan tren noi dung xu huong.

Khac core/graph.py, cai do moc cac tai khoan CUA MINH voi nhau. Do thi noi bo can, nhung
mot tai khoan moi ma chi tuong tac voi sau tai khoan moi khac la mot cum kin - va cum
kin la thu de nhin ra nhat. Nguoi that xem For You, tha tim video dang len, theo doi
vai creator la, thinh thoang binh luan. Day la cai do.

Nguon dich la For You CUA CHINH TAI KHOAN DO, doc qua proxy cua no (core/tiktok_web).
Nen moi tai khoan tuong tac voi mot bo video khac nhau - bay tai khoan cung tha tim
cung tam video trong cung mot gio lai la mot cum kin kieu khac.

Ngan sach moi ngay co y nho. Trong hai ngay dau (quiet period cua rate governor) day
la TOAN BO viec tai khoan lam, nen no phai trong nhu nguoi that, khong phai nhu may.
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from seeding.core import activity as activity_mod
from seeding.core import profiles as profiles_mod
from seeding.core import readiness
from seeding.core.tiktok_web import ORIGIN, FeedItem, TikTokWeb
from seeding.models import (
    Account,
    AccountStatus,
    ActivityJob,
    ActivityKind,
    Platform,
    Profile,
    Proxy,
)

log = structlog.get_logger(__name__)

# Ngan sach mot ngay (min, max). Ngay dau tien cua warm-up lay mot nua.
LIKES_PER_DAY = (4, 8)
FOLLOWS_PER_DAY = (1, 3)
COMMENTS_PER_DAY = (0, 2)

# Bo qua video qua nho (khong phai xu huong) - va khong follow creator qua lon: mot tai
# khoan moi follow toan nguoi 10 trieu follower cung la mot mau hinh.
MIN_VIEWS = 20_000
FEED_COUNT = 24

# Binh luan di SAU tha tim cung video it nhat tung nay - nguoi that xem, tha tim, roi
# moi go. Va khong bao gio binh luan video minh chua tha tim.
COMMENT_AFTER_LIKE = timedelta(minutes=8)

_DURATION = {
    ActivityKind.ENGAGE: (30, 90),
    ActivityKind.FOLLOW: (40, 120),
    ActivityKind.COMMENT: (60, 180),
}


@dataclass(frozen=True, slots=True)
class Budget:
    likes: int
    follows: int
    comments: int


def budget_for(account: Account, now: datetime, rng: random.Random) -> Budget:
    """Ngan sach hom nay. Ngay 0 cua warm-up: mot nua, va khong binh luan."""
    day = (now - account.warmup_started_at).days if account.warmup_started_at else 0
    likes = rng.randint(*LIKES_PER_DAY)
    follows = rng.randint(*FOLLOWS_PER_DAY)
    comments = rng.randint(*COMMENTS_PER_DAY)
    if day <= 0:
        return Budget(max(1, likes // 2), max(0, follows // 2), 0)
    return Budget(likes, follows, min(comments, likes))


def pick_targets(
    items: list[FeedItem], *, own_handles: set[str], rng: random.Random
) -> list[FeedItem]:
    """Loc feed thanh danh sach dich: bo tai khoan cua minh, bo video nho, moi creator
    mot video, xao thu tu."""
    seen: set[str] = set()
    out: list[FeedItem] = []
    for it in items:
        if it.author_handle in own_handles or it.author_handle in seen:
            continue
        if it.views < MIN_VIEWS:
            continue
        seen.add(it.author_handle)
        out.append(it)
    rng.shuffle(out)
    return out


def profile_url(handle: str) -> str:
    return f"{ORIGIN}/@{handle}"


async def count_outward_for_day(session: AsyncSession, account_id: uuid.UUID, day: date) -> int:
    start = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
    stmt = (
        select(func.count())
        .select_from(ActivityJob)
        .where(
            ActivityJob.account_id == account_id,
            ActivityJob.target_account_id.is_(None),
            ActivityJob.kind.in_([ActivityKind.ENGAGE, ActivityKind.FOLLOW, ActivityKind.COMMENT]),
            ActivityJob.scheduled_at >= start,
            ActivityJob.scheduled_at < start + timedelta(days=1),
        )
    )
    return int((await session.execute(stmt)).scalar_one())


def build_jobs(
    account: Account,
    targets: list[FeedItem],
    budget: Budget,
    *,
    day: date,
    window: tuple[datetime, datetime],
    rng: random.Random,
) -> list[ActivityJob]:
    """Xep ngan sach len danh sach dich thanh job, rai deu trong khung gio.

    Thuan tuy (khong DB, khong mang) de test duoc: cung feed, cung rng thi cung lich.
    """
    if not targets:
        return []
    liked = targets[: budget.likes]
    followed = targets[: budget.follows]  # follow creator cua video da tha tim
    commented = liked[: budget.comments]

    total = len(liked) + len(followed) + len(commented)
    start, end = window
    slots = activity_mod._slots(day, total, rng, start, end)
    jobs: list[ActivityJob] = []
    when_liked: dict[str, datetime] = {}

    def make(kind: ActivityKind, url: str, when: datetime) -> ActivityJob:
        low, high = _DURATION[kind]
        return ActivityJob(
            account_id=account.id,
            kind=kind,
            scheduled_at=when,
            duration_seconds=rng.randint(low, high),
            target_url=url,
        )

    i = 0
    for it in liked:
        jobs.append(make(ActivityKind.ENGAGE, it.url, slots[i]))
        when_liked[it.item_id] = slots[i]
        i += 1
    for it in followed:
        jobs.append(make(ActivityKind.FOLLOW, profile_url(it.author_handle), slots[i]))
        i += 1
    for it in commented:
        when = max(slots[i], when_liked[it.item_id] + COMMENT_AFTER_LIKE)
        jobs.append(make(ActivityKind.COMMENT, it.url, when))
        i += 1
    return jobs


async def plan_for_account(
    session: AsyncSession,
    account: Account,
    profile: Profile,
    *,
    day: date | None = None,
    now: datetime | None = None,
    rng: random.Random | None = None,
    web_factory=TikTokWeb,
) -> list[ActivityJob]:
    """Lich huong ra ngoai cho mot tai khoan trong mot ngay. Da co thi khong lam lai."""
    now = now or datetime.now(UTC)
    day = day or now.date()
    rng = rng or random.Random(f"outreach:{account.id}:{day.isoformat()}")

    if await count_outward_for_day(session, account.id, day):
        return []

    own = set(
        (await session.execute(select(Account.handle).where(Account.platform == account.platform)))
        .scalars()
        .all()
    )
    async with web_factory(profile) as tt:
        items = await tt.feed(FEED_COUNT)
    targets = pick_targets(items, own_handles=own, rng=rng)
    if not targets:
        log.warning("outreach.no_targets", handle=account.handle, feed=len(items))
        return []

    window = await activity_mod.window_for(session, account.platform, day)
    jobs = build_jobs(
        account, targets, budget_for(account, now, rng), day=day, window=window, rng=rng
    )
    for job in jobs:
        session.add(job)
    await session.commit()
    log.info("outreach.planned", handle=account.handle, jobs=len(jobs), targets=len(targets))
    return jobs


async def plan_all(session: AsyncSession, *, day: date | None = None) -> int:
    """Moi tai khoan TikTok dang nuoi hoac dang hoat dong, co profile san sang."""
    stmt = select(Account).where(
        Account.platform == Platform.TIKTOK,
        Account.status.in_([AccountStatus.WARMING, AccountStatus.ACTIVE]),
    )
    total = 0
    for account in list((await session.execute(stmt)).scalars().all()):
        profile = await profiles_mod.get_for_account(session, account.id)
        if not readiness.check(account, profile).ready:
            continue
        # TikTokWeb doc profile.proxy; get_for_account khong nap san, va lazy-load trong
        # phien async la MissingGreenlet. Nap tuong minh.
        if profile.proxy_id is not None and "proxy" not in profile.__dict__:
            profile.proxy = await session.get(Proxy, profile.proxy_id)
        try:
            total += len(await plan_for_account(session, account, profile, day=day))
        except Exception as exc:
            # Mot tai khoan doc feed hong (proxy treo, signer chet) khong duoc chan ca doi.
            await session.rollback()
            log.warning(
                "outreach.plan_failed", handle=account.handle, error=f"{type(exc).__name__}: {exc}"
            )
    return total


def is_outward(job: ActivityJob) -> bool:
    return job.target_account_id is None and job.kind in {
        ActivityKind.ENGAGE,
        ActivityKind.FOLLOW,
        ActivityKind.COMMENT,
    }


__all__ = [
    "Budget",
    "budget_for",
    "build_jobs",
    "is_outward",
    "pick_targets",
    "plan_all",
    "plan_for_account",
]
