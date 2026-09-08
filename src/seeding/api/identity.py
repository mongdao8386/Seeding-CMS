"""Doi danh tinh (ten, username, anh dai dien) cua mot tai khoan - theo yeu cau tu
dashboard, chay bang worker nhu mot viec nuoi, hien trong dong thoi gian."""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from seeding.api.deps import get_session
from seeding.api.schemas import IdentityIn, IdentityJobOut, IdentityOut, IdentitySuggestions
from seeding.content import identity
from seeding.domain import profiles as profiles_mod
from seeding.domain import readiness
from seeding.domain.models import (
    Account,
    ActivityJob,
    ActivityKind,
    JobStatus,
    MediaAsset,
    MediaKind,
)

router = APIRouter(prefix="/accounts", tags=["identity"])

_PENDING = (JobStatus.SCHEDULED, JobStatus.RUNNING, JobStatus.PENDING)


async def _jobs(s: AsyncSession, account_id: uuid.UUID) -> list[ActivityJob]:
    stmt = (
        select(ActivityJob)
        .where(ActivityJob.account_id == account_id, ActivityJob.kind == ActivityKind.IDENTITY)
        .order_by(ActivityJob.scheduled_at.desc())
        .limit(20)
    )
    return list((await s.execute(stmt)).unique().scalars().all())


def _last_username_change(jobs: list[ActivityJob]) -> datetime | None:
    for j in jobs:
        if j.status is JobStatus.SUCCEEDED and identity.plan_from_target(j.target_url).get(
            "username"
        ):
            return j.scheduled_at
    return None


async def _out(s: AsyncSession, account: Account) -> IdentityOut:
    jobs = await _jobs(s, account.id)
    pending = next((j for j in jobs if j.status in _PENDING), None)
    last = _last_username_change(jobs)
    min_days = identity.MIN_DAYS.get(account.platform, 0)
    next_allowed = last + timedelta(days=min_days) if last and min_days else None
    supported = account.platform in identity.SUPPORTED
    seed = f"{account.id}:{datetime.now(UTC).date().isoformat()}"
    names = identity.suggest_names(seed)
    return IdentityOut(
        handle=account.handle,
        platform=account.platform,
        supported=supported,
        why_not=None
        if supported
        else (
            "TikTok chưa có đường đổi tự động — bấm Mở trình duyệt, vào Sửa hồ sơ."
            if account.platform.value == "tiktok"
            else f"{account.platform.value} chưa hỗ trợ"
        ),
        min_days=min_days,
        last_username_change_at=last,
        next_username_change_at=next_allowed,
        pending=IdentityJobOut(
            id=pending.id,
            scheduled_at=pending.scheduled_at,
            status=pending.status,
            plan=identity.describe(identity.plan_from_target(pending.target_url)),
        )
        if pending
        else None,
        suggestions=IdentitySuggestions(
            names=names,
            usernames=identity.suggest_usernames(seed, account.platform, from_name=names[0])
            + identity.suggest_usernames(seed + ":b", account.platform, n=2),
        ),
    )


@router.get("/{account_id}/identity", response_model=IdentityOut)
async def get_identity(account_id: uuid.UUID, s: AsyncSession = Depends(get_session)):
    account = await s.get(Account, account_id)
    if account is None:
        raise HTTPException(404, "Không có tài khoản này")
    return await _out(s, account)


@router.post("/{account_id}/identity", response_model=IdentityOut)
async def schedule_identity(
    account_id: uuid.UUID, body: IdentityIn, s: AsyncSession = Depends(get_session)
):
    """Hen mot lan doi trong vai phut toi. Worker lam, ket qua hien o dong thoi gian."""
    account = await s.get(Account, account_id)
    if account is None:
        raise HTTPException(404, "Không có tài khoản này")
    if account.platform not in identity.SUPPORTED:
        raise HTTPException(409, (await _out(s, account)).why_not or "chưa hỗ trợ")

    plan: dict = {}
    if body.username:
        username = body.username.strip().lstrip("@").lower()
        if err := identity.validate_username(account.platform, username):
            raise HTTPException(422, err.capitalize())
        if username == account.handle.lstrip("@").lower():
            raise HTTPException(422, "Username này đang dùng rồi")
        plan["username"] = username
    if body.display_name:
        name = body.display_name.strip()
        if len(name) > 50:
            raise HTTPException(422, "Tên hiển thị tối đa 50 ký tự")
        plan["display_name"] = name
    if body.avatar_media_id:
        asset = await s.get(MediaAsset, body.avatar_media_id)
        if asset is None or asset.kind is not MediaKind.IMAGE:
            raise HTTPException(422, "Ảnh đại diện phải là một ảnh trong thư viện")
        plan["avatar"] = asset.filename
    if not plan:
        raise HTTPException(422, "Chưa chọn gì để đổi")

    jobs = await _jobs(s, account.id)
    if any(j.status in _PENDING for j in jobs):
        raise HTTPException(409, "Đang có một lần đổi chờ chạy — huỷ nó trước")
    if "username" in plan:
        last = _last_username_change(jobs)
        min_days = identity.MIN_DAYS.get(account.platform, 0)
        if last and min_days and datetime.now(UTC) < last + timedelta(days=min_days):
            allowed = (last + timedelta(days=min_days)).astimezone().strftime("%d/%m %H:%M")
            raise HTTPException(
                409, f"Username mới đổi gần đây; {account.platform.value} cho đổi lại từ {allowed}"
            )

    profile = await profiles_mod.get_for_account(s, account.id)
    verdict = readiness.check(account, profile)
    if not verdict.ready:
        raise HTTPException(409, f"{account.handle}: {verdict.reason}")

    # Vai phut toi, khong phai ngay lap tuc: bam nut roi doi ngay la nhip cua may.
    when = datetime.now(UTC) + timedelta(seconds=random.randint(60, 300))
    s.add(
        ActivityJob(
            account_id=account.id,
            kind=ActivityKind.IDENTITY,
            status=JobStatus.SCHEDULED,
            scheduled_at=when,
            duration_seconds=60,
            target_url=identity.plan_to_target(plan),
        )
    )
    await s.commit()
    return await _out(s, account)


@router.delete("/{account_id}/identity", response_model=IdentityOut)
async def cancel_identity(account_id: uuid.UUID, s: AsyncSession = Depends(get_session)):
    account = await s.get(Account, account_id)
    if account is None:
        raise HTTPException(404, "Không có tài khoản này")
    for j in await _jobs(s, account.id):
        if j.status is JobStatus.SCHEDULED:
            j.status = JobStatus.SKIPPED
            j.last_error = "huỷ từ dashboard"
    await s.commit()
    return await _out(s, account)
