"""Chay mot ActivityJob nham dich tren Instagram: tha tim, theo doi, binh luan.

Cung hop dong ket qua (InteractResult) voi TikTok de worker khong phai biet nen tang.
"""

from __future__ import annotations

import asyncio
import random
import re
from urllib.parse import urlparse

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from seeding.browser.checkpoints import Checkpoint, CheckpointKind
from seeding.config import get_settings
from seeding.content.comments import warm_comment
from seeding.domain.models import Account, ActivityJob, ActivityKind, Platform, Profile
from seeding.platforms.base import InteractResult, register_interact
from seeding.platforms.instagram.client import (
    ActionResult,
    InstagramClient,
    classify_exc,
    pk_from_code,
)
from seeding.platforms.outreach import client_kwargs, direct_ok, ensure_proxy_loaded, watch_seconds

log = structlog.get_logger(__name__)

_MEDIA = re.compile(r"^/(?:reel|reels|p|tv)/([A-Za-z0-9_-]+)/?$")
_PROFILE = re.compile(r"^/([A-Za-z0-9_.]+)/?$")
_NOT_PROFILES = {"explore", "reels", "accounts", "p", "tv", "stories", "direct"}


def parse_target(url: str | None) -> tuple[str | None, str | None]:
    """(handle, media code). code None neu la trang ca nhan."""
    if not url:
        return None, None
    path = urlparse(url).path
    if m := _MEDIA.match(path):
        return None, m.group(1)
    if (m := _PROFILE.match(path)) and m.group(1) not in _NOT_PROFILES:
        return m.group(1), None
    return None, None


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
    return InteractResult(False, res.detail, retryable=res.retryable)


async def run(
    session: AsyncSession,
    profile: Profile,
    job: ActivityJob,
    *,
    client_factory=InstagramClient,
    rng: random.Random | None = None,
    sleep=asyncio.sleep,
) -> InteractResult:
    await ensure_proxy_loaded(session, profile)
    if profile.proxy is None and not direct_ok(job):
        return InteractResult(
            False, "profile has no proxy - refusing to touch Instagram from the host IP"
        )

    handle, code = parse_target(job.target_url)
    if job.kind is ActivityKind.FOLLOW and job.target_account_id is not None:
        target = await session.get(Account, job.target_account_id)
        handle = target.handle if target else handle

    if job.kind in (ActivityKind.ENGAGE, ActivityKind.COMMENT) and not code:
        return InteractResult(False, f"{job.kind.value} job has no media url")
    if job.kind is ActivityKind.FOLLOW and not handle:
        return InteractResult(False, "follow job has no target handle")
    if job.kind is ActivityKind.REPOST:
        return InteractResult(False, "repost on instagram is not implemented")

    try:
        async with client_factory(profile, **client_kwargs(job)) as ig:
            if job.kind is ActivityKind.FOLLOW:
                user_id = await ig.user_id(handle)
                if not user_id:
                    return InteractResult(
                        False, f"could not resolve @{handle} to a user id", retryable=True
                    )
                await sleep(watch_seconds(job))
                res = await ig.follow(user_id)
            else:
                pk = pk_from_code(code)
                await ig.watch(pk)
                await sleep(watch_seconds(job))
                if job.kind is ActivityKind.ENGAGE:
                    res = await ig.like(pk)
                else:
                    res = await ig.comment(pk, warm_comment(job.id, "instagram", rng))
    except Exception as exc:
        # Dang nhap bang sessionid hong, proxy treo, feed hong... Dang nhap hong la
        # phien chet -> nguoi; con lai la ha tang -> thu lai.
        r = _to_result(classify_exc(exc, idempotent=True))
        log.warning("instagram_interact.failed", job=str(job.id), error=r.detail)
        return r

    result = _to_result(res)
    log.info(
        "instagram_interact.done",
        job=str(job.id),
        kind=job.kind.value,
        target=job.target_url,
        ok=result.ok,
        detail=result.detail,
    )
    return result


if get_settings().instagram_enabled:
    register_interact(Platform.INSTAGRAM, run)
