"""Xoa bai X da dang, qua twifork. Sua thi X chi cho tai khoan tra phi - khong lam."""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from seeding.browser.checkpoints import Checkpoint, CheckpointKind
from seeding.config import get_settings
from seeding.domain.models import ActivityJob, Platform, Profile
from seeding.platforms import manage
from seeding.platforms.base import InteractResult, register_manage
from seeding.platforms.outreach import ensure_proxy_loaded
from seeding.platforms.x.client import XClient, classify_exc

log = structlog.get_logger(__name__)


async def run(
    session: AsyncSession,
    profile: Profile,
    job: ActivityJob,
    *,
    client_factory=XClient,
) -> InteractResult:
    plan = manage.decode(job.target_url)
    if plan is None or not plan.remote_id:
        return InteractResult(False, "manage job has no plan or no tweet id")
    if plan.action != "delete":
        return InteractResult(False, "X chỉ cho sửa bài với tài khoản trả phí")
    await ensure_proxy_loaded(session, profile)
    if profile.proxy is None:
        return InteractResult(False, "profile has no proxy - refusing to touch X")

    try:
        async with client_factory(profile) as x:
            assert x.client is not None
            await x.client.delete_tweet(plan.remote_id)
    except Exception as exc:
        r = classify_exc(exc, idempotent=True)
        cp = (
            Checkpoint(CheckpointKind.SUSPENDED, r.detail)
            if r.terminal
            else Checkpoint(CheckpointKind.VERIFY, r.detail)
            if r.needs_human
            else None
        )
        log.warning("x_manage.failed", job=str(job.id), error=r.detail)
        return InteractResult(False, r.detail, checkpoint=cp, retryable=r.retryable or r.library)

    await manage.mark_done(session, job, plan)
    return InteractResult(True, "đã xoá")


if get_settings().x_enabled:
    register_manage(Platform.X, run)
