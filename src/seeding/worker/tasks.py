"""Job cua worker.

tick()             quet job dang bai toi gio, kiem rate governor, day vao queue
activity_tick()    quet job hoat dong nen toi gio
run_post_job()     dang mot bai, ghi Attempt, quyet dinh retry / cho nguoi / bo
run_activity_job() mot lan "song" tren nen tang ma khong dang gi
health_sweep()     kiem tra cac phien da qua han
plan_activity()    lap lich hoat dong nen cho ngay moi
repeat_tick()      sinh ky ke tiep cua cac chien dich lap lai
graph_tick()       moc them mot it canh trong do thi tuong tac cheo
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select, update

from seeding.adapters import base as adapters
from seeding.adapters import browser as _browser  # noqa: F401 - import de dang ky adapter
from seeding.adapters import reddit as _reddit  # noqa: F401 - import de dang ky adapter
from seeding.adapters import tiktok_http as _tiktok_http  # noqa: F401 - SAU browser: ghi de TikTok
from seeding.config import get_settings
from seeding.core import activity as activity_mod
from seeding.core import graph, outreach, ratelimit, readiness, recurring, takeover
from seeding.core import profiles as profiles_mod
from seeding.core import slots as slots_mod
from seeding.core.planner import due_jobs
from seeding.db import SessionLocal
from seeding.models import (
    TARGETED_KINDS,
    Account,
    ActivityJob,
    ActivityKind,
    Attempt,
    JobStatus,
    Platform,
    PostJob,
    Variant,
)

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
            allowed, reason = await ratelimit.check(
                session,
                job.account,
                settings.warmup_days,
                now,
                quiet_days=settings.warmup_quiet_days,
            )

            if not allowed:
                # Chua duoc chay thi lui lai, khong danh that bai. Lui toi MOC KHUNG GIO
                # VANG ke tiep chu khong phai +1 tieng: job bi chan vi chua het quiet
                # period se duoc tha dung gio vang, thay vi troi dan vao gio ngau nhien.
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
                log.info(
                    "tick.deferred",
                    job=str(job.id),
                    reason=reason,
                    until=job.scheduled_at.isoformat(timespec="minutes"),
                )
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


async def activity_tick(ctx: dict) -> int:
    """Quet job hoat dong nen toi gio.

    Khong qua rate governor: tran cua governor la tran DANG BAI. Hoat dong nen chinh
    la thu can nhieu, chan no lai la di nguoc muc dich.
    """
    now = datetime.now(UTC)
    enqueued = 0

    async with SessionLocal() as session:
        for job in await activity_mod.due_activity(session, now):
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


async def plan_activity(ctx: dict) -> int:
    """Lap lich hoat dong nen cho ngay hom nay. Chay mot lan moi ngay."""
    async with SessionLocal() as session:
        created = await activity_mod.plan_all(session)
        # Nuoi huong ra ngoai (tha tim / theo doi / binh luan tren For You). Rieng
        # TikTok, va chi khi duong HTTP bat - trinh duyet khong tai noi feed qua proxy.
        outward = 0
        if get_settings().tiktok_interact_via_http:
            outward = await outreach.plan_all(session)
    if created or outward:
        log.info("plan_activity.done", created=created, outward=outward)
    return created + outward


async def repeat_tick(ctx: dict) -> int:
    """Sinh ky ke tiep cua cac chien dich lap lai. Chay mot lan moi gio.

    Moi gio chu khong moi ngay: ky tinh tu `last_repeated_at` nen chay day hon chi lam
    ban sao xuat hien dung gio hon, khong lam no xuat hien nhieu hon.
    """
    async with SessionLocal() as session:
        created = await recurring.run_due(session)
    if created:
        log.info("repeat_tick.done", jobs=created)
    return created


async def graph_tick(ctx: dict) -> int:
    """Moc them mot it canh trong do thi tuong tac cheo. Chay mot lan moi ngay.

    Do thi phai LON LEN theo thoi gian. Nam muoi canh xuat hien trong mot buoi sang la
    mot su kien, khong phai mot mang xa hoi - nen so canh moi bi chan cung trong
    core/graph.py chu khong phai o day.
    """
    async with SessionLocal() as session:
        edges = await graph.plan_follows(session)
        jobs = await graph.due_follow_jobs(session)

        # Do lai sau khi them. Do thi vuot tran la thu phai hien ra trong nhat ky ngay,
        # chu khong phai doi den luc nguoi van hanh tinh co mo man hinh len xem.
        report = await graph.audit(session)
        for warning in report.warnings:
            log.warning("graph.warning", detail=warning)

    if edges or jobs:
        log.info("graph_tick.done", edges=len(edges), jobs=len(jobs))
    return len(jobs)


async def prune_media(ctx: dict) -> int:
    """Don ban bien the cu. Chay mot lan moi ngay.

    Bai da dang roi thi ban bien the khong con tac dung gi. Mot chien dich 100 tai khoan
    voi video 5 MB la 500 MB cho MOT bai - khong don thi day dia rat nhanh.
    """
    import asyncio

    from seeding.core import mediastore

    settings = get_settings()
    result = await asyncio.to_thread(mediastore.prune, settings.media_variant_keep_days)
    if result["removed"]:
        log.info("prune_media.done", **result)
    return int(result["removed"])


async def health_sweep(ctx: dict) -> int:
    """Kiem tra cac phien da qua han.

    Chay tuan tu chu khong song song: moi lan kiem la mot lan mo trinh duyet that,
    khoang 400MB RAM. Da co lich giai deu roi thi khong can voi.
    """
    from seeding.browser.session import check_session

    settings = get_settings()
    checked = 0

    async with SessionLocal() as session:
        # Doi soat truoc: tai khoan ket ma bi bo quen thi khong bao gio hien ra cho
        # nguoi van hanh, va se nam do mai.
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

            ok, detail = await check_session(profile, account.platform)
            needs_human = await profiles_mod.mark_health(
                session,
                profile,
                ok,
                detail=detail,
                threshold=settings.health_fail_threshold,
            )

            # Bat buoc: khong mo yeu cau thi tai khoan nam o NEEDS_HUMAN ma khong bao
            # gio hien ra trong hang doi - nguoi van hanh khong biet de cuu.
            if needs_human:
                await takeover.open_request(session, account, f"session died: {detail}")

            checked += 1
            log.info("health.checked", handle=account.handle, alive=ok, detail=detail)

    if checked:
        log.info("health_sweep.done", checked=checked)
    return checked


async def run_post_job(ctx: dict, job_id: str) -> str:
    async with SessionLocal() as session:
        job = (
            await session.execute(select(PostJob).where(PostJob.id == uuid.UUID(job_id)))
        ).scalar_one()

        attempt = Attempt(job_id=job.id)
        session.add(attempt)
        job.attempt_count += 1
        await session.commit()

        # Render ban media rieng cua tai khoan nay, ngay truoc khi dang. Da co cache
        # theo cong thuc nen chay lai khong ton them gi.
        media_error = await _ensure_media(session, job)
        if media_error:
            job.status = JobStatus.FAILED
            job.last_error = media_error
            attempt.finished_at = datetime.now(UTC)
            attempt.error = media_error
            await session.commit()
            log.warning("job.media_failed", job=job_id, error=media_error)
            return job.status.value

        adapter = adapters.get(job.account.platform)
        profile = await profiles_mod.get_for_account(session, job.account_id)

        # Cung lop chan nhu ben hoat dong nen. Quan trong hon o day: mot bai dang tu
        # IP nha nguoi dung khong rut lai duoc, khac han mot job hoat dong nen that bai.
        verdict = readiness.check(job.account, profile)
        if not verdict.ready:
            job.status = JobStatus.SKIPPED
            job.last_error = verdict.reason
            await session.commit()
            log.warning("job.not_ready", handle=job.account.handle, reason=verdict.reason)
            return job.status.value

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

        # Gap checkpoint thi dua tai khoan vao hang doi cho nguoi, va nho lai job nao
        # bi ket de giai xong con thu lai dung job do.
        if job.status == JobStatus.NEEDS_HUMAN:
            await takeover.open_request(
                session, job.account, result.error or "checkpoint", post_job_id=job.id
            )

        # Bai da len thi lap lich tuong tac cheo. Chi mot phan nguoi theo doi, va cham -
        # luat nam trong core/graph.py, khong phai o day.
        if job.status == JobStatus.SUCCEEDED and result.remote_url:
            try:
                await graph.engage_with(session, job)
            except Exception as exc:
                # Tuong tac hong khong duoc lam hong ket qua dang bai. Bai da len that
                # roi; danh dau job that bai o day se khien no bi dang lai lan nua.
                await session.rollback()
                log.warning("graph.engage_failed", job=job_id, error=f"{type(exc).__name__}: {exc}")

        log.info(
            "job.finished",
            job=job_id,
            handle=job.account.handle,
            status=job.status.value,
            url=result.remote_url,
        )
        return job.status.value


async def run_activity_job(ctx: dict, job_id: str) -> str:
    from seeding.browser import activity as activity_runner

    async with SessionLocal() as session:
        job = (
            (await session.execute(select(ActivityJob).where(ActivityJob.id == uuid.UUID(job_id))))
            .unique()
            .scalar_one()
        )

        job.attempt_count += 1
        profile = await profiles_mod.get_for_account(session, job.account_id)

        # Chan o day chu khong chi o giao dien. Giao dien chi la loi nhac; day la lop
        # that su ngan job chay.
        #
        # Truong hop nguy hiem nhat la profile CO nhung khong co proxy: trinh duyet van
        # mo, van vao duoc trang, chi la di ra bang dia chi nha nguoi dung - va moi tai
        # khoan chay nhu vay deu hien ra tren cung mot IP.
        verdict = readiness.check(job.account, profile)
        if not verdict.ready:
            job.status = JobStatus.SKIPPED
            job.last_error = verdict.reason
            await session.commit()
            log.warning(
                "activity.not_ready",
                handle=job.account.handle,
                reason=verdict.reason,
            )
            return job.status.value

        if job.kind in TARGETED_KINDS:
            if job.account.platform is Platform.TIKTOK and get_settings().tiktok_interact_via_http:
                # HTTP thay trinh duyet: trang TikTok khong tai noi qua proxy dan cu,
                # endpoint thi 1-3 giay. Cung hop dong ket qua.
                from seeding.core import tiktok_interact

                result = await tiktok_interact.run(session, profile, job)
            else:
                from seeding.browser import interact

                target_handle = None
                if job.target_account_id is not None:
                    target = await session.get(Account, job.target_account_id)
                    target_handle = target.handle if target else None

                result = await interact.run(
                    profile,
                    job.account.platform,
                    job.kind,
                    target_url=job.target_url,
                    target_handle=target_handle,
                    budget_seconds=job.duration_seconds,
                )

            # Canh chi tinh la co that khi trinh duyet lam duoc that. Coi canh da lap
            # ke hoach la da xong thi moi phep tinh mat do sau do deu sai.
            if job.kind is ActivityKind.FOLLOW and job.target_account_id is not None:
                await graph.mark_edge(
                    session, job.account_id, job.target_account_id, result.ok, result.detail
                )
        else:
            result = await activity_runner.run(
                profile, job.account.platform, job.kind, job.duration_seconds
            )

        job.detail = result.detail
        if result.ok:
            job.status = JobStatus.SUCCEEDED
            job.last_error = None
        elif result.checkpoint and not result.checkpoint.is_terminal:
            job.status = JobStatus.NEEDS_HUMAN
            job.last_error = result.detail
        elif result.retryable and job.attempt_count < MAX_ATTEMPTS:
            job.status = JobStatus.SCHEDULED
            job.scheduled_at = datetime.now(UTC) + timedelta(minutes=45)
            job.last_error = result.detail
        else:
            job.status = JobStatus.FAILED
            job.last_error = result.detail

        await session.commit()

        if job.status == JobStatus.NEEDS_HUMAN:
            await takeover.open_request(session, job.account, result.detail)

        log.info(
            "activity.finished",
            job=job_id,
            handle=job.account.handle,
            kind=job.kind.value,
            status=job.status.value,
            detail=result.detail,
        )
        return job.status.value


async def _ensure_media(session, job: PostJob) -> str | None:
    """Chuan bi ban media rieng cho job nay. Tra ve mo ta loi neu that bai.

    Bai khong co media thi bo qua. Render la viec ton CPU nen chay trong thread rieng
    de khong chan vong lap su kien cua worker.
    """
    variant = job.variant
    if not variant.media_ref or variant.media_variant_ref:
        return None

    import asyncio

    from seeding.core import media as media_mod
    from seeding.core import mediastore

    strength = media_mod.Strength(get_settings().media_strength)

    # Cac pHash da dung trong chien dich nay. Hai tai khoan ra ban tri giac giong het
    # nhau la mat het y nghia cua viec sinh bien the.
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
        return f"could not render media: {exc}"

    variant.media_variant_ref = str(path)
    variant.media_phash = phash
    await session.commit()
    return None


def _next_status(job: PostJob, result) -> JobStatus:
    if result.ok:
        return JobStatus.SUCCEEDED
    if result.needs_human:
        # Khong retry - nguoi van hanh phai tiep quan.
        return JobStatus.NEEDS_HUMAN
    if result.retryable and job.attempt_count < MAX_ATTEMPTS:
        return JobStatus.SCHEDULED
    return JobStatus.FAILED
