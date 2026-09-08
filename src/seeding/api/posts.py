"""Bai DA DANG: liet ke, xoa tren nen tang, sua chu thich.

Mot bai da len = mot Attempt(ok=True) co remote_url. Xoa / sua la viec cua worker (qua
proxy cua tai khoan), hen trong 1-2 phut, ket qua len dong thoi gian. Attempt khong bao
gio bi xoa: bai da tung len la lich su co that; chi ghi them deleted_at / edited_at.
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from seeding.api.deps import get_session
from seeding.api.schemas import PostEditIn, PostOut
from seeding.domain import profiles as profiles_mod
from seeding.domain import readiness
from seeding.domain.models import (
    Account,
    ActivityJob,
    ActivityKind,
    Attempt,
    JobStatus,
    Platform,
    PostJob,
    Variant,
)
from seeding.platforms import manage

router = APIRouter(prefix="/posts", tags=["posts"])

_PENDING = (JobStatus.SCHEDULED, JobStatus.RUNNING, JobStatus.PENDING)
_MANAGE = (ActivityKind.DELETE, ActivityKind.EDIT)


async def _pending_for(s: AsyncSession, attempt_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    """attempt_id -> 'delete' | 'edit' dang cho chay."""
    if not attempt_ids:
        return {}
    rows = (
        await s.execute(
            select(ActivityJob).where(
                ActivityJob.kind.in_(_MANAGE), ActivityJob.status.in_(_PENDING)
            )
        )
    ).scalars()
    out: dict[uuid.UUID, str] = {}
    wanted = {str(a) for a in attempt_ids}
    for j in rows:
        plan = manage.decode(j.target_url)
        if plan and plan.attempt_id in wanted:
            out[uuid.UUID(plan.attempt_id)] = plan.action
    return out


def _out(a: Attempt, job: PostJob, pending: str | None) -> PostOut:
    m = a.metrics or {}
    platform = job.account.platform
    return PostOut(
        attempt_id=a.id,
        job_id=job.id,
        account_id=job.account_id,
        handle=job.account.handle,
        platform=platform,
        title=job.variant.title,
        caption=m.get("caption")
        or (
            f"{job.variant.title}\n\n{job.variant.body}".strip()
            if job.variant.body
            else job.variant.title
        ),
        remote_id=a.remote_id,
        remote_url=a.remote_url,
        posted_at=a.finished_at or a.started_at,
        deleted_at=datetime.fromisoformat(m["deleted_at"]) if m.get("deleted_at") else None,
        edited_at=datetime.fromisoformat(m["edited_at"]) if m.get("edited_at") else None,
        pending=pending,
        can_delete=manage.supported(ActivityKind.DELETE, platform),
        can_edit=manage.supported(ActivityKind.EDIT, platform),
    )


@router.get("", response_model=list[PostOut])
async def list_posts(
    account_id: uuid.UUID | None = None,
    platform: Platform | None = None,
    include_deleted: bool = False,
    limit: int = Query(100, ge=1, le=500),
    s: AsyncSession = Depends(get_session),
) -> list[PostOut]:
    stmt = (
        select(Attempt)
        .join(PostJob, PostJob.id == Attempt.job_id)
        .join(Account, Account.id == PostJob.account_id)
        .where(Attempt.ok.is_(True), Attempt.remote_url.is_not(None))
        .options(
            selectinload(Attempt.job).selectinload(PostJob.account),
            selectinload(Attempt.job).selectinload(PostJob.variant),
        )
        .order_by(Attempt.finished_at.desc().nulls_last())
        .limit(limit)
    )
    if account_id is not None:
        stmt = stmt.where(PostJob.account_id == account_id)
    if platform is not None:
        stmt = stmt.where(Account.platform == platform)
    attempts = list((await s.execute(stmt)).unique().scalars().all())
    pending = await _pending_for(s, [a.id for a in attempts])
    out = []
    for a in attempts:
        if not include_deleted and (a.metrics or {}).get("deleted_at"):
            continue
        out.append(_out(a, a.job, pending.get(a.id)))
    return out


async def _load(s: AsyncSession, attempt_id: uuid.UUID) -> tuple[Attempt, PostJob]:
    a = await s.get(
        Attempt,
        attempt_id,
        options=[
            selectinload(Attempt.job).selectinload(PostJob.account),
            selectinload(Attempt.job).selectinload(PostJob.variant),
        ],
    )
    if a is None or not a.ok or not a.remote_id:
        raise HTTPException(404, "Không có bài đã đăng này")
    return a, a.job


async def _schedule(s: AsyncSession, a: Attempt, job: PostJob, plan: manage.Plan) -> PostOut:
    account = job.account
    if err := manage.supported(plan.kind, account.platform):
        raise HTTPException(409, err)
    if (a.metrics or {}).get("deleted_at"):
        raise HTTPException(409, "Bài này đã xoá rồi")
    if await _pending_for(s, [a.id]):
        raise HTTPException(409, "Đang có một việc chờ chạy cho bài này")
    profile = await profiles_mod.get_for_account(s, account.id)
    verdict = readiness.check(account, profile)
    if not verdict.ready:
        raise HTTPException(409, f"{account.handle}: {verdict.reason}")
    s.add(
        ActivityJob(
            account_id=account.id,
            kind=plan.kind,
            status=JobStatus.SCHEDULED,
            scheduled_at=datetime.now(UTC) + timedelta(seconds=random.randint(30, 120)),
            duration_seconds=30,
            target_url=manage.encode(plan),
        )
    )
    await s.commit()
    return _out(a, job, plan.action)


@router.post("/{attempt_id}/delete", response_model=PostOut)
async def delete_post(attempt_id: uuid.UUID, s: AsyncSession = Depends(get_session)) -> PostOut:
    """Xoa bai tren nen tang (worker lam trong 1-2 phut)."""
    a, job = await _load(s, attempt_id)
    plan = manage.Plan("delete", str(a.id), a.remote_id or "", a.remote_url or "")
    return await _schedule(s, a, job, plan)


@router.post("/{attempt_id}/edit", response_model=PostOut)
async def edit_post(
    attempt_id: uuid.UUID, body: PostEditIn, s: AsyncSession = Depends(get_session)
) -> PostOut:
    """Sua chu thich tren nen tang (worker lam trong 1-2 phut)."""
    a, job = await _load(s, attempt_id)
    caption = body.caption.strip()
    if not caption:
        raise HTTPException(422, "Chú thích trống")
    plan = manage.Plan("edit", str(a.id), a.remote_id or "", a.remote_url or "", caption=caption)
    return await _schedule(s, a, job, plan)


@router.post("/{attempt_id}/cancel", response_model=PostOut)
async def cancel_post_action(
    attempt_id: uuid.UUID, s: AsyncSession = Depends(get_session)
) -> PostOut:
    a, job = await _load(s, attempt_id)
    rows = (
        await s.execute(
            select(ActivityJob).where(
                ActivityJob.kind.in_(_MANAGE), ActivityJob.status == JobStatus.SCHEDULED
            )
        )
    ).scalars()
    for j in rows:
        plan = manage.decode(j.target_url)
        if plan and plan.attempt_id == str(a.id):
            j.status = JobStatus.SKIPPED
            j.last_error = "huỷ từ dashboard"
    await s.commit()
    return _out(a, job, None)


__all__ = ["Variant", "router"]
