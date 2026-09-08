"""Mot tai khoan da san sang nhan viec chua, va neu chua thi thieu gi.

Cau hoi nay truoc day khong ai tra loi duoc o mot cho. Man hinh tao chien dich cho
chon MOI tai khoan, ke ca nhung cai chua co profile hay chua gan proxy - roi lap lich
xong, job chay, va that bai tung cai mot.

Truong hop te nhat khong phai la that bai. La profile CO nhung KHONG co proxy: luc do
trinh duyet van mo, van vao duoc trang, chi la di ra bang dia chi nha ban. Khong co loi
nao ca - va tat ca tai khoan chay nhu vay deu duoc nen tang nhin thay tren cung mot IP.

Nen module nay tra loi mot lan, o mot cho, va ca giao dien lan worker deu hoi no.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from seeding.domain.models import Account, AccountRole, AccountStatus, Platform, Profile

# Reddit di bang API: khong can profile, khong can proxy, khong can cookie.
API_PLATFORMS = frozenset({Platform.REDDIT})


@dataclass(slots=True)
class Readiness:
    ready: bool
    reason: str | None = None


def check(account: Account, profile: Profile | None) -> Readiness:
    """Tai khoan nay dang bai duoc chua?

    Thu tu kiem la thu tu nguoi van hanh phai sua: khong co profile thi gan proxy cung
    vo nghia, va co proxy ma chua dang nhap thi cung chua dang duoc.
    """
    if account.status is AccountStatus.DEAD:
        return Readiness(False, "the account is marked dead")
    if account.status is AccountStatus.SUSPENDED:
        return Readiness(False, "the account is suspended")
    if account.status is AccountStatus.NEEDS_HUMAN:
        return Readiness(False, "waiting for a person in the takeover queue")

    if account.platform in API_PLATFORMS:
        if not account.secrets_enc:
            return Readiness(False, "no API credentials saved")
        return Readiness(True)

    if profile is None:
        return Readiness(False, "no profile yet")
    if profile.proxy_id is None and account.role is not AccountRole.BOOSTER:
        # Day la cai bay: no KHONG lam job that bai. No lam job chay bang IP that.
        # Booster (tuong tac cheo) la ngoai le co chu y: nguoi van hanh chon khong proxy.
        return Readiness(False, "no proxy — it would go out on your own IP")
    if not profile.cookies_enc:
        return Readiness(False, "never signed in — import a cookie or run login_profile.py")

    return Readiness(True)


async def for_accounts(
    session: AsyncSession, account_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Readiness]:
    """Tra loi cho nhieu tai khoan trong MOT cau truy van.

    Hoi tung cai mot thi man hinh danh sach sinh ra mot truy van cho moi dong, va no
    cham dan ma khong ai de y cho toi luc co vai tram tai khoan.
    """
    if not account_ids:
        return {}

    rows = (
        (
            await session.execute(
                select(Account)
                .where(Account.id.in_(account_ids))
                .options(selectinload(Account.profile))
            )
        )
        .unique()
        .scalars()
        .all()
    )
    return {a.id: check(a, a.profile) for a in rows}
