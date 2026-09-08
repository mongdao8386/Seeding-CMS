"""Nuoi Instagram huong ra ngoai: Reels de xuat cua chinh tai khoan, qua proxy cua no.

Phan chung o platforms/outreach.py. O day chi con nguon feed va dang URL trang ca nhan.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from seeding.config import get_settings
from seeding.domain.models import Platform
from seeding.platforms import outreach
from seeding.platforms.base import register_health, register_warm
from seeding.platforms.instagram.client import ORIGIN, InstagramClient, check


def profile_url(handle: str) -> str:
    return f"{ORIGIN}/{handle}/"


async def plan_all(session: AsyncSession, *, day: date | None = None) -> int:
    return await outreach.plan_platform(
        session,
        Platform.INSTAGRAM,
        source_factory=InstagramClient,
        profile_url=profile_url,
        day=day,
    )


if get_settings().instagram_enabled:
    register_warm(Platform.INSTAGRAM, plan_all)
    register_health(Platform.INSTAGRAM, check)
