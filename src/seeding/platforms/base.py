"""Giao dien chung cho moi nen tang, va so dang ky.

Worker khong biet TikTok hay Instagram khac nhau the nao. No hoi so dang ky: nen tang
nay dang bai bang gi, nuoi bang gi, kiem phien bang gi. Moi nen tang tu dang ky khi
duoc import (load_all), va chi dang ky khi cong tac trong .env dang bat.
"""

from __future__ import annotations

import importlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from seeding.browser.checkpoints import Checkpoint
from seeding.domain.models import Account, Platform, Profile, Proxy, Variant


@dataclass(slots=True)
class PublishResult:
    ok: bool
    remote_id: str | None = None
    remote_url: str | None = None
    error: str | None = None
    # True khi gap checkpoint / captcha / xac minh -> day sang hang doi can thiep tay
    # thay vi retry.
    needs_human: bool = False
    # True khi loi mang tam thoi hoac bi rate limit -> retry co ich.
    retryable: bool = False
    metrics: dict = field(default_factory=dict)


class LibraryBroken(RuntimeError):
    """Thu vien cua mot nen tang lech voi nen tang do (X xoay query id, handshake doi
    dang). Khong phai loi cua tai khoan: khong ghi len profile, bao he thong mot lan."""


@dataclass(slots=True)
class InteractResult:
    """Ket qua mot hanh dong nuoi (tha tim / follow / binh luan).

    `checkpoint` khac None = can nguoi; `checkpoint.is_terminal` = tai khoan xong roi.
    """

    ok: bool
    detail: str
    checkpoint: Checkpoint | None = None
    retryable: bool = False


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
        """Adapter API bo qua `profile`; adapter trinh duyet / cookie thi bat buoc phai co."""
        ...


# (session, profile, job) -> InteractResult
InteractRunner = Callable[..., Awaitable[InteractResult]]
# (session, *, day=None) -> so job da lap
WarmPlanner = Callable[..., Awaitable[int]]
# (profile) -> (con song, mo ta)
HealthCheck = Callable[[Profile], Awaitable[tuple[bool, str]]]

_REGISTRY: dict[Platform, Adapter] = {}
_IDENTITY: dict[Platform, InteractRunner] = {}
_MANAGE: dict[Platform, InteractRunner] = {}
# (profile, account) -> Channel (mo bang `async with`)
_CHATBOT: dict[Platform, Callable[..., object]] = {}
_INTERACT: dict[Platform, InteractRunner] = {}
_WARM: dict[Platform, WarmPlanner] = {}
_HEALTH: dict[Platform, HealthCheck] = {}


def register(adapter: Adapter) -> None:
    _REGISTRY[adapter.platform] = adapter


def get(platform: Platform) -> Adapter:
    if platform not in _REGISTRY:
        raise NotImplementedError(f"Chua co adapter cho {platform.value}")
    return _REGISTRY[platform]


def register_interact(platform: Platform, runner: InteractRunner) -> None:
    _INTERACT[platform] = runner


def get_interact(platform: Platform) -> InteractRunner | None:
    return _INTERACT.get(platform)


def register_identity(platform: Platform, runner: InteractRunner) -> None:
    """Doi ten / username / anh dai dien. Cung hop dong voi runner nuoi."""
    _IDENTITY[platform] = runner


def get_identity(platform: Platform) -> InteractRunner | None:
    return _IDENTITY.get(platform)


def register_manage(platform: Platform, runner: InteractRunner) -> None:
    """Xoa bai da dang / sua chu thich. Cung hop dong voi runner nuoi."""
    _MANAGE[platform] = runner


def get_manage(platform: Platform) -> InteractRunner | None:
    return _MANAGE.get(platform)


def register_chatbot(platform: Platform, factory: Callable[..., object]) -> None:
    """Kenh chatbot: doc binh luan / hop thu cua chinh tai khoan va tra loi."""
    _CHATBOT[platform] = factory


def get_chatbot(platform: Platform) -> Callable[..., object] | None:
    return _CHATBOT.get(platform)


def chatbots() -> dict[Platform, Callable[..., object]]:
    return dict(_CHATBOT)


def register_warm(platform: Platform, planner: WarmPlanner) -> None:
    _WARM[platform] = planner


def warm_planners() -> dict[Platform, WarmPlanner]:
    return dict(_WARM)


def register_health(platform: Platform, check: HealthCheck) -> None:
    _HEALTH[platform] = check


def get_health(platform: Platform) -> HealthCheck | None:
    return _HEALTH.get(platform)


# Cac module tu dang ky khi duoc import. Thu tu khong quan trong.
_MODULES = (
    "seeding.platforms.tiktok.publish",
    "seeding.platforms.tiktok.interact",
    "seeding.platforms.tiktok.warm",
    "seeding.platforms.tiktok.manage",
    "seeding.platforms.instagram.publish",
    "seeding.platforms.instagram.interact",
    "seeding.platforms.instagram.warm",
    "seeding.platforms.instagram.identity",
    "seeding.platforms.instagram.manage",
    "seeding.platforms.x.publish",
    "seeding.platforms.x.interact",
    "seeding.platforms.x.warm",
    "seeding.platforms.x.identity",
    "seeding.platforms.x.manage",
    "seeding.platforms.reddit.publish",
    "seeding.platforms.reddit.interact",
    "seeding.platforms.reddit.warm",
    "seeding.platforms.reddit.manage",
    "seeding.platforms.facebook.publish",
    "seeding.platforms.facebook.interact",
    "seeding.platforms.tiktok.chatbot",
    "seeding.platforms.instagram.chatbot",
    "seeding.platforms.x.chatbot",
    "seeding.platforms.reddit.chatbot",
)


def load_all() -> None:
    """Import moi nen tang de chung dang ky. Goi mot lan khi worker khoi dong."""
    for name in _MODULES:
        importlib.import_module(name)


def proxy_dsn(proxy: Proxy) -> str:
    """scheme://user:pass@host:port - dang ma httpx va aiograpi cung hieu."""
    auth = f"{proxy.username}:{proxy.get_password() or ''}@" if proxy.username else ""
    return f"{(proxy.scheme or 'http').lower()}://{auth}{proxy.host}:{proxy.port}"
