"""Tuong tac cheo NOI BO: tai khoan TUONG TAC CHEO (booster) tha tim / follow / binh luan
/ dang lai vao bai cua tai khoan XAY KENH (channel).

Khac nuoi huong ra ngoai (outreach.py - dich la nguoi la tren feed), o day dich la bai
cua chinh doi minh, lay tu nhung lan dang da len (Attempt co remote_url). Booster khong
dang bai, khong nuoi ra ngoai, khong can proxy; mot booster mot ngay:

    tha tim 2-5 bai, follow 1-2 kenh chua follow, binh luan sticker 0-1, dang lai 0-1
    (tu ngay thu 2). Moi bai moi ngay nhan toi da BOOST_PER_POST_CAP luot tha tim tu doi
    booster - nghin tai khoan cung nhau dap vao mot bai trong mot gio la dau vet ro nhat.

Job sinh ra la ActivityJob co target_account_id = kenh (canh noi bo trong do thi), chay
bang dung runner cua nen tang (TikTok trinh duyet, IG/X/Reddit API).
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from seeding.config import get_settings
from seeding.domain import profiles as profiles_mod
from seeding.domain import readiness
from seeding.domain.models import (
    Account,
    AccountRole,
    AccountStatus,
    ActivityJob,
    ActivityKind,
    Attempt,
    JobStatus,
    Platform,
    PostJob,
)
from seeding.platforms.outreach import _DURATION, COMMENT_AFTER_LIKE, REPOST_AFTER_LIKE
from seeding.scheduling import windows as windows_mod

log = structlog.get_logger(__name__)

LIKES_PER_DAY = (2, 5)
FOLLOWS_PER_DAY = (1, 2)
COMMENTS_PER_DAY = (0, 1)
REPOSTS_PER_DAY = (0, 1)
POST_AGE_DAYS = 7


@dataclass(frozen=True, slots=True)
class ChannelPost:
    url: str
    account_id: uuid.UUID
    handle: str
    posted_at: datetime


async def channel_posts(session: AsyncSession, platform: Platform) -> list[ChannelPost]:
    """Bai cua tai khoan xay kenh da len trong POST_AGE_DAYS ngay, moi nhat truoc."""
    since = datetime.now(UTC) - timedelta(days=POST_AGE_DAYS)
    rows = (
        await session.execute(
            select(Attempt.remote_url, Account.id, Account.handle, Attempt.finished_at)
            .join(PostJob, PostJob.id == Attempt.job_id)
            .join(Account, Account.id == PostJob.account_id)
            .where(
                Attempt.ok.is_(True),
                Attempt.remote_url.is_not(None),
                Attempt.finished_at >= since,
                Account.platform == platform,
                Account.role == AccountRole.CHANNEL,
            )
            .order_by(Attempt.finished_at.desc())
        )
    ).all()
    out: list[ChannelPost] = []
    seen: set[str] = set()
    for url, aid, handle, at in rows:
        if url in seen or (isinstance(url, str) and "deleted" in url):
            continue
        seen.add(url)
        out.append(ChannelPost(url=url, account_id=aid, handle=handle, posted_at=at))
    return out


async def channel_accounts(session: AsyncSession, platform: Platform) -> list[Account]:
    return list(
        (
            await session.execute(
                select(Account).where(
                    Account.platform == platform,
                    Account.role == AccountRole.CHANNEL,
                    Account.status.in_([AccountStatus.WARMING, AccountStatus.ACTIVE]),
                )
            )
        )
        .unique()
        .scalars()
        .all()
    )


async def _touched_urls(
    session: AsyncSession, booster_id: uuid.UUID, kind: ActivityKind
) -> set[str]:
    rows = (
        await session.execute(
            select(ActivityJob.target_url).where(
                ActivityJob.account_id == booster_id,
                ActivityJob.kind == kind,
                ActivityJob.status != JobStatus.FAILED,
            )
        )
    ).scalars()
    return {u for u in rows if u}


async def _followed_channels(session: AsyncSession, booster_id: uuid.UUID) -> set[uuid.UUID]:
    rows = (
        await session.execute(
            select(ActivityJob.target_account_id).where(
                ActivityJob.account_id == booster_id,
                ActivityJob.kind == ActivityKind.FOLLOW,
                ActivityJob.target_account_id.is_not(None),
                ActivityJob.status != JobStatus.FAILED,
            )
        )
    ).scalars()
    return {a for a in rows if a}


async def _likes_today_per_post(session: AsyncSession, day: date) -> dict[str, int]:
    start = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
    rows = (
        await session.execute(
            select(ActivityJob.target_url, func.count())
            .where(
                ActivityJob.kind == ActivityKind.ENGAGE,
                ActivityJob.target_account_id.is_not(None),
                ActivityJob.scheduled_at >= start,
                ActivityJob.scheduled_at < start + timedelta(days=1),
            )
            .group_by(ActivityJob.target_url)
        )
    ).all()
    return {u: int(n) for u, n in rows if u}


async def has_plan_today(session: AsyncSession, booster_id: uuid.UUID, day: date) -> bool:
    start = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
    n = (
        await session.execute(
            select(func.count())
            .select_from(ActivityJob)
            .where(
                ActivityJob.account_id == booster_id,
                ActivityJob.scheduled_at >= start,
                ActivityJob.scheduled_at < start + timedelta(days=1),
            )
        )
    ).scalar_one()
    return int(n) > 0


def budget_for(booster: Account, now: datetime, rng: random.Random) -> tuple[int, int, int, int]:
    day = (now - booster.warmup_started_at).days if booster.warmup_started_at else 0
    likes = rng.randint(*LIKES_PER_DAY)
    follows = rng.randint(*FOLLOWS_PER_DAY)
    comments = rng.randint(*COMMENTS_PER_DAY)
    reposts = rng.randint(*REPOSTS_PER_DAY) if day >= 2 else 0
    if day <= 0:
        return max(1, likes // 2), follows, 0, 0
    return likes, follows, min(comments, likes), min(reposts, likes)


def build_jobs(
    booster: Account,
    posts: list[ChannelPost],
    channels: list[Account],
    *,
    liked_before: set[str],
    followed_before: set[uuid.UUID],
    likes_today: dict[str, int],
    cap: int,
    budget: tuple[int, int, int, int],
    day: date,
    window: tuple[datetime, datetime],
    rng: random.Random,
    profile_url,
) -> list[ActivityJob]:
    """Thuan tuy: chon bai chua tha, chua qua tran ngay, uu tien bai moi (xao nhe)."""
    n_likes, n_follows, n_comments, n_reposts = budget
    fresh = [p for p in posts if p.url not in liked_before and likes_today.get(p.url, 0) < cap]
    # Uu tien bai moi nhung khong dong deu: xao trong tung nhom 5 bai moi nhat.
    picked: list[ChannelPost] = []
    for i in range(0, len(fresh), 5):
        chunk = fresh[i : i + 5]
        rng.shuffle(chunk)
        picked.extend(chunk)
    liked = picked[:n_likes]
    to_follow = [c for c in channels if c.id not in followed_before and c.id != booster.id]
    rng.shuffle(to_follow)
    followed = to_follow[:n_follows]
    commented = liked[:n_comments]
    reposted = (liked[n_comments:] or liked)[:n_reposts]

    total = len(liked) + len(followed) + len(commented) + len(reposted)
    if total == 0:
        return []
    start, end = window
    slots = windows_mod.spread(day, total, rng, start, end)
    jobs: list[ActivityJob] = []
    when_liked: dict[str, datetime] = {}

    def make(kind: ActivityKind, url: str, target_id: uuid.UUID, when: datetime) -> ActivityJob:
        low, high = _DURATION[kind]
        return ActivityJob(
            account_id=booster.id,
            kind=kind,
            scheduled_at=when,
            duration_seconds=rng.randint(low, high),
            target_url=url,
            target_account_id=target_id,
        )

    i = 0
    for p in liked:
        jobs.append(make(ActivityKind.ENGAGE, p.url, p.account_id, slots[i]))
        when_liked[p.url] = slots[i]
        i += 1
    for c in followed:
        jobs.append(make(ActivityKind.FOLLOW, profile_url(c.handle), c.id, slots[i]))
        i += 1
    for p in commented:
        when = max(slots[i], when_liked[p.url] + COMMENT_AFTER_LIKE)
        jobs.append(make(ActivityKind.COMMENT, p.url, p.account_id, when))
        i += 1
    for p in reposted:
        when = max(slots[i], when_liked[p.url] + REPOST_AFTER_LIKE)
        jobs.append(make(ActivityKind.REPOST, p.url, p.account_id, when))
        i += 1
    return jobs


def _profile_url_for(platform: Platform):
    if platform is Platform.TIKTOK:
        from seeding.platforms.tiktok.warm import profile_url
    elif platform is Platform.INSTAGRAM:
        from seeding.platforms.instagram.warm import profile_url
    elif platform is Platform.X:
        from seeding.platforms.x.warm import profile_url
    elif platform is Platform.REDDIT:
        from seeding.platforms.reddit.warm import profile_url
    elif platform is Platform.FACEBOOK:
        from seeding.platforms.facebook.interact import profile_url
    else:
        return None
    return profile_url


async def plan_all(session: AsyncSession, *, day: date | None = None) -> int:
    """Moi booster dang chay, moi nen tang: mot lich cho hom nay neu chua co."""
    now = datetime.now(UTC)
    day = day or now.date()
    cap = get_settings().boost_per_post_cap
    total = 0
    boosters = list(
        (
            await session.execute(
                select(Account.id, Account.platform).where(
                    Account.role == AccountRole.BOOSTER,
                    Account.status.in_([AccountStatus.WARMING, AccountStatus.ACTIVE]),
                )
            )
        ).all()
    )
    if not boosters:
        return 0
    by_platform: dict[Platform, list[uuid.UUID]] = {}
    for bid, platform in boosters:
        by_platform.setdefault(platform, []).append(bid)

    for platform, ids in by_platform.items():
        profile_url = _profile_url_for(platform)
        if profile_url is None:
            continue
        posts = await channel_posts(session, platform)
        channels = await channel_accounts(session, platform)
        if not posts and not channels:
            continue
        window = await windows_mod.window_for(session, platform, day)
        likes_today = await _likes_today_per_post(session, day)
        for bid in ids:
            try:
                booster = await session.get(Account, bid)
                profile = await profiles_mod.get_for_account(session, bid)
                if booster is None or not readiness.check(booster, profile).ready:
                    continue
                if await has_plan_today(session, bid, day):
                    continue
                rng = random.Random(f"boost:{bid}:{day.isoformat()}")
                jobs = build_jobs(
                    booster,
                    posts,
                    channels,
                    liked_before=await _touched_urls(session, bid, ActivityKind.ENGAGE),
                    followed_before=await _followed_channels(session, bid),
                    likes_today=likes_today,
                    cap=cap,
                    budget=budget_for(booster, now, rng),
                    day=day,
                    window=window,
                    rng=rng,
                    profile_url=profile_url,
                )
                for j in jobs:
                    session.add(j)
                    if j.kind is ActivityKind.ENGAGE and j.target_url:
                        likes_today[j.target_url] = likes_today.get(j.target_url, 0) + 1
                await session.commit()
                total += len(jobs)
            except Exception as exc:
                await session.rollback()
                log.warning(
                    "boost.plan_failed", booster=str(bid), error=f"{type(exc).__name__}: {exc}"
                )
    if total:
        log.info("boost.planned", jobs=total, boosters=len(boosters))
    return total
