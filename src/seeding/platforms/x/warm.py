"""Nuoi X huong ra ngoai: For You cua chinh tai khoan, qua proxy cua no.

Phan chung o platforms/outreach.py. O day chi con nguon feed va dang URL trang ca nhan.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from seeding.config import get_settings
from seeding.domain.models import Platform
from seeding.platforms import outreach
from seeding.platforms.base import register_health, register_warm
from seeding.platforms.x.client import ORIGIN, XClient, check


def profile_url(handle: str) -> str:
    return f"{ORIGIN}/{handle.lstrip('@')}"


async def plan_all(session: AsyncSession, *, day: date | None = None) -> int:
    return await outreach.plan_platform(
        session, Platform.X, source_factory=XClient, profile_url=profile_url, day=day
    )


if get_settings().x_enabled:
    register_warm(Platform.X, plan_all)
    register_health(Platform.X, check)
