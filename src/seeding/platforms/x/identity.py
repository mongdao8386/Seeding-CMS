"""Doi ten / username / anh dai dien tren X qua twifork.

Ten hien thi di qua `update_profile` cua twifork (v1.1 account/update_profile). Username
va anh thi twifork chua co: hai endpoint v1.1 cung ho (account/settings, account/
update_profile_image) duoc goi bang chinh lop request cua no - cung cookie, cung
X-Client-Transaction-Id. CHUA thu tren tai khoan that.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from seeding.browser.checkpoints import Checkpoint, CheckpointKind
from seeding.config import get_settings
from seeding.content import identity, mediastore
from seeding.domain.models import ActivityJob, Platform, Profile
from seeding.platforms.base import InteractResult, register_identity
from seeding.platforms.outreach import ensure_proxy_loaded
from seeding.platforms.x.client import XClient, classify_exc

log = structlog.get_logger(__name__)


def _avatar_for(job: ActivityJob, filename: str) -> Path:
    source = mediastore.resolve_source(filename)
    dest = mediastore.variants_dir() / f"avatar-{job.account_id}-{source.stem}.jpg"
    return identity.avatar_variant(source, dest, seed=f"{job.account_id}:{filename}")


async def run(
    session: AsyncSession,
    profile: Profile,
    job: ActivityJob,
    *,
    client_factory=XClient,
) -> InteractResult:
    plan = identity.plan_from_target(job.target_url)
    if not plan:
        return InteractResult(False, "identity job has no plan")
    await ensure_proxy_loaded(session, profile)
    if profile.proxy is None:
        return InteractResult(False, "profile has no proxy - refusing to touch X")

    done: list[str] = []
    try:
        async with client_factory(profile) as x:
            if plan.get("avatar"):
                path = await asyncio.to_thread(_avatar_for, job, plan["avatar"])
                await x.change_picture(path)
                done.append("ảnh đại diện")
            if plan.get("display_name"):
                await x.edit_profile(name=plan["display_name"])
                done.append(f"tên → {plan['display_name']}")
            if plan.get("username"):
                await x.change_username(plan["username"])
                done.append(f"username → @{plan['username']}")
    except Exception as exc:
        r = classify_exc(exc, idempotent=False)
        partial = f" (đã xong: {', '.join(done)})" if done else ""
        if r.terminal:
            cp = Checkpoint(CheckpointKind.SUSPENDED, r.detail)
        elif r.needs_human:
            cp = Checkpoint(CheckpointKind.VERIFY, r.detail)
        else:
            cp = None
        log.warning("x_identity.failed", job=str(job.id), error=r.detail)
        return InteractResult(
            False, r.detail + partial, checkpoint=cp, retryable=r.retryable or r.library
        )

    if plan.get("username"):
        job.account.handle = plan["username"]
    log.info("x_identity.done", handle=job.account.handle, changed=done)
    return InteractResult(True, "đổi: " + ", ".join(done))


if get_settings().x_enabled:
    register_identity(Platform.X, run)
