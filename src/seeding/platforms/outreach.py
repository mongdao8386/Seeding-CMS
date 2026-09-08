"""Nuoi tai khoan HUONG RA NGOAI - phan dung chung cho moi nen tang.

Mot tai khoan moi ma chi tuong tac voi sau tai khoan moi khac la mot cum kin - va cum
kin la thu de nhin ra nhat. Nguoi that xem feed, tha tim video dang len, theo doi vai
creator la, thinh thoang binh luan. Day la cai do.

Nguon dich la feed CUA CHINH TAI KHOAN DO, doc qua proxy cua no. Nen moi tai khoan
tuong tac voi mot bo video khac nhau - bay tai khoan cung tha tim cung tam video trong
cung mot gio lai la mot cum kin kieu khac.

Moi nen tang chi can dua vao hai thu: mot `source_factory(profile)` mo duoc bang
`async with` va co `feed(count)`, va mot `profile_url(handle)`. Con lai - ngan sach,
loc dich, rai gio, khong lam lai ngay da co lich - la chung.
"""

from __future__ import annotations

import random
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Protocol

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from seeding.domain import profiles as profiles_mod
from seeding.domain import readiness
from seeding.domain.models import (
    Account,
    AccountRole,
    AccountStatus,
    ActivityJob,
    ActivityKind,
    Platform,
    Profile,
    Proxy,
)
from seeding.scheduling import windows as activity_mod

log = structlog.get_logger(__name__)

# Ngan sach mot ngay (min, max). Ngay dau tien cua warm-up lay mot nua.
LIKES_PER_DAY = (4, 8)
FOLLOWS_PER_DAY = (1, 3)
COMMENTS_PER_DAY = (0, 2)
# Dang lai (repost) hiem hon: nguoi that thinh thoang moi lam, va chi tu ngay thu 2.
REPOSTS_PER_DAY = (0, 1)

# Bo qua video qua nho (khong phai xu huong) - va khong follow creator qua lon: mot tai
# khoan moi follow toan nguoi 10 trieu follower cung la mot mau hinh.
MIN_VIEWS = 20_000
FEED_COUNT = 24

# Binh luan di SAU tha tim cung video it nhat tung nay - nguoi that xem, tha tim, roi
# moi go. Va khong bao gio binh luan video minh chua tha tim.
COMMENT_AFTER_LIKE = timedelta(minutes=8)
REPOST_AFTER_LIKE = timedelta(minutes=3)

# Thoi gian XEM truoc khi hanh dong (giay). Runner mo trang video / trang ca nhan roi
# cho dung tung nay moi bam. Tha tim sau 30-45 giay xem la nhip nguoi that; tha tim ngay
# giay dau tien sau khi doc feed la nhip cua may.
_DURATION = {
    ActivityKind.ENGAGE: (30, 45),
    ActivityKind.FOLLOW: (10, 20),
    ActivityKind.COMMENT: (20, 40),
    ActivityKind.REPOST: (30, 45),
}


def watch_seconds(job: ActivityJob) -> int:
    """Bao lau thi bam. Job cu (truoc khi co xem) mang 90 giay - cat xuong 60."""
    return max(5, min(int(job.duration_seconds or 30), 60))


class Target(Protocol):
    """Mot video trong feed, du de xep lich. Moi nen tang co FeedItem rieng khop hinh nay."""

    @property
    def item_id(self) -> str: ...
    @property
    def author_handle(self) -> str: ...
    @property
    def views(self) -> int: ...
    @property
    def url(self) -> str: ...


@dataclass(frozen=True, slots=True)
class Budget:
    likes: int
    follows: int
    comments: int
    reposts: int = 0


def budget_for(account: Account, now: datetime, rng: random.Random) -> Budget:
    """Ngan sach hom nay. Ngay 0 cua warm-up: mot nua, khong binh luan, khong dang lai;
    ngay 1 chua dang lai."""
    day = (now - account.warmup_started_at).days if account.warmup_started_at else 0
    likes = rng.randint(*LIKES_PER_DAY)
    follows = rng.randint(*FOLLOWS_PER_DAY)
    comments = rng.randint(*COMMENTS_PER_DAY)
    reposts = rng.randint(*REPOSTS_PER_DAY)
    if day <= 0:
        return Budget(max(1, likes // 2), max(0, follows // 2), 0, 0)
    return Budget(likes, follows, min(comments, likes), min(reposts, likes) if day >= 2 else 0)


def pick_targets(
    items: list, *, own_handles: set[str], rng: random.Random, min_views: int = MIN_VIEWS
) -> list:
    """Loc feed thanh danh sach dich: bo tai khoan cua minh, bo video nho, moi creator
    mot video, xao thu tu. `min_views` la nguong "dang len" - Reddit do bang diem."""
    seen: set[str] = set()
    seen_items: set[str] = set()
    out: list = []
    for it in items:
        if it.item_id in seen_items:
            continue
        seen_items.add(it.item_id)
        if it.author_handle in own_handles or it.author_handle in seen:
            continue
        if it.views < min_views:
            continue
        seen.add(it.author_handle)
        out.append(it)
    rng.shuffle(out)
    return out


def keywords_from(interests: list | None, extra: str | None) -> list[str]:
    """Chu de cua persona + WARM_KEYWORDS (dau phay), bo trung, giu thu tu."""
    out: list[str] = []
    for raw in list(interests or []) + str(extra or "").split(","):
        kw = str(raw).strip()
        if kw and kw.lower() not in {o.lower() for o in out}:
            out.append(kw)
    return out


async def gather_targets(src, rng: random.Random, keywords: list[str]) -> list:
    """Feed cua tai khoan + ket qua tim kiem theo 1-2 tu khoa (neu nguon biet tim).
    Tim hong (endpoint doi, tu khoa la) thi van con feed - khong lam hong ca ngay."""
    items = list(await src.feed(FEED_COUNT))
    if keywords and hasattr(src, "search"):
        for kw in rng.sample(keywords, min(2, len(keywords))):
            try:
                items += list(await src.search(kw, FEED_COUNT // 2))
            except Exception as exc:
                log.warning(
                    "outreach.search_failed", keyword=kw, error=f"{type(exc).__name__}: {exc}"
                )
    return items


async def count_outward_for_day(session: AsyncSession, account_id: uuid.UUID, day: date) -> int:
    start = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
    stmt = (
        select(func.count())
        .select_from(ActivityJob)
        .where(
            ActivityJob.account_id == account_id,
            ActivityJob.target_account_id.is_(None),
            ActivityJob.kind.in_(
                [
                    ActivityKind.ENGAGE,
                    ActivityKind.FOLLOW,
                    ActivityKind.COMMENT,
                    ActivityKind.REPOST,
                ]
            ),
            ActivityJob.scheduled_at >= start,
            ActivityJob.scheduled_at < start + timedelta(days=1),
        )
    )
    return int((await session.execute(stmt)).scalar_one())


def build_jobs(
    account: Account,
    targets: list,
    budget: Budget,
    *,
    day: date,
    window: tuple[datetime, datetime],
    rng: random.Random,
    profile_url: Callable[[str], str],
) -> list[ActivityJob]:
    """Xep ngan sach len danh sach dich thanh job, rai deu trong khung gio.

    Thuan tuy (khong DB, khong mang) de test duoc: cung feed, cung rng thi cung lich.
    """
    if not targets:
        return []
    liked = targets[: budget.likes]
    followed = targets[: budget.follows]  # follow creator cua video da tha tim
    commented = liked[: budget.comments]
    # Dang lai video khac video da binh luan, neu du dich: mot video vua binh luan vua
    # dang lai trong cung buoi la hoi nhieu cho mot nguoi la.
    reposted = (liked[budget.comments :] or liked)[: budget.reposts]

    total = len(liked) + len(followed) + len(commented) + len(reposted)
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
    for it in reposted:
        when = max(slots[i], when_liked[it.item_id] + REPOST_AFTER_LIKE)
        jobs.append(make(ActivityKind.REPOST, it.url, when))
        i += 1
    return jobs


async def plan_for_account(
    session: AsyncSession,
    account: Account,
    profile: Profile,
    *,
    source_factory: Callable[[Profile], object],
    profile_url: Callable[[str], str],
    day: date | None = None,
    now: datetime | None = None,
    rng: random.Random | None = None,
    min_views: int = MIN_VIEWS,
    keywords: list[str] | None = None,
) -> list[ActivityJob]:
    """Lich huong ra ngoai cho mot tai khoan trong mot ngay. Da co thi khong lam lai.
    `profile` co the None voi nen tang di bang API (Reddit). `keywords` = tu khoa tim
    kiem de tron them dich ngoai feed."""
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
    async with source_factory(profile) as src:
        items = await gather_targets(src, rng, keywords or [])
    targets = pick_targets(items, own_handles=own, rng=rng, min_views=min_views)
    if not targets:
        log.warning("outreach.no_targets", handle=account.handle, feed=len(items))
        return []

    window = await activity_mod.window_for(session, account.platform, day)
    jobs = build_jobs(
        account,
        targets,
        budget_for(account, now, rng),
        day=day,
        window=window,
        rng=rng,
        profile_url=profile_url,
    )
    for job in jobs:
        session.add(job)
    await session.commit()
    log.info(
        "outreach.planned",
        platform=account.platform.value,
        handle=account.handle,
        jobs=len(jobs),
        targets=len(targets),
    )
    return jobs


async def plan_platform(
    session: AsyncSession,
    platform: Platform,
    *,
    source_factory: Callable[[Profile], object],
    profile_url: Callable[[str], str],
    day: date | None = None,
) -> int:
    """Moi tai khoan cua nen tang dang nuoi hoac dang hoat dong, co profile san sang."""
    stmt = select(Account.id, Account.handle).where(
        Account.platform == platform,
        Account.role == AccountRole.CHANNEL,
        Account.status.in_([AccountStatus.WARMING, AccountStatus.ACTIVE]),
    )
    # Lay id + handle thanh tuple TRUOC vong lap. Sau mot `rollback()` moi object ORM
    # trong phien deu bi expire, va cham vao `account.handle` de ghi log la mot lan
    # lazy-load - trong phien async do la MissingGreenlet. Da hong that o dung cho do.
    targets = list((await session.execute(stmt)).all())
    total = 0
    for account_id, handle in targets:
        try:
            account = await session.get(Account, account_id)
            profile = await profiles_mod.get_for_account(session, account_id)
            if account is None or not readiness.check(account, profile).ready:
                continue
            # Nguon doc profile.proxy; get_for_account khong nap san. Nap tuong minh.
            if profile is None:
                continue
            if profile.proxy_id is not None and "proxy" not in profile.__dict__:
                profile.proxy = await session.get(Proxy, profile.proxy_id)
            total += len(
                await plan_for_account(
                    session,
                    account,
                    profile,
                    source_factory=source_factory,
                    profile_url=profile_url,
                    day=day,
                    keywords=await keywords_for(session, account),
                )
            )
        except Exception as exc:
            # Mot tai khoan doc feed hong (proxy treo, signer chet) khong duoc chan ca doi.
            await session.rollback()
            log.warning(
                "outreach.plan_failed",
                platform=platform.value,
                handle=handle,
                error=f"{type(exc).__name__}: {exc}",
            )
    return total


async def keywords_for(session: AsyncSession, account: Account) -> list[str]:
    """Tu khoa cua tai khoan: chu de persona + WARM_KEYWORDS."""
    from seeding.config import get_settings
    from seeding.domain.models import Persona

    interests = (
        await session.execute(select(Persona.interests).where(Persona.id == account.persona_id))
    ).scalar_one_or_none()
    return keywords_from(interests, get_settings().warm_keywords)


def is_outward(job: ActivityJob) -> bool:
    return job.target_account_id is None and job.kind in {
        ActivityKind.ENGAGE,
        ActivityKind.FOLLOW,
        ActivityKind.COMMENT,
        ActivityKind.REPOST,
    }


def direct_ok(job: ActivityJob) -> bool:
    """Booster (tuong tac cheo) duoc di khong proxy - lua chon co chu y cua nguoi van hanh."""
    account = job.__dict__.get("account")
    return account is not None and account.role is AccountRole.BOOSTER


def client_kwargs(job: ActivityJob) -> dict:
    return {"allow_direct": True} if direct_ok(job) else {}


async def ensure_proxy_loaded(session: AsyncSession, profile: Profile | None) -> None:
    """profile.proxy co the chua duoc nap trong phien async - nap tuong minh, khong lazy."""
    if profile is None:
        return
    if profile.proxy_id is not None and "proxy" not in profile.__dict__:
        profile.proxy = await session.get(Proxy, profile.proxy_id)
