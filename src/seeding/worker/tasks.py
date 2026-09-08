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
from seeding.domain.models import AccountStatus, ActivityKind, Attempt, JobStatus, PostJob
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

        await session.commit()  # khong giu giao dich mo trong luc dang bai
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


async def prune_history(ctx: dict) -> int:
    """Xoa lich su nuoi va su kien phien cu hon ACTIVITY_RETENTION_DAYS. Nghin acc clone
    la hang nghin dong moi ngay; bang activity_jobs khong duoc lon mai."""
    from sqlalchemy import delete

    from seeding.domain.models import ActivityJob, SessionEvent

    cutoff = datetime.now(UTC) - timedelta(days=get_settings().activity_retention_days)
    async with SessionLocal() as session:
        jobs = await session.execute(
            delete(ActivityJob).where(
                ActivityJob.scheduled_at < cutoff,
                ActivityJob.status.in_([JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.SKIPPED]),
            )
        )
        events = await session.execute(delete(SessionEvent).where(SessionEvent.created_at < cutoff))
        await session.commit()
    removed = int(jobs.rowcount or 0) + int(events.rowcount or 0)
    if removed:
        log.info("prune_history.done", jobs=jobs.rowcount, events=events.rowcount)
    return removed


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
        # Tuong tac cheo noi bo: booster -> bai cua tai khoan xay kenh.
        from seeding.platforms import boost

        try:
            created += await boost.plan_all(session)
        except Exception as exc:
            await session.rollback()
            log.warning("plan_activity.boost_failed", error=f"{type(exc).__name__}: {exc}")
    if created:
        log.info("plan_activity.done", outward=created)
    return created


async def reclaim_orphans() -> int:
    """Job dang RUNNING luc worker khoi dong la job mo coi: chi co mot worker, va no vua
    chet/khoi dong lai giua chung (08/09/2026: job HA1 ket RUNNING mai sau khi restart).
    Tra ve SCHEDULED de tick nhat lai; lan thu da dem roi nen khong dem them."""
    from seeding.domain.models import ActivityJob

    async with SessionLocal() as session:
        acts = await session.execute(
            update(ActivityJob)
            .where(ActivityJob.status == JobStatus.RUNNING)
            .values(status=JobStatus.SCHEDULED)
        )
        posts = await session.execute(
            update(PostJob)
            .where(PostJob.status == JobStatus.RUNNING)
            .values(status=JobStatus.SCHEDULED)
        )
        await session.commit()
    return (acts.rowcount or 0) + (posts.rowcount or 0)


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
# Mot acc chi mo MOT trinh duyet mot luc. Hai job cua cung acc chay song song (job thu lai
# sau 45 phut trung gio job ke tiep) la hai "thiet bi" cung dang nhap tu mot proxy - dau
# vet khong nguoi that nao de lai. TTL bang job_timeout de khoa khong bao gio ket mai.
ACCOUNT_LOCK_TTL = 1500
# Gom job cung acc: khi mot job trinh duyet chay, cac job MO THANG LINK khac cua cung acc
# toi han trong khoang nay di chung mot trinh duyet (toi da BATCH_MAX). Clone 2-5 luot
# thich/ngay -> mot lan mo. Phien luot (BROWSE_FEED) di rieng.
BATCH_HORIZON = timedelta(hours=4)
BATCH_MAX = 5
PER_TARGET = (
    ActivityKind.ENGAGE,
    ActivityKind.FOLLOW,
    ActivityKind.COMMENT,
    ActivityKind.REPOST,
)
# Cho mot cho trinh duyet toi da tung nay giay; khong co thi hen lai vai phut.
BROWSER_WAIT_S = 30
_browser_slots: asyncio.Semaphore | None = None


def browser_slots() -> asyncio.Semaphore:
    """Semaphore theo tien trinh: so trinh duyet mo song song. Nhieu tien trinh worker =
    nhan len bay nhieu (moi tien trinh tu gioi han phan minh)."""
    global _browser_slots
    if _browser_slots is None:
        _browser_slots = asyncio.Semaphore(max(1, get_settings().browser_concurrency))
    return _browser_slots


async def _claim_siblings(session, job) -> list:
    """Job mo thang link cua cung acc, toi han trong BATCH_HORIZON: nhan luon de chay
    chung trinh duyet. Nhan bang UPDATE co dieu kien nhu activity_tick."""
    from seeding.domain.models import ActivityJob

    if job.kind not in PER_TARGET:
        return []
    now = datetime.now(UTC)
    rows = (
        await session.execute(
            select(ActivityJob)
            .where(
                ActivityJob.account_id == job.account_id,
                ActivityJob.id != job.id,
                ActivityJob.status == JobStatus.SCHEDULED,
                ActivityJob.kind.in_(PER_TARGET),
                ActivityJob.scheduled_at <= now + BATCH_HORIZON,
            )
            .order_by(ActivityJob.scheduled_at)
            .limit(BATCH_MAX - 1)
        )
    ).scalars()
    claimed = []
    for sib in list(rows):
        res = await session.execute(
            update(ActivityJob)
            .where(ActivityJob.id == sib.id, ActivityJob.status == JobStatus.SCHEDULED)
            .values(status=JobStatus.RUNNING, attempt_count=ActivityJob.attempt_count + 1)
        )
        if res.rowcount == 1:
            claimed.append(sib)
    await session.commit()
    for sib in claimed:
        await session.refresh(sib)
    return claimed


async def _apply_result(session, job, result) -> None:
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


def _defer(job, minutes: int, why: str) -> None:
    """Tra job ve hang doi ma khong tinh mot lan thu."""
    job.attempt_count = max(0, job.attempt_count - 1)
    job.status = JobStatus.SCHEDULED
    job.scheduled_at = datetime.now(UTC) + timedelta(minutes=minutes)
    job.last_error = why


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

        # Ket thuc giao dich TRUOC khi ra mang: mot job trinh duyet keo 2-6 phut, giu
        # transaction mo ngan ay lau la giu khoa tren bang accounts - migration va ca API
        # dung lai cho no (da xay ra that 08/09/2026). expire_on_commit=False nen object van dung.
        await session.commit()

        redis = ctx.get("redis")
        lock_key = f"lock:account:{job.account_id}"
        if redis is not None and not await redis.set(
            lock_key, job_id, nx=True, ex=ACCOUNT_LOCK_TTL
        ):
            # Acc dang ban voi job khac: tra ve hang doi, thu lai sau vai phut, khong tinh
            # la mot lan thu.
            _defer(job, 3, "acc đang bận với việc khác")
            await session.commit()
            log.info("activity.deferred", job=job_id, handle=job.account.handle)
            return "deferred"

        platform = job.account.platform
        slot = browser_slots() if adapters.uses_browser(platform) else None
        if slot is not None:
            try:
                await asyncio.wait_for(slot.acquire(), timeout=BROWSER_WAIT_S)
            except TimeoutError:
                if redis is not None:
                    await redis.delete(lock_key)
                _defer(job, random.randint(2, 6), "hết chỗ trình duyệt, hẹn lại")
                await session.commit()
                log.info("activity.no_browser_slot", job=job_id, handle=job.account.handle)
                return "deferred"

        batch = [job]
        results: dict = {}
        try:
            if job.kind is ActivityKind.IDENTITY:
                runner = adapters.get_identity(platform)
            elif job.kind in (ActivityKind.DELETE, ActivityKind.EDIT):
                runner = adapters.get_manage(platform)
            else:
                runner = adapters.get_interact(platform)
            many = adapters.get_interact_many(platform) if job.kind in PER_TARGET else None
            if many is not None:
                batch += await _claim_siblings(session, job)
            if runner is None:
                results[job.id] = adapters.InteractResult(
                    False,
                    f"chưa có đường {job.kind.value} cho {platform.value} (hoặc đang tắt)",
                )
            elif many is not None and len(batch) > 1:
                results = await many(session, profile, batch)
            else:
                results[job.id] = await runner(session, profile, job)
        finally:
            if slot is not None:
                slot.release()
            if redis is not None:
                await redis.delete(lock_key)

        for item in batch:
            result = results.get(item.id)
            if result is None:
                # Chua toi luot (acc gap checkpoint o job truoc): tra ve hang doi.
                _defer(item, 3, "chưa tới lượt trong phiên trình duyệt, hẹn lại")
                continue
            await _apply_result(session, item, result)
        await session.commit()
        for item in batch:
            log.info(
                "activity.finished",
                job=str(item.id),
                handle=job.account.handle,
                kind=item.kind.value,
                status=item.status.value,
                detail=item.detail or item.last_error,
                batched=len(batch) > 1,
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
            session,
            settings.health_check_interval_hours,
            limit=settings.health_sweep_limit,
            booster_interval_hours=settings.booster_health_interval_hours,
        )
        for profile in due:
            account = await session.get(Account, profile.account_id)
            if account is None:
                continue
            if profile.proxy_id is not None and "proxy" not in profile.__dict__:
                profile.proxy = await session.get(Proxy, profile.proxy_id)
            # Nen tang co duong kiem nhe (HTTP qua proxy) thi dung; khong thi mo trinh duyet.
            await session.commit()  # kiem phien co the mo trinh duyet: khong giu giao dich
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


# ------------------------------------------------------------- chatbot (phan 10)


async def chatbot_tick(ctx: dict) -> int:
    """Moi tai khoan dang chay tren nen tang co kenh chatbot -> mot job run_chatbot.
    _job_id theo phut de hai tick khong xep trung."""
    from seeding.domain.models import Account, AccountRole, AccountStatus

    settings = get_settings()
    if not settings.chatbot_enabled:
        return 0
    channels = adapters.chatbots()
    if not channels:
        return 0
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M")
    enqueued = 0
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(Account.id).where(
                    Account.platform.in_(list(channels)),
                    Account.role == AccountRole.CHANNEL,
                    Account.status.in_([AccountStatus.WARMING, AccountStatus.ACTIVE]),
                )
            )
        ).scalars()
        for account_id in list(rows):
            await ctx["redis"].enqueue_job(
                "run_chatbot", str(account_id), _job_id=f"chatbot:{account_id}:{stamp}"
            )
            enqueued += 1
    if enqueued:
        log.info("chatbot_tick.enqueued", count=enqueued)
    return enqueued


async def run_chatbot(ctx: dict, account_id: str) -> str:
    from sqlalchemy.orm import selectinload

    from seeding.content import chatbot as writer
    from seeding.domain.models import Account
    from seeding.platforms import chatbot as engine
    from seeding.platforms import outreach

    settings = get_settings()
    async with SessionLocal() as session:
        account = await session.get(
            Account, uuid.UUID(account_id), options=[selectinload(Account.persona)]
        )
        if account is None:
            return "missing"
        profile = await profiles_mod.get_for_account(session, account.id)
        verdict = readiness.check(account, profile)
        if not verdict.ready:
            return "not_ready"
        await outreach.ensure_proxy_loaded(session, profile)
        factory = adapters.get_chatbot(account.platform)
        if factory is None:
            return "no_channel"
        replier = writer.build_replier(
            api_key=settings.anthropic_api_key, model=settings.chatbot_model
        )
        limits = engine.Limits(
            max_per_hour=settings.chatbot_max_per_hour,
            reply_ratio=settings.chatbot_reply_ratio,
            lookback_hours=settings.chatbot_lookback_hours,
        )
        report = await engine.run_for_account(
            session,
            account,
            profile,
            channel_factory=factory,
            replier=replier,
            limits=limits,
            do_comments=settings.chatbot_comments,
            do_dms=settings.chatbot_dms,
        )
        await flags.set_flag(
            "chatbot:last",
            {
                "at": datetime.now(UTC).isoformat(),
                "handle": account.handle,
                "replier": replier.name,
                "replied": report.replied,
                "dm_replied": report.dm_replied,
                "stopped": report.stopped,
            },
        )
        log.info(
            "chatbot.done",
            handle=account.handle,
            replier=replier.name,
            comments_seen=report.comments_seen,
            replied=report.replied,
            dms_seen=report.dms_seen,
            dm_replied=report.dm_replied,
            skipped=report.skipped,
            failed=report.failed,
            stopped=report.stopped,
        )
        return "ok"
