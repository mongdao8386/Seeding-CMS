"""Chay mot ActivityJob nham dich tren Reddit: upvote, "friend" (follow), binh luan."""

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
from seeding.platforms.reddit.client import ActionResult, RedditClient, classify_exc

log = structlog.get_logger(__name__)

_POST = re.compile(r"/comments/([a-z0-9]+)")
_USER = re.compile(r"^/(?:u|user)/([A-Za-z0-9_-]+)/?$")


def parse_target(url: str | None) -> tuple[str | None, str | None]:
    """(handle, submission_id)."""
    if not url:
        return None, None
    path = urlparse(url).path
    if m := _POST.search(path):
        return None, m.group(1)
    if m := _USER.match(path):
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
    profile: Profile | None,
    job: ActivityJob,
    *,
    client_factory=RedditClient,
    rng: random.Random | None = None,
) -> InteractResult:
    handle, sid = parse_target(job.target_url)
    if job.kind is ActivityKind.FOLLOW and job.target_account_id is not None:
        target = await session.get(Account, job.target_account_id)
        handle = target.handle.lstrip("@") if target else handle
    if job.kind in (ActivityKind.ENGAGE, ActivityKind.COMMENT) and not sid:
        return InteractResult(False, f"{job.kind.value} job has no post url")
    if job.kind is ActivityKind.FOLLOW and not handle:
        return InteractResult(False, "follow job has no target handle")
    if job.kind is ActivityKind.REPOST:
        return InteractResult(False, "crosspost is not implemented")

    try:
        async with client_factory(job.account, profile) as rd:
            if job.kind is ActivityKind.ENGAGE:
                res = await rd.like(sid)
            elif job.kind is ActivityKind.COMMENT:
                res = await rd.comment(sid, comment_text(job.id, rng))
            else:
                res = await rd.follow(handle)
    except Exception as exc:
        r = _to_result(classify_exc(exc, idempotent=True))
        log.warning("reddit_interact.failed", job=str(job.id), error=r.detail)
        return r

    result = _to_result(res)
    log.info(
        "reddit_interact.done",
        job=str(job.id),
        kind=job.kind.value,
        target=job.target_url,
        ok=result.ok,
        detail=result.detail,
    )
    return result


if get_settings().reddit_enabled:
    register_interact(Platform.REDDIT, run)
