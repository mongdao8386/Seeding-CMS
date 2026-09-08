"""Con so cho Tong quan va tinh trang cac tien trinh."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from seeding.api.deps import get_session
from seeding.api.schemas import StatsOut, SystemOut
from seeding.config import get_settings
from seeding.domain import readiness
from seeding.domain.models import Account, AccountStatus, Profile, Proxy
from seeding.ops import flags

router = APIRouter(tags=["system"])


@router.get("/stats", response_model=StatsOut)
async def stats(s: AsyncSession = Depends(get_session)) -> StatsOut:
    accounts = list(
        (
            await s.execute(
                select(Account).options(selectinload(Account.profile).selectinload(Profile.proxy))
            )
        )
        .unique()
        .scalars()
    )
    verdicts = {a.id: readiness.check(a, a.profile) for a in accounts}
    live = [a for a in accounts if a.status is not AccountStatus.DEAD]

    proxies = int((await s.execute(select(func.count()).select_from(Proxy))).scalar_one())
    bound = int(
        (
            await s.execute(
                select(func.count()).select_from(Profile).where(Profile.proxy_id.is_not(None))
            )
        ).scalar_one()
    )
    return StatsOut(
        accounts=len(accounts),
        ready=sum(1 for a in live if verdicts[a.id].ready),
        blocked=sum(1 for a in live if not verdicts[a.id].ready),
        dead=sum(1 for a in accounts if a.status is AccountStatus.DEAD),
        needs_human=sum(1 for a in accounts if a.status is AccountStatus.NEEDS_HUMAN),
        warming=sum(1 for a in accounts if a.status is AccountStatus.WARMING),
        proxies=proxies,
        proxies_free=max(0, proxies - bound),
    )


@router.get("/system", response_model=SystemOut)
async def system(s: AsyncSession = Depends(get_session)) -> SystemOut:
    """API con song la tat nhien (dang tra loi). DB va signer thi hoi that."""
    db_ok = True
    try:
        await s.execute(text("select 1"))
    except Exception:
        db_ok = False

    signer_ok, detail = False, None
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            r = await c.get(f"{get_settings().signer_url}/health")
            body = r.json()
            signer_ok = bool(body.get("ready"))
            detail = (
                "sẵn sàng"
                if signer_ok
                else "đang khởi động"
                if body.get("initializing")
                else "chưa sẵn sàng"
            )
    except Exception:
        detail = "không chạy"

    x_lib = await flags.get_flag("library:x")
    return SystemOut(
        api=True,
        database=db_ok,
        signer=signer_ok,
        signer_detail=detail,
        x_library=None if x_lib is None else bool(x_lib.get("ok")),
        x_library_detail=None if x_lib is None else x_lib.get("detail"),
    )
