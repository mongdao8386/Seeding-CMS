"""Doi ten / username / anh dai dien tren Instagram qua aiograpi."""

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
from seeding.platforms.instagram.client import InstagramClient, classify_exc
from seeding.platforms.outreach import ensure_proxy_loaded

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
    client_factory=InstagramClient,
) -> InteractResult:
    plan = identity.plan_from_target(job.target_url)
    if not plan:
        return InteractResult(False, "identity job has no plan")
    await ensure_proxy_loaded(session, profile)
    if profile.proxy is None:
        return InteractResult(False, "profile has no proxy - refusing to touch Instagram")

    done: list[str] = []
    try:
        async with client_factory(profile) as ig:
            if plan.get("avatar"):
                path = await asyncio.to_thread(_avatar_for, job, plan["avatar"])
                await ig.change_picture(path)
                done.append("ảnh đại diện")
            fields = {}
            if plan.get("username"):
                fields["username"] = plan["username"]
            if plan.get("display_name"):
                fields["full_name"] = plan["display_name"]
            if fields:
                await ig.edit_profile(**fields)
                if "username" in fields:
                    done.append(f"username → @{fields['username']}")
                if "full_name" in fields:
                    done.append(f"tên → {fields['full_name']}")
    except Exception as exc:
        r = classify_exc(exc, idempotent=False)
        partial = f" (đã xong: {', '.join(done)})" if done else ""
        if r.terminal:
            cp = Checkpoint(CheckpointKind.SUSPENDED, r.detail)
        elif r.needs_human:
            cp = Checkpoint(CheckpointKind.VERIFY, r.detail)
        else:
            cp = None
        log.warning("instagram_identity.failed", job=str(job.id), error=r.detail)
        return InteractResult(False, r.detail + partial, checkpoint=cp, retryable=r.retryable)

    if plan.get("username"):
        job.account.handle = plan["username"]
    log.info("instagram_identity.done", handle=job.account.handle, changed=done)
    return InteractResult(True, "đổi: " + ", ".join(done))


if get_settings().instagram_enabled:
    register_identity(Platform.INSTAGRAM, run)
