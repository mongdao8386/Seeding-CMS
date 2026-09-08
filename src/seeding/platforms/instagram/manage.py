"""Xoa / sua chu thich bai Instagram da dang, qua aiograpi."""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from seeding.browser.checkpoints import Checkpoint, CheckpointKind
from seeding.config import get_settings
from seeding.domain.models import ActivityJob, Platform, Profile
from seeding.platforms import manage
from seeding.platforms.base import InteractResult, register_manage
from seeding.platforms.instagram.client import InstagramClient, classify_exc
from seeding.platforms.outreach import ensure_proxy_loaded

log = structlog.get_logger(__name__)


async def run(
    session: AsyncSession,
    profile: Profile,
    job: ActivityJob,
    *,
    client_factory=InstagramClient,
) -> InteractResult:
    plan = manage.decode(job.target_url)
    if plan is None or not plan.remote_id:
        return InteractResult(False, "manage job has no plan or no media id")
    await ensure_proxy_loaded(session, profile)
    if profile.proxy is None:
        return InteractResult(False, "profile has no proxy - refusing to touch Instagram")

    try:
        async with client_factory(profile) as ig:
            assert ig.client is not None
            if plan.action == "delete":
                ok = await ig.client.media_delete(plan.remote_id)
                if not ok:
                    return InteractResult(False, "Instagram answered but did not delete")
            else:
                await ig.client.media_edit(plan.remote_id, plan.caption or "")
    except Exception as exc:
        r = classify_exc(exc, idempotent=plan.action == "delete")
        cp = (
            Checkpoint(CheckpointKind.SUSPENDED, r.detail)
            if r.terminal
            else Checkpoint(CheckpointKind.VERIFY, r.detail)
            if r.needs_human
            else None
        )
        log.warning("instagram_manage.failed", job=str(job.id), error=r.detail)
        return InteractResult(False, r.detail, checkpoint=cp, retryable=r.retryable)

    await manage.mark_done(session, job, plan)
    return InteractResult(True, "đã xoá" if plan.action == "delete" else "đã sửa chú thích")


if get_settings().instagram_enabled:
    register_manage(Platform.INSTAGRAM, run)
