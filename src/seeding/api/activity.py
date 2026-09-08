"""Dong thoi gian cua mot tai khoan, va tong ket viec nuoi trong ngay."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from seeding.api.deps import get_session
from seeding.api.schemas import ActivitySummary, KindCount, TimelineItem
from seeding.domain.models import (
    Account,
    AccountStatus,
    ActivityJob,
    ActivityKind,
    Attempt,
    JobStatus,
    PostJob,
    Profile,
    SessionEvent,
    SessionEventKind,
)
from seeding.scheduling import slots as slots_mod

router = APIRouter(tags=["activity"])

_EVENT_VI = {
    SessionEventKind.CREATED: "Tạo profile",
    SessionEventKind.LOGIN: "Đăng nhập tay",
    SessionEventKind.HEALTH_OK: "Kiểm phiên: còn sống",
    SessionEventKind.HEALTH_FAIL: "Kiểm phiên: hỏng",
    SessionEventKind.CHECKPOINT: "Checkpoint",
    SessionEventKind.TAKEOVER: "Người xử lý",
    SessionEventKind.COOKIES_SAVED: "Lưu cookie",
}

_KIND_LABEL = {
    ActivityKind.ENGAGE: "like",
    ActivityKind.FOLLOW: "follow",
    ActivityKind.COMMENT: "comment",
    ActivityKind.REPOST: "repost",
    ActivityKind.BROWSE_FEED: "browse",
    ActivityKind.READ_POST: "browse",
    ActivityKind.REACT: "like",
    ActivityKind.WATCH_VIDEO: "browse",
}


@router.get("/accounts/{account_id}/timeline", response_model=list[TimelineItem])
async def timeline(
    account_id: uuid.UUID,
    limit: int = Query(80, ge=1, le=300),
    s: AsyncSession = Depends(get_session),
) -> list[TimelineItem]:
    """Dang bai, nuoi, su kien phien - tron lam mot, moi nhat truoc."""
    if await s.get(Account, account_id) is None:
        raise HTTPException(404, "Không có tài khoản này")

    items: list[TimelineItem] = []

    posts = (
        (await s.execute(select(PostJob).where(PostJob.account_id == account_id)))
        .unique()
        .scalars()
    )
    posts = list(posts)
    urls: dict[uuid.UUID, str] = {}
    if posts:
        rows = (
            await s.execute(
                select(Attempt.job_id, Attempt.remote_url).where(
                    Attempt.job_id.in_([p.id for p in posts]), Attempt.ok.is_(True)
                )
            )
        ).all()
        urls = {j: u for j, u in rows if u}
    for p in posts:
        items.append(
            TimelineItem(
                at=p.scheduled_at,
                kind="post",
                status=p.status,
                title=p.variant.title,
                detail=p.last_error,
                url=urls.get(p.id),
            )
        )

    acts = (
        await s.execute(
            select(ActivityJob)
            .where(ActivityJob.account_id == account_id)
            .order_by(ActivityJob.scheduled_at.desc())
            .limit(limit)
        )
    ).scalars()
    for a in acts:
        items.append(
            TimelineItem(
                at=a.scheduled_at,
                kind=_KIND_LABEL.get(a.kind, a.kind.value),
                status=a.status,
                title=_target_label(a),
                detail=a.detail or a.last_error,
                url=a.target_url,
            )
        )

    profile_id = (
        await s.execute(select(Profile.id).where(Profile.account_id == account_id))
    ).scalar_one_or_none()
    if profile_id is not None:
        events = (
            await s.execute(
                select(SessionEvent)
                .where(SessionEvent.profile_id == profile_id)
                .order_by(SessionEvent.created_at.desc())
                .limit(limit)
            )
        ).scalars()
        for e in events:
            items.append(
                TimelineItem(
                    at=e.created_at,
                    kind="session",
                    status=None,
                    title=_EVENT_VI.get(e.kind, e.kind.value),
                    detail=e.detail,
                    url=None,
                )
            )

    items.sort(key=lambda i: i.at, reverse=True)
    return items[:limit]


def _target_label(a: ActivityJob) -> str:
    url = a.target_url or ""
    handle = url.split("/@")[1].split("/")[0] if "/@" in url else ""
    verb = {
        ActivityKind.ENGAGE: "Thả tim",
        ActivityKind.FOLLOW: "Follow",
        ActivityKind.COMMENT: "Bình luận",
        ActivityKind.REPOST: "Đăng lại",
    }.get(a.kind, a.kind.value)
    return f"{verb} @{handle}" if handle else verb


@router.get("/activity/summary", response_model=ActivitySummary)
async def summary(
    day: date | None = None, s: AsyncSession = Depends(get_session)
) -> ActivitySummary:
    """Hom nay (gio dia phuong) da nuoi bao nhieu, con bao nhieu."""
    zone = slots_mod.tz()
    day = day or datetime.now(UTC).astimezone(zone).date()
    lo = datetime.combine(day, time.min, tzinfo=zone).astimezone(UTC)
    hi = lo + timedelta(days=1)

    rows = (
        await s.execute(
            select(ActivityJob.kind, ActivityJob.status, func.count())
            .where(ActivityJob.scheduled_at >= lo, ActivityJob.scheduled_at < hi)
            .group_by(ActivityJob.kind, ActivityJob.status)
        )
    ).all()

    def bucket(kinds: set[ActivityKind]) -> KindCount:
        planned = sum(n for k, st, n in rows if k in kinds)
        done = sum(n for k, st, n in rows if k in kinds and st is JobStatus.SUCCEEDED)
        failed = sum(
            n for k, st, n in rows if k in kinds and st in (JobStatus.FAILED, JobStatus.NEEDS_HUMAN)
        )
        return KindCount(planned=planned, done=done, failed=failed)

    warming = int(
        (
            await s.execute(
                select(func.count())
                .select_from(Account)
                .where(Account.status == AccountStatus.WARMING)
            )
        ).scalar_one()
    )
    return ActivitySummary(
        date=day,
        likes=bucket({ActivityKind.ENGAGE, ActivityKind.REACT}),
        follows=bucket({ActivityKind.FOLLOW}),
        comments=bucket({ActivityKind.COMMENT}),
        accounts_warming=warming,
    )
