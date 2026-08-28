"""Rate governor.

Giai doan 01 chi can tang dau tien: tran so bai moi tai khoan trong 24h, co ramp
warm-up. Giai doan 03 se them hai tang nua (theo proxy/IP va theo app credential)
va job chi chay khi lay duoc token o ca ba tang.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from seeding.models import Account, Attempt, PostJob


def effective_daily_cap(account: Account, now: datetime, warmup_days: int) -> int:
    """Tai khoan moi bat dau o 1 bai/ngay, tang tuyen tinh len daily_cap qua warmup_days.

    Tran nam trong DB chu khong hardcode - ban se chinh no lien tuc.
    """
    if account.warmup_started_at is None:
        return 1

    days_in = (now - account.warmup_started_at).days
    if days_in >= warmup_days:
        return account.daily_cap

    progress = max(0, days_in) / max(1, warmup_days)
    return max(1, round(1 + progress * (account.daily_cap - 1)))


async def posts_last_24h(session: AsyncSession, account_id, now: datetime) -> int:
    since = now - timedelta(hours=24)
    stmt = (
        select(func.count())
        .select_from(Attempt)
        .join(PostJob, PostJob.id == Attempt.job_id)
        .where(
            PostJob.account_id == account_id,
            Attempt.ok.is_(True),
            Attempt.started_at >= since,
        )
    )
    return int((await session.execute(stmt)).scalar_one())


async def check(
    session: AsyncSession, account: Account, warmup_days: int, now: datetime | None = None
) -> tuple[bool, str]:
    """Tra ve (duoc phep chay, ly do neu bi chan)."""
    now = now or datetime.now(UTC)

    if account.status.value in {"suspended", "dead", "needs_human"}:
        return False, f"account status is {account.status.value}"

    cap = effective_daily_cap(account, now, warmup_days)
    used = await posts_last_24h(session, account.id, now)
    if used >= cap:
        return False, f"daily cap reached: {used}/{cap} posts in 24h"

    return True, ""
