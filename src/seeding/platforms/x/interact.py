"""Chay mot ActivityJob nham dich tren X: tha tim, theo doi, tra loi.

X chan bai trung chu (code 187) trong mot khoang thoi gian. Bo binh luan chung chi co
hai muoi cau, nen tra loi tren X duoc ghep them mot duoi nho (emoji, dau cham) chon
theo job id de hai lan tra loi gan nhau khong trung nguyen van.
"""

from __future__ import annotations

import random
import re
from urllib.parse import urlparse

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from seeding.browser.checkpoints import Checkpoint, CheckpointKind
from seeding.config import get_settings
from seeding.content.comments import comment_text
from seeding.domain.models import Account, ActivityJob, ActivityKind, Platform, Profile
from seeding.platforms.base import InteractResult, register_interact
from seeding.platforms.outreach import ensure_proxy_loaded
from seeding.platforms.x.client import ActionResult, XClient, classify_exc

log = structlog.get_logger(__name__)

_STATUS = re.compile(r"^/([A-Za-z0-9_]{1,15})/status/(\d+)")
_PROFILE = re.compile(r"^/([A-Za-z0-9_]{1,15})/?$")
_NOT_PROFILES = {"home", "explore", "i", "search", "settings", "messages", "notifications"}

SUFFIXES = ["", "", "", " 🔥", " 👏", " 😂", "!!", "…", " 💯", " nè"]


def parse_target(url: str | None) -> tuple[str | None, str | None]:
    """(handle, tweet_id). tweet_id None neu la trang ca nhan."""
    if not url:
        return None, None
    path = urlparse(url).path
    if m := _STATUS.match(path):
        return m.group(1), m.group(2)
    if (m := _PROFILE.match(path)) and m.group(1).lower() not in _NOT_PROFILES:
        return m.group(1), None
    return None, None


def reply_text(job_id, rng: random.Random | None = None) -> str:
    rng = rng or random.Random(f"reply:{job_id}")
    return comment_text(job_id, rng) + rng.choice(SUFFIXES)


def _to_result(res: ActionResult) -> InteractResult:
    if res.ok:
        return InteractResult(True, res.detail)
    if res.terminal:
        return InteractResult(
            False, res.detail, checkpoint=Checkpoint(CheckpointKind.SUSPENDED, res.detail)
        )
    if res.needs_human:
        return InteractResult(
            False, res.detail, checkpoint=Checkpoint(CheckpointKind.VERIFY, res.detail)
        )
    # Thu vien lech: thu lai sau, khong phai loi tai khoan.
    return InteractResult(False, res.detail, retryable=res.retryable or res.library)


async def run(
    session: AsyncSession,
    profile: Profile,
    job: ActivityJob,
    *,
    client_factory=XClient,
    rng: random.Random | None = None,
) -> InteractResult:
    await ensure_proxy_loaded(session, profile)
    if profile.proxy is None:
        return InteractResult(False, "profile has no proxy - refusing to touch X from the host IP")

    handle, tweet_id = parse_target(job.target_url)
    if job.kind is ActivityKind.FOLLOW and job.target_account_id is not None:
        target = await session.get(Account, job.target_account_id)
        handle = target.handle.lstrip("@") if target else handle

    if job.kind in (ActivityKind.ENGAGE, ActivityKind.COMMENT) and not tweet_id:
        return InteractResult(False, f"{job.kind.value} job has no tweet url")
    if job.kind is ActivityKind.FOLLOW and not handle:
        return InteractResult(False, "follow job has no target handle")
    if job.kind is ActivityKind.REPOST:
        return InteractResult(False, "repost on x is not implemented")

    try:
        async with client_factory(profile) as x:
            if job.kind is ActivityKind.ENGAGE:
                res = await x.like(tweet_id)
            elif job.kind is ActivityKind.COMMENT:
                res = await x.comment(tweet_id, reply_text(job.id, rng))
            else:
                user_id = await x.user_id(handle)
                if not user_id:
                    return InteractResult(
                        False, f"could not resolve @{handle} to a user id", retryable=True
                    )
                res = await x.follow(user_id)
    except Exception as exc:
        r = _to_result(classify_exc(exc, idempotent=True))
        log.warning("x_interact.failed", job=str(job.id), error=r.detail)
        return r

    result = _to_result(res)
    log.info(
        "x_interact.done",
        job=str(job.id),
        kind=job.kind.value,
        target=job.target_url,
        ok=result.ok,
        detail=result.detail,
    )
    return result


if get_settings().x_enabled:
    register_interact(Platform.X, run)
