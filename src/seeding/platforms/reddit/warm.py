"""Nuoi Reddit huong ra ngoai: front page (hot) cua chinh tai khoan.

Khac ba nen tang kia o hai cho: khong can profile (API), va "xu huong" do bang diem
chu khong phai luot xem - nen nguong dich la MIN_SCORE, khong phai MIN_VIEWS.
"""

from __future__ import annotations

from datetime import date

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from seeding.config import get_settings
from seeding.domain import profiles as profiles_mod
from seeding.domain import readiness
from seeding.domain.models import Account, AccountStatus, Platform
from seeding.platforms import outreach
from seeding.platforms.base import register_warm
from seeding.platforms.reddit.client import MIN_SCORE, ORIGIN, RedditClient

log = structlog.get_logger(__name__)


def profile_url(handle: str) -> str:
    return f"{ORIGIN}/user/{handle.lstrip('@')}"


async def plan_all(session: AsyncSession, *, day: date | None = None) -> int:
    stmt = select(Account.id, Account.handle).where(
        Account.platform == Platform.REDDIT,
        Account.status.in_([AccountStatus.WARMING, AccountStatus.ACTIVE]),
    )
    targets = list((await session.execute(stmt)).all())
    total = 0
    for account_id, handle in targets:
        try:
            account = await session.get(Account, account_id)
            profile = await profiles_mod.get_for_account(session, account_id)
            if account is None or not readiness.check(account, profile).ready:
                continue
            if profile is not None:
                await outreach.ensure_proxy_loaded(session, profile)

            def factory(_profile, _account=account):
                return RedditClient(_account, _profile)

            total += len(
                await outreach.plan_for_account(
                    session,
                    account,
                    profile,
                    source_factory=factory,
                    profile_url=profile_url,
                    day=day,
                    min_views=MIN_SCORE,
                    keywords=await outreach.keywords_for(session, account),
                )
            )
        except Exception as exc:
            await session.rollback()
            log.warning(
                "outreach.plan_failed",
                platform="reddit",
                handle=handle,
                error=f"{type(exc).__name__}: {exc}",
            )
    return total


if get_settings().reddit_enabled:
    register_warm(Platform.REDDIT, plan_all)
