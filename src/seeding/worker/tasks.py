"""Job cua worker.

tick()              quet job dang bai toi gio, qua governor, day vao queue
run_post_job()      dang mot bai, ghi Attempt, retry / cho nguoi / bo
plan_activity()     lap lich nuoi hom nay
activity_tick()     quet job nuoi toi gio
run_activity_job()  mot lan tha tim / follow / binh luan
health_sweep()      kiem phien qua han, mo yeu cau cho nguoi khi chet
prune_media()       don ban bien the media cu
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
from seeding.ops import flags
from seeding.platforms import base as adapters
from seeding.scheduling import governor
from seeding.scheduling import slots as slots_mod
from seeding.scheduling.planner import due_jobs

log = structlog.get_logger(__name__)

# Moi nen tang tu dang ky adapter / runner / planner / health khi duoc import.
adapters.load_all()

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
        await session.commit()

        if job.status == JobStatus.NEEDS_HUMAN:
            # Vao hang doi cho nguoi, nho job de giai xong thu lai dung job do.
            from seeding.ops import takeover

            await takeover.open_request(
                session, job.account, result.error or "checkpoint", post_job_id=job.id
            )
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


# ------------------------------------------------------------------ nuoi (phan 3)


async def plan_activity(ctx: dict) -> int:
    """Lap lich nuoi huong ra ngoai cho hom nay. Chay moi sang va luc khoi dong; ngay da
    co lich thi khong lam lai (warm.plan_for_account tu kiem)."""
    created = 0
    async with SessionLocal() as session:
        for platform, planner in adapters.warm_planners().items():
            try:
                created += await planner(session)
            except Exception as exc:
                await session.rollback()
                log.warning(
                    "plan_activity.failed",
                    platform=platform.value,
                    error=f"{type(exc).__name__}: {exc}",
                )
    if created:
        log.info("plan_activity.done", outward=created)
    return created


async def activity_tick(ctx: dict) -> int:
    """Quet job nuoi toi gio. Khong qua rate governor: tran cua governor la tran DANG BAI."""
    from seeding.domain.models import Account, ActivityJob

    now = datetime.now(UTC)
    enqueued = 0
    async with SessionLocal() as session:
        due = (
            await session.execute(
                select(ActivityJob)
                .join(Account, Account.id == ActivityJob.account_id)
                .where(
                    ActivityJob.status == JobStatus.SCHEDULED,
                    ActivityJob.scheduled_at <= now,
                    Account.status.in_([AccountStatus.WARMING, AccountStatus.ACTIVE]),
                )
                .order_by(ActivityJob.scheduled_at)
                .limit(50)
            )
        ).scalars()
        for job in list(due):
            claimed = await session.execute(
                update(ActivityJob)
                .where(ActivityJob.id == job.id, ActivityJob.status == JobStatus.SCHEDULED)
                .values(status=JobStatus.RUNNING)
            )
            await session.commit()
            if claimed.rowcount != 1:
                continue
            await ctx["redis"].enqueue_job("run_activity_job", str(job.id))
            enqueued += 1
    if enqueued:
        log.info("activity_tick.enqueued", count=enqueued)
    return enqueued


ACTIVITY_MAX_ATTEMPTS = 3


async def run_activity_job(ctx: dict, job_id: str) -> str:
    from seeding.domain.models import ActivityJob, ActivityKind

    async with SessionLocal() as session:
        job = (
            (await session.execute(select(ActivityJob).where(ActivityJob.id == uuid.UUID(job_id))))
            .unique()
            .scalar_one()
        )
        job.attempt_count += 1
        profile = await profiles_mod.get_for_account(session, job.account_id)

        verdict = readiness.check(job.account, profile)
        if not verdict.ready:
            job.status = JobStatus.SKIPPED
            job.last_error = verdict.reason
            await session.commit()
            log.warning("activity.not_ready", handle=job.account.handle, reason=verdict.reason)
            return job.status.value

        if job.kind is ActivityKind.IDENTITY:
            runner = adapters.get_identity(job.account.platform)
        elif job.kind in (ActivityKind.DELETE, ActivityKind.EDIT):
            runner = adapters.get_manage(job.account.platform)
        else:
            runner = adapters.get_interact(job.account.platform)
        if runner is None:
            result = adapters.InteractResult(
                False,
                f"chưa có đường {job.kind.value} cho {job.account.platform.value} (hoặc đang tắt)",
            )
        else:
            result = await runner(session, profile, job)

        job.detail = result.detail
        if result.ok:
            job.status = JobStatus.SUCCEEDED
            job.last_error = None
        elif result.checkpoint and not result.checkpoint.is_terminal:
            job.status = JobStatus.NEEDS_HUMAN
            job.last_error = result.detail
            from seeding.ops import takeover

            await takeover.open_request(session, job.account, result.detail)
        elif result.retryable and job.attempt_count < ACTIVITY_MAX_ATTEMPTS:
            job.status = JobStatus.SCHEDULED
            job.scheduled_at = datetime.now(UTC) + timedelta(minutes=45)
            job.last_error = result.detail
        else:
            job.status = JobStatus.FAILED
            job.last_error = result.detail
        await session.commit()
        log.info(
            "activity.finished",
            job=job_id,
            handle=job.account.handle,
            kind=job.kind.value,
            status=job.status.value,
            detail=result.detail,
        )
        return job.status.value


# ------------------------------------------------------- suc khoe phien (phan 4)


async def health_sweep(ctx: dict) -> int:
    """Kiem phien cua cac profile da qua han. Tuan tu: moi lan kiem la mot lan mo trinh
    duyet (~400MB). Endpoint nhe duoc uu tien (session.py) nen thuong chi ~15 giay."""
    from seeding.browser.session import check_session
    from seeding.domain.models import Account, Proxy
    from seeding.ops import takeover

    settings = get_settings()
    checked = 0
    async with SessionLocal() as session:
        healed = await takeover.reconcile(session)
        if healed:
            log.warning("health_sweep.reconciled", count=healed)

        due = await profiles_mod.due_for_health_check(
            session, settings.health_check_interval_hours, limit=10
        )
        for profile in due:
            account = await session.get(Account, profile.account_id)
            if account is None:
                continue
            if profile.proxy_id is not None and "proxy" not in profile.__dict__:
                profile.proxy = await session.get(Proxy, profile.proxy_id)
            # Nen tang co duong kiem nhe (HTTP qua proxy) thi dung; khong thi mo trinh duyet.
            checker = adapters.get_health(account.platform)
            try:
                if checker is not None:
                    ok, detail = await checker(profile)
                else:
                    ok, detail = await check_session(profile, account.platform)
            except adapters.LibraryBroken as exc:
                # Thu vien lech, khong phai tai khoan: khong ghi len profile, bao mot lan.
                await _library_broken(account.platform, str(exc))
                continue
            if checker is not None:
                await flags.set_flag(
                    f"library:{account.platform.value}",
                    {"ok": True, "detail": detail, "at": datetime.now(UTC).isoformat()},
                )
            needs_human = await profiles_mod.mark_health(
                session, profile, ok, detail=detail, threshold=settings.health_fail_threshold
            )
            if needs_human:
                await takeover.open_request(session, account, f"phiên chết: {detail}")
            checked += 1
            log.info("health.checked", handle=account.handle, alive=ok, detail=detail)
    if checked:
        log.info("health_sweep.done", checked=checked)
    return checked


async def _library_broken(platform, detail: str) -> None:
    """Ghi co cho Cai dat va bao ra ngoai - toi da mot lan moi 12 tieng."""
    from seeding.ops import alerts

    log.error("library.broken", platform=platform.value, detail=detail)
    await flags.set_flag(
        f"library:{platform.value}",
        {"ok": False, "detail": detail, "at": datetime.now(UTC).isoformat()},
    )
    gate = f"library-alerted:{platform.value}"
    if alerts.configured() and await flags.get_flag(gate) is None:
        alerts.send(
            f"[seeding] Thư viện {platform.value} lệch với nền tảng, mọi job {platform.value} "
            f"sẽ hỏng cho tới khi cập nhật (pip install -U twifork). {detail[:200]}"
        )
        await flags.set_flag(gate, {"at": datetime.now(UTC).isoformat()}, ttl_seconds=12 * 3600)
