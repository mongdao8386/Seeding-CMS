"""Phien luot xem TikTok: mo For You (hoac trang tim kiem), cuon qua vai video, xem moi
video 20-45 giay, thinh thoang tha tim / follow / binh luan sticker / dang lai.

Truoc day moi hanh dong la mot job mo THANG link video roi bam: toi 8 phut trinh duyet
cho mot cu tha tim, va khong nguoi that nao mo sau link video roi rac tu hu khong trong
mot ngay. Mot phien luot la cach nguoi that dung TikTok: vao, xem mot loat, tim vai
cai, thoat. Voi tai khoan moi, thoi gian XEM moi la thu thuat toan de y toi, nen ngay
dau chi xem khong bam (WARM_WATCH_ONLY_DAYS).

Ke hoach nam trong target_url dang "sitting:{json}", nhu doi danh tinh / quan ly bai.
Moi hanh dong lam duoc trong phien duoc ghi thanh mot ActivityJob con (ENGAGE/FOLLOW/
COMMENT/REPOST) da xong voi link video that - dong thoi gian va ngan sach ngay van dung.
Runner o interact_browser.py (chung recipe voi cac job mo thang link).
"""

from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from urllib.parse import quote

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
    Platform,
)
from seeding.platforms import outreach
from seeding.scheduling import windows as activity_mod

log = structlog.get_logger(__name__)

PREFIX = "sitting:"
SITTINGS_PER_DAY = (2, 3)
VIDEOS_PER_SITTING = (4, 8)
WATCH_RANGE = (20, 45)
# Toi da mot phien tinh tu luc trang hien. Qua no thi dung, du chua het video: worker
# giu job 25 phut, va nguoi that cung khong luot mai.
SITTING_MAX_S = 12 * 60


@dataclass(frozen=True, slots=True)
class Plan:
    source: str = "foryou"  # "foryou" | "search"
    keyword: str | None = None
    videos: int = 5
    likes: int = 0
    follows: int = 0
    comments: int = 0
    reposts: int = 0

    @property
    def watch_only(self) -> bool:
        return not (self.likes or self.follows or self.comments or self.reposts)

    def dumps(self) -> str:
        return PREFIX + json.dumps(asdict(self), ensure_ascii=False)

    def url(self, origin: str) -> str:
        if self.source == "search" and self.keyword:
            return f"{origin}/search?q={quote(self.keyword)}"
        return f"{origin}/foryou"


def decode(target_url: str | None) -> Plan | None:
    if not target_url or not target_url.startswith(PREFIX):
        return None
    try:
        data = json.loads(target_url[len(PREFIX) :])
        return Plan(**{k: data[k] for k in Plan.__dataclass_fields__ if k in data})
    except (ValueError, TypeError):
        return None


def describe(plan: Plan | None) -> str:
    if plan is None:
        return "Lướt xem"
    where = f"tìm “{plan.keyword}”" if plan.source == "search" and plan.keyword else "For You"
    acts = []
    if plan.likes:
        acts.append(f"{plan.likes} tim")
    if plan.follows:
        acts.append(f"{plan.follows} follow")
    if plan.comments:
        acts.append(f"{plan.comments} bình luận")
    if plan.reposts:
        acts.append(f"{plan.reposts} đăng lại")
    return f"Lướt {where}: {plan.videos} video, {', '.join(acts) if acts else 'chỉ xem'}"


def _split(total: int, parts: int, rng: random.Random) -> list[int]:
    """Chia `total` thanh `parts` phan nguyen khong am, ngau nhien nhung du tong."""
    out = [0] * parts
    for _ in range(max(0, total)):
        out[rng.randrange(parts)] += 1
    return out


def watch_only_today(account: Account, now: datetime) -> bool:
    """Nhung ngay dau cua warm-up chi xem, khong bam gi."""
    day = (now - account.warmup_started_at).days if account.warmup_started_at else 0
    return day < get_settings().warm_watch_only_days


def build_sittings(
    account: Account,
    budget: outreach.Budget,
    keywords: list[str],
    *,
    day: date,
    window: tuple[datetime, datetime],
    rng: random.Random,
    watch_only: bool = False,
) -> list[ActivityJob]:
    """Rai ngan sach mot ngay len 2-3 phien luot trong khung gio. Thuan tuy de test.

    Follow / binh luan / dang lai chi xay ra tren video vua tha tim trong cung phien,
    nen moi phien khong the co nhieu hon so tim cua no.
    """
    n = rng.randint(*SITTINGS_PER_DAY)
    start, end = window
    slots = sorted(activity_mod._slots(day, n, rng, start, end))
    if watch_only:
        budget = outreach.Budget(0, 0, 0, 0)
    likes = _split(budget.likes, n, rng)
    follows = _split(budget.follows, n, rng)
    comments = _split(budget.comments, n, rng)
    reposts = _split(budget.reposts, n, rng)
    # Mot phien trong ngay di tim theo tu khoa (neu co); con lai la For You.
    search_at = rng.randrange(n) if keywords else -1
    jobs: list[ActivityJob] = []
    for i, when in enumerate(slots):
        # Khong tha tim video dau tien, nen so video phai nhieu hon so tim it nhat mot.
        videos = max(rng.randint(*VIDEOS_PER_SITTING), likes[i] + 1)
        plan = Plan(
            source="search" if i == search_at else "foryou",
            keyword=rng.choice(keywords) if i == search_at else None,
            videos=videos,
            likes=likes[i],
            follows=min(follows[i], likes[i]),
            comments=min(comments[i], likes[i]),
            reposts=min(reposts[i], likes[i]),
        )
        jobs.append(
            ActivityJob(
                account_id=account.id,
                kind=ActivityKind.BROWSE_FEED,
                scheduled_at=when,
                duration_seconds=videos * sum(WATCH_RANGE) // 2,
                target_url=plan.dumps(),
            )
        )
    return jobs


async def count_for_day(session: AsyncSession, account_id, day: date) -> int:
    start = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
    stmt = (
        select(func.count())
        .select_from(ActivityJob)
        .where(
            ActivityJob.account_id == account_id,
            ActivityJob.kind == ActivityKind.BROWSE_FEED,
            ActivityJob.scheduled_at >= start,
            ActivityJob.scheduled_at < start + timedelta(days=1),
        )
    )
    return int((await session.execute(stmt)).scalar_one())


async def plan_for_account(
    session: AsyncSession,
    account: Account,
    *,
    day: date | None = None,
    now: datetime | None = None,
    rng: random.Random | None = None,
    keywords: list[str] | None = None,
) -> list[ActivityJob]:
    """Cac phien luot cua mot tai khoan trong mot ngay. Ngay da co phien, hoac da co job
    huong ra ngoai (lich cu theo tung link), thi khong them."""
    now = now or datetime.now(UTC)
    day = day or now.date()
    rng = rng or random.Random(f"sitting:{account.id}:{day.isoformat()}")
    if await count_for_day(session, account.id, day):
        return []
    if await outreach.count_outward_for_day(session, account.id, day):
        return []
    window = await activity_mod.window_for(session, account.platform, day)
    watch_only = watch_only_today(account, now)
    jobs = build_sittings(
        account,
        outreach.budget_for(account, now, rng),
        keywords or [],
        day=day,
        window=window,
        rng=rng,
        watch_only=watch_only,
    )
    for job in jobs:
        session.add(job)
    await session.commit()
    log.info("sitting.planned", handle=account.handle, sittings=len(jobs), watch_only=watch_only)
    return jobs


async def plan_all(session: AsyncSession, *, day: date | None = None) -> int:
    """Moi tai khoan xay kenh TikTok dang nuoi / hoat dong, profile san sang. Khong doc
    feed qua HTTP: dich duoc tim ngay trong trinh duyet luc luot."""
    stmt = select(Account.id, Account.handle).where(
        Account.platform == Platform.TIKTOK,
        Account.role == AccountRole.CHANNEL,
        Account.status.in_([AccountStatus.WARMING, AccountStatus.ACTIVE]),
    )
    total = 0
    for account_id, handle in list((await session.execute(stmt)).all()):
        try:
            account = await session.get(Account, account_id)
            profile = await profiles_mod.get_for_account(session, account_id)
            if account is None or profile is None:
                continue
            if not readiness.check(account, profile).ready:
                continue
            total += len(
                await plan_for_account(
                    session,
                    account,
                    day=day,
                    keywords=await outreach.keywords_for(session, account),
                )
            )
        except Exception as exc:
            await session.rollback()
            log.warning("sitting.plan_failed", handle=handle, error=f"{type(exc).__name__}: {exc}")
    return total
