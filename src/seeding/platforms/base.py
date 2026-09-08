"""Giao dien chung cho moi nen tang.

Giai doan 01 chi co RedditAdapter (goi API that). Giai doan 03 se them
BrowserAdapter dung Camoufox - no cai dat dung giao dien nay, nen planner,
scheduler va rate governor khong phai biet su khac nhau.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from seeding.domain.models import Account, Platform, Profile, Variant


@dataclass(slots=True)
class PublishResult:
    ok: bool
    remote_id: str | None = None
    remote_url: str | None = None
    error: str | None = None
    # True khi gap checkpoint / captcha / xac minh -> day sang hang doi can thiep tay
    # thay vi retry. Giai doan 03 moi dung toi, khai bao san de khong phai doi giao dien.
    needs_human: bool = False
    # True khi loi mang tam thoi hoac bi rate limit -> retry co ich.
    retryable: bool = False
    metrics: dict = field(default_factory=dict)


@runtime_checkable
class Adapter(Protocol):
    platform: Platform

    async def publish(
        self,
        account: Account,
        variant: Variant,
        target: dict,
        *,
        profile: Profile | None = None,
    ) -> PublishResult:
        """Adapter API bo qua `profile`; adapter trinh duyet thi bat buoc phai co."""
        ...


_REGISTRY: dict[Platform, Adapter] = {}


def register(adapter: Adapter) -> None:
    _REGISTRY[adapter.platform] = adapter


def get(platform: Platform) -> Adapter:
    if platform not in _REGISTRY:
        raise NotImplementedError(f"Chua co adapter cho {platform.value}")
    return _REGISTRY[platform]
