"""Lich: tuan nao dang gi, len lich mot bai cho nhieu tai khoan, doi ngay, huy."""

from __future__ import annotations

import random
import uuid
from datetime import UTC, date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from seeding.api.deps import get_session
from seeding.api.schemas import AttemptOut, DeleteOut, JobMove, JobOut, ScheduleIn
from seeding.domain import readiness
from seeding.domain.defaults import ensure_defaults
from seeding.domain.models import (
    Account,
    Attempt,
    Campaign,
    CampaignGroup,
    ContentItem,
    JobStatus,
    PostJob,
    PostKind,
    Profile,
    Variant,
)
from seeding.scheduling import planner
from seeding.scheduling import slots as slots_mod

router = APIRouter(prefix="/schedule", tags=["schedule"])


def _job_out(job: PostJob, content_id: uuid.UUID | None, remote_url: str | None) -> JobOut:
    return JobOut(
        id=job.id,
        campaign_id=job.campaign_id,
        content_id=content_id,
        account_id=job.account_id,
        handle=job.account.handle,
        platform=job.account.platform,
        status=job.status,
        scheduled_at=job.scheduled_at,
        title=job.variant.title,
        body=job.variant.body,
        remote_url=remote_url,
        last_error=job.last_error,
        attempt_count=job.attempt_count,
    )


async def _remote_urls(s: AsyncSession, job_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not job_ids:
        return {}
    rows = (
        await s.execute(
            select(Attempt.job_id, Attempt.remote_url).where(
                Attempt.job_id.in_(job_ids), Attempt.ok.is_(True)
            )
        )
    ).all()
    return {j: u for j, u in rows if u}


@router.get("", response_model=list[JobOut])
async def list_jobs(
    start: date = Query(..., description="ngày đầu (giờ địa phương)"),
    days: int = Query(7, ge=1, le=31),
    account_id: uuid.UUID | None = None,
    s: AsyncSession = Depends(get_session),
) -> list[JobOut]:
    zone = slots_mod.tz()
    lo = datetime.combine(start, time.min, tzinfo=zone).astimezone(UTC)
    hi = lo + timedelta(days=days)
    stmt = (
        select(PostJob)
        .where(PostJob.scheduled_at >= lo, PostJob.scheduled_at < hi)
        .options(selectinload(PostJob.variant).selectinload(Variant.content_item))
        .order_by(PostJob.scheduled_at)
    )
    if account_id is not None:
        stmt = stmt.where(PostJob.account_id == account_id)
    jobs = list((await s.execute(stmt)).unique().scalars().all())
    urls = await _remote_urls(s, [j.id for j in jobs])
    return [_job_out(j, j.variant.content_item_id, urls.get(j.id)) for j in jobs]


@router.post("", response_model=list[JobOut])
async def schedule(body: ScheduleIn, s: AsyncSession = Depends(get_session)) -> list[JobOut]:
    """Len lich MOT bai cho nhieu tai khoan. Moi tai khoan mot bien the, bam vao gio vang
    tu ngay bat dau; cung ngay thi rai qua cac moc khac nhau."""
    content = await s.get(ContentItem, body.content_id)
    if content is None:
        raise HTTPException(404, "Không có bài này")
    if not body.account_ids:
        raise HTTPException(422, "Chọn ít nhất một tài khoản.")

    accounts = list(
        (
            await s.execute(
                select(Account)
                .where(Account.id.in_(body.account_ids))
                .options(selectinload(Account.profile).selectinload(Profile.proxy))
            )
        )
        .unique()
        .scalars()
    )
    if len(accounts) != len(set(body.account_ids)):
        raise HTTPException(404, "Có tài khoản không tồn tại.")
    platforms = {a.platform for a in accounts}
    if len(platforms) != 1:
        raise HTTPException(422, "Một lần lên lịch chỉ cho một nền tảng.")
    blocked = [a.handle for a in accounts if not readiness.check(a, a.profile).ready]
    if blocked:
        raise HTTPException(
            409, "Chưa sẵn sàng nên không lên lịch được: " + ", ".join(blocked[:10])
        )

    zone = slots_mod.tz()
    now = datetime.now(UTC)
    if body.start_date is None or body.start_date <= now.astimezone(zone).date():
        starts_at = now
    else:
        starts_at = datetime.combine(body.start_date, time.min, tzinfo=zone).astimezone(UTC)

    workspace, _ = await ensure_defaults(s)
    campaign = Campaign(
        workspace_id=workspace.id,
        content_item_id=content.id,
        name=f"{content.title_template[:40]} · {starts_at.astimezone(zone):%d/%m}",
        starts_at=starts_at,
        stagger_window_seconds=body.stagger_seconds,
    )
    s.add(campaign)
    await s.flush()
    group = CampaignGroup(
        campaign_id=campaign.id,
        name=platforms.pop().value,
        platform=accounts[0].platform,
        post_kind=PostKind.POST,
        target={},
        account_ids=[str(a.id) for a in accounts],
    )
    s.add(group)
    await s.commit()

    try:
        jobs = await planner.plan_campaign(s, campaign.id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    # nap lai voi quan he account/variant
    ids = [j.id for j in jobs]
    jobs = list(
        (await s.execute(select(PostJob).where(PostJob.id.in_(ids)).order_by(PostJob.scheduled_at)))
        .unique()
        .scalars()
    )
    return [_job_out(j, content.id, None) for j in jobs]


@router.patch("/{job_id}", response_model=JobOut)
async def move_job(
    job_id: uuid.UUID, body: JobMove, s: AsyncSession = Depends(get_session)
) -> JobOut:
    """Doi ngay. Bam vao moc gio vang cua ngay do (uu tien `hour` neu ngay do co moc ay)."""
    job = await s.get(PostJob, job_id)
    if job is None:
        raise HTTPException(404, "Không có job này")
    if job.status is not JobStatus.SCHEDULED:
        raise HTTPException(409, f"Job đang ở trạng thái {job.status.value}, không dời được.")

    zone = slots_mod.tz()
    now = datetime.now(UTC)
    day_start = datetime.combine(body.date, time.min, tzinfo=zone)
    tables = await slots_mod.load(s)
    table = tables.get(job.account.platform) or {}
    rng = random.Random(f"move:{job.id}:{body.date.isoformat()}")

    when: datetime | None = None
    if body.hour is not None:
        for t in table.get(body.date.weekday(), []):
            if t.hour == body.hour:
                when = datetime.combine(body.date, t, tzinfo=zone)
                break
        if when is None:
            when = datetime.combine(body.date, time(body.hour), tzinfo=zone)
    elif table:
        try:
            when = slots_mod.choose(
                table, not_before=max(day_start, now.astimezone(zone)), rng=rng, zone=zone
            )
        except ValueError:
            when = None
    if when is None:
        when = day_start + timedelta(hours=9)
    when = when.astimezone(UTC) + timedelta(seconds=rng.randrange(slots_mod.JITTER_MAX_SECONDS))
    if when < now:
        when = now + timedelta(minutes=2)

    job.scheduled_at = when
    job.last_error = None
    await s.commit()
    urls = await _remote_urls(s, [job.id])
    return _job_out(job, job.variant.content_item_id, urls.get(job.id))


@router.delete("/{job_id}", response_model=DeleteOut)
async def cancel_job(job_id: uuid.UUID, s: AsyncSession = Depends(get_session)) -> DeleteOut:
    job = await s.get(PostJob, job_id)
    if job is None:
        raise HTTPException(404, "Không có job này")
    if job.status not in (
        JobStatus.SCHEDULED,
        JobStatus.FAILED,
        JobStatus.SKIPPED,
        JobStatus.NEEDS_HUMAN,
    ):
        raise HTTPException(409, f"Job đang {job.status.value}, không huỷ được.")
    handle = job.account.handle
    await s.delete(job)
    await s.commit()
    return DeleteOut(deleted=True, detail=f"Đã huỷ bài của {handle}")


@router.get("/{job_id}/attempts", response_model=list[AttemptOut])
async def attempts(job_id: uuid.UUID, s: AsyncSession = Depends(get_session)) -> list[AttemptOut]:
    rows = (
        await s.execute(
            select(Attempt).where(Attempt.job_id == job_id).order_by(Attempt.started_at)
        )
    ).scalars()
    return [AttemptOut.model_validate(a) for a in rows]
