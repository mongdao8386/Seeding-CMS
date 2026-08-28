"""Hang doi can thiep tay.

Khi gap checkpoint, captcha hay yeu cau xac minh, he thong DUNG LAI va cho nguoi.
Khong retry - retry chi lam nang them. Khong tu dang nhap lai - do la cach nhanh
nhat de mat tai khoan.

Day la co che phan biet mot he thong chay duoc voi mot ban demo. Thieu no, moi lan
gap checkpoint la mat mot tai khoan.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from seeding.core import alerts
from seeding.core import profiles as profiles_mod
from seeding.models import (
    Account,
    AccountStatus,
    JobStatus,
    PostJob,
    SessionEventKind,
    TakeoverRequest,
    TakeoverStatus,
)

log = structlog.get_logger(__name__)

# Nghi bao lau sau khi giai checkpoint truoc khi thu lai job. Vua giai xong ma dang
# bai lien la dung cai nhip dang bi soi.
_COOL_OFF = timedelta(hours=6)


async def open_request(
    session: AsyncSession,
    account: Account,
    reason: str,
    *,
    post_job_id: uuid.UUID | None = None,
) -> TakeoverRequest:
    """Dua mot tai khoan vao hang doi cho nguoi.

    Neu da co yeu cau dang mo thi cap nhat ly do chu khong tao them - mot tai khoan
    hong theo mot kieu, nguoi van hanh khong can doc ba dong bao giong nhau.
    """
    existing = await open_for_account(session, account.id)
    if existing is not None:
        existing.reason = reason
        if post_job_id:
            existing.post_job_id = post_job_id
        await session.commit()
        return existing

    profile = await profiles_mod.get_for_account(session, account.id)
    request = TakeoverRequest(
        account_id=account.id,
        profile_id=profile.id if profile else None,
        reason=reason,
        post_job_id=post_job_id,
    )
    session.add(request)
    account.status = AccountStatus.NEEDS_HUMAN

    if profile is not None:
        profile.session_alive = False
        await profiles_mod.record_event(
            session, profile, SessionEventKind.CHECKPOINT, detail=reason, commit=False
        )

    await session.commit()
    log.warning("takeover.opened", handle=account.handle, reason=reason)

    # Bao ra ngoai MOT lan cho moi yeu cau. Cac lan open_request sau chi cap nhat ly do
    # (nhanh `existing` o tren) nen khong bao gio toi day lan hai.
    if alerts.configured():
        waiting = len(await list_open(session))
        if alerts.takeover_opened(account.handle, account.platform.value, reason, waiting):
            request.alerted_at = datetime.now(UTC)
            await session.commit()

    return request


async def open_for_account(session: AsyncSession, account_id: uuid.UUID) -> TakeoverRequest | None:
    stmt = select(TakeoverRequest).where(
        TakeoverRequest.account_id == account_id,
        TakeoverRequest.status == TakeoverStatus.OPEN,
    )
    return (await session.execute(stmt)).unique().scalar_one_or_none()


async def list_open(session: AsyncSession) -> list[TakeoverRequest]:
    stmt = (
        select(TakeoverRequest)
        .where(TakeoverRequest.status == TakeoverStatus.OPEN)
        .order_by(TakeoverRequest.created_at)
    )
    return list((await session.execute(stmt)).unique().scalars().all())


async def reconcile(session: AsyncSession) -> int:
    """Mo yeu cau cho nhung tai khoan ket ma bi bo quen.

    Mot tai khoan o NEEDS_HUMAN nhung khong co yeu cau nao dang mo la vo hinh: no nam
    ngoai hang doi tu dong, cung khong hien ra cho nguoi van hanh, va se nam do mai.

    Ham nay chay moi lan quet suc khoe. No ton tai vi mot duong code tung dat trang
    thai ma quen mo yeu cau; sua duong do roi van giu ham nay, vi mot he thong van hanh
    khong nen tin rang moi duong code deu nho lam du buoc.
    """
    stmt = (
        select(Account)
        .outerjoin(
            TakeoverRequest,
            (TakeoverRequest.account_id == Account.id)
            & (TakeoverRequest.status == TakeoverStatus.OPEN),
        )
        .where(Account.status == AccountStatus.NEEDS_HUMAN, TakeoverRequest.id.is_(None))
    )
    orphans = list((await session.execute(stmt)).unique().scalars().all())

    for account in orphans:
        await open_request(
            session, account, "found during reconciliation: stuck with no open request"
        )
        log.warning("takeover.reconciled", handle=account.handle)

    return len(orphans)


async def resolve(
    session: AsyncSession,
    request: TakeoverRequest,
    *,
    by: str,
    note: str | None = None,
    retry_job: bool = True,
) -> None:
    """Nguoi da giai xong. Tra tai khoan ve hang doi tu dong.

    Job bi ket lai duoc dat lai lich chu khong chay ngay: vua giai checkpoint xong ma
    dang bai lien la dung cai nhip dang bi soi.
    """
    request.status = TakeoverStatus.RESOLVED
    request.resolved_at = datetime.now(UTC)
    request.resolved_by = by
    request.note = note

    account = await session.get(Account, request.account_id)
    if account is not None and account.status == AccountStatus.NEEDS_HUMAN:
        # Ve WARMING chu khong ve ACTIVE: vua qua checkpoint thi di cham lai mot nhip.
        account.status = AccountStatus.WARMING

    if retry_job and request.post_job_id:
        job = await session.get(PostJob, request.post_job_id)
        if job is not None and job.status == JobStatus.NEEDS_HUMAN:
            job.status = JobStatus.SCHEDULED
            job.scheduled_at = datetime.now(UTC) + _COOL_OFF
            job.last_error = f"checkpoint cleared by {by}, rescheduled"

    profile = await profiles_mod.get_for_account(session, request.account_id)
    if profile is not None:
        await profiles_mod.record_event(
            session,
            profile,
            SessionEventKind.TAKEOVER,
            detail=f"resolved by {by}: {note or 'no note'}",
            commit=False,
        )

    await session.commit()
    log.info("takeover.resolved", request=str(request.id), by=by)


async def abandon(session: AsyncSession, request: TakeoverRequest, *, by: str, note: str) -> None:
    """Tai khoan khong cuu duoc nua."""
    request.status = TakeoverStatus.ABANDONED
    request.resolved_at = datetime.now(UTC)
    request.resolved_by = by
    request.note = note

    account = await session.get(Account, request.account_id)
    if account is not None:
        account.status = AccountStatus.DEAD

    await session.commit()
    log.warning("takeover.abandoned", request=str(request.id), by=by, note=note)
