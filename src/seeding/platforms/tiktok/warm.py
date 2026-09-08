"""Nuoi TikTok huong ra ngoai: For You cua chinh tai khoan, qua proxy cua no.

Phan chung (ngan sach, loc dich, rai gio) o platforms/outreach.py. O day chi con hai
thu TikTok: nguon feed (TikTokWeb) va dang URL trang ca nhan.
"""

from __future__ import annotations

import random
from datetime import date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from seeding.config import get_settings
from seeding.domain.models import Account, ActivityJob, Platform, Profile
from seeding.platforms import outreach
from seeding.platforms.base import register_warm
from seeding.platforms.outreach import (
    COMMENT_AFTER_LIKE,
    COMMENTS_PER_DAY,
    FEED_COUNT,
    FOLLOWS_PER_DAY,
    LIKES_PER_DAY,
    MIN_VIEWS,
    Budget,
    budget_for,
    count_outward_for_day,
    is_outward,
    pick_targets,
)
from seeding.platforms.tiktok.web import ORIGIN, TikTokWeb


def profile_url(handle: str) -> str:
    return f"{ORIGIN}/@{handle}"


def build_jobs(
    account: Account,
    targets: list,
    budget: Budget,
    *,
    day: date,
    window: tuple[datetime, datetime],
    rng: random.Random,
) -> list[ActivityJob]:
    return outreach.build_jobs(
        account, targets, budget, day=day, window=window, rng=rng, profile_url=profile_url
    )


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
    return await outreach.plan_for_account(
        session,
        account,
        profile,
        source_factory=web_factory,
        profile_url=profile_url,
        day=day,
        now=now,
        rng=rng,
    )


async def plan_all(session: AsyncSession, *, day: date | None = None) -> int:
    return await outreach.plan_platform(
        session, Platform.TIKTOK, source_factory=TikTokWeb, profile_url=profile_url, day=day
    )


if get_settings().tiktok_interact_via_http:
    register_warm(Platform.TIKTOK, plan_all)


__all__ = [
    "COMMENTS_PER_DAY",
    "COMMENT_AFTER_LIKE",
    "FEED_COUNT",
    "FOLLOWS_PER_DAY",
    "LIKES_PER_DAY",
    "MIN_VIEWS",
    "Budget",
    "budget_for",
    "build_jobs",
    "count_outward_for_day",
    "is_outward",
    "pick_targets",
    "plan_all",
    "plan_for_account",
    "profile_url",
]
