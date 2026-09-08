"""Xoa / sua bai Reddit da dang, qua PRAW."""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from seeding.browser.checkpoints import Checkpoint, CheckpointKind
from seeding.config import get_settings
from seeding.domain.models import ActivityJob, Platform, Profile
from seeding.platforms import manage
from seeding.platforms.base import InteractResult, register_manage
from seeding.platforms.reddit.client import RedditClient, classify_exc

log = structlog.get_logger(__name__)


async def run(
    session: AsyncSession,
    profile: Profile | None,
    job: ActivityJob,
    *,
    client_factory=RedditClient,
) -> InteractResult:
    plan = manage.decode(job.target_url)
    if plan is None or not plan.remote_id:
        return InteractResult(False, "manage job has no plan or no submission id")
    try:
        async with client_factory(job.account, profile) as rd:
            if plan.action == "delete":
                await rd.delete(plan.remote_id)
            else:
                await rd.edit(plan.remote_id, plan.caption or "")
    except Exception as exc:
        r = classify_exc(exc, idempotent=plan.action == "delete")
        cp = (
            Checkpoint(CheckpointKind.SUSPENDED, r.detail)
            if r.terminal
            else Checkpoint(CheckpointKind.VERIFY, r.detail)
            if r.needs_human
            else None
        )
        log.warning("reddit_manage.failed", job=str(job.id), error=r.detail)
        return InteractResult(False, r.detail, checkpoint=cp, retryable=r.retryable)

    await manage.mark_done(session, job, plan)
    return InteractResult(True, "đã xoá" if plan.action == "delete" else "đã sửa")


if get_settings().reddit_enabled:
    register_manage(Platform.REDDIT, run)
