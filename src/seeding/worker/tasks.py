"""Job cua worker - phan 2: dang bai.

tick()          quet job toi gio, qua governor (ramp + quiet period), day vao queue
run_post_job()  dang mot bai, ghi Attempt, quyet dinh retry / cho nguoi / bo
prune_media()   don ban bien the media cu
"""

from __future__ import annotations

import asyncio
import random
import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select, update

from seeding.config import get_settings
from seeding.db import SessionLocal
from seeding.domain import profiles as profiles_mod
from seeding.domain import readiness
from seeding.domain.models import AccountStatus, Attempt, JobStatus, PostJob
from seeding.platforms import base as adapters
from seeding.platforms.tiktok import publish as _tiktok  # noqa: F401 - import de dang ky adapter
from seeding.scheduling import governor
from seeding.scheduling import slots as slots_mod
from seeding.scheduling.planner import due_jobs

log = structlog.get_logger(__name__)

MAX_ATTEMPTS = 3
RETRY_BACKOFF = [timedelta(minutes=5), timedelta(minutes=30), timedelta(hours=2)]


async def tick(ctx: dict) -> int:
    """Quet job dang bai toi gio. Chay moi 30 giay."""
    settings = get_settings()
    now = datetime.now(UTC)
    enqueued = 0

    async with SessionLocal() as session:
        slot_tables = None
        for job in await due_jobs(session, now):
            allowed, reason = await governor.check(
                session,
                job.account,
                settings.warmup_days,
                now,
                quiet_days=settings.warmup_quiet_days,
            )
            if not allowed:
                # Lui toi MOC GIO VANG ke tiep chu khong phai +1 tieng: job bi chan vi
                # chua het quiet period se duoc tha dung gio vang.
                if slot_tables is None:
                    slot_tables = await slots_mod.load(session)
                job.scheduled_at = slots_mod.defer(
                    slot_tables.get(job.account.platform),
                    now=now,
                    rng=random.Random(str(job.id)),
                    zone=slots_mod.tz(),
                )
                job.last_error = f"rate governor: {reason}"
                await session.commit()
                log.info("tick.deferred", job=str(job.id), reason=reason)
                continue

            # Claim nguyen tu: chi mot worker gianh duoc job nay.
            claimed = await session.execute(
                update(PostJob)
                .where(PostJob.id == job.id, PostJob.status == JobStatus.SCHEDULED)
                .values(status=JobStatus.RUNNING)
            )
            await session.commit()
            if claimed.rowcount != 1:
                continue
            await ctx["redis"].enqueue_job("run_post_job", str(job.id))
            enqueued += 1

    if enqueued:
        log.info("tick.enqueued", count=enqueued)
    return enqueued


async def _ensure_media(session, job: PostJob) -> str | None:
    """Ban media RIENG cua tai khoan nay, render sat luc dang. Tra ve loi neu hong."""
    variant = job.variant
    if not variant.media_ref or variant.media_variant_ref:
        return None

    from seeding.content import media as media_mod
    from seeding.content import mediastore
    from seeding.domain.models import Variant

    strength = media_mod.Strength(get_settings().media_strength)
    # pHash da dung trong chien dich nay: hai tai khoan ra ban giong het la mat y nghia.
    taken = set(
        (
            await session.execute(
                select(Variant.media_phash)
                .join(PostJob, PostJob.variant_id == Variant.id)
                .where(PostJob.campaign_id == job.campaign_id, Variant.media_phash.is_not(None))
            )
        )
        .scalars()
        .all()
    )
    try:
        path, phash = await asyncio.to_thread(
            mediastore.ensure_variant,
            variant.media_ref,
            job.campaign_id,
            job.account_id,
            strength=strength,
            avoid=taken,
        )
    except media_mod.MediaError as exc:
        return f"không render được media: {exc}"

    variant.media_variant_ref = str(path)
    variant.media_phash = phash
    await session.commit()
    return None


def _next_status(job: PostJob, result) -> JobStatus:
    if result.ok:
        return JobStatus.SUCCEEDED
    if result.needs_human:
        return JobStatus.NEEDS_HUMAN
    if result.retryable and job.attempt_count < MAX_ATTEMPTS:
        return JobStatus.SCHEDULED
    return JobStatus.FAILED


async def run_post_job(ctx: dict, job_id: str) -> str:
    async with SessionLocal() as session:
        job = (
            await session.execute(select(PostJob).where(PostJob.id == uuid.UUID(job_id)))
        ).scalar_one()

        attempt = Attempt(job_id=job.id)
        session.add(attempt)
        job.attempt_count += 1
        await session.commit()

        media_error = await _ensure_media(session, job)
        if media_error:
            job.status = JobStatus.FAILED
            job.last_error = media_error
            attempt.finished_at = datetime.now(UTC)
            attempt.error = media_error
            await session.commit()
            log.warning("job.media_failed", job=job_id, error=media_error)
            return job.status.value

        profile = await profiles_mod.get_for_account(session, job.account_id)
        verdict = readiness.check(job.account, profile)
        if not verdict.ready:
            job.status = JobStatus.SKIPPED
            job.last_error = verdict.reason
            attempt.finished_at = datetime.now(UTC)
            attempt.error = verdict.reason
            await session.commit()
            log.warning("job.not_ready", handle=job.account.handle, reason=verdict.reason)
            return job.status.value

        try:
            adapter = adapters.get(job.account.platform)
        except Exception as exc:
            job.status = JobStatus.FAILED
            job.last_error = f"chưa có adapter cho {job.account.platform.value}: {exc}"
            attempt.finished_at = datetime.now(UTC)
            attempt.error = job.last_error
            await session.commit()
            return job.status.value

        # publish() doc profile.proxy - nap tuong minh, lazy-load async la MissingGreenlet.
        if profile is not None and profile.proxy_id is not None and "proxy" not in profile.__dict__:
            from seeding.domain.models import Proxy

            profile.proxy = await session.get(Proxy, profile.proxy_id)

        result = await adapter.publish(job.account, job.variant, job.target, profile=profile)

        attempt.finished_at = datetime.now(UTC)
        attempt.ok = result.ok
        attempt.remote_id = result.remote_id
        attempt.remote_url = result.remote_url
        attempt.error = result.error
        attempt.metrics = result.metrics

        job.status = _next_status(job, result)
        job.last_error = result.error
        if result.ok:
            job.account.last_posted_at = attempt.finished_at
        elif job.status == JobStatus.SCHEDULED:
            backoff = RETRY_BACKOFF[min(job.attempt_count - 1, len(RETRY_BACKOFF) - 1)]
            job.scheduled_at = datetime.now(UTC) + backoff
        elif job.status == JobStatus.NEEDS_HUMAN:
            # Hang doi cho nguoi (phan 4) doc tu trang thai tai khoan. Dung tai khoan
            # lai o day de khong job nao khac cua no chay tiep trong luc cho.
            job.account.status = AccountStatus.NEEDS_HUMAN

        await session.commit()
        log.info(
            "job.finished",
            job=job_id,
            handle=job.account.handle,
            status=job.status.value,
            url=result.remote_url,
        )
        return job.status.value


async def prune_media(ctx: dict) -> int:
    """Don ban bien the cu. Mot chien dich 100 tai khoan voi video 5 MB la 500 MB cho MOT bai."""
    from seeding.content import mediastore

    result = await asyncio.to_thread(mediastore.prune, get_settings().media_variant_keep_days)
    if result["removed"]:
        log.info("prune_media.done", **result)
    return int(result["removed"])
