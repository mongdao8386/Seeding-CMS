"""Chia proxy cho tai khoan: mot proxy dung chung toi da ACCOUNTS_PER_PROXY acc.

Truoc 21/09/2026 luat la "mot acc mot proxy". Proxy dan cu dat, nen nguoi van hanh chon
dung chung: mac dinh 5 acc mot proxy (dat ACCOUNTS_PER_PROXY=1 de quay ve luat cu). Hai
thu giu cho viec dung chung bot lo:

  - Chia DEU: acc moi vao proxy dang IT NGUOI NHAT, khong don het vao proxy dau tien.
    20 proxy cho 40 acc la 2 acc moi proxy, khong phai 5-5-5-5 roi de trong 12 cai.
  - Worker khoa theo proxy (worker/tasks.py): hai acc chung mot IP khong bao gio hanh
    dong cung luc - cung luc moi la dau vet, lan luot thi giong mot nha dung chung mang.

Acc tuong tac cheo (booster) khong can proxy nen khong chiem cho.
"""

from __future__ import annotations

import heapq
import uuid

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from seeding.config import get_settings
from seeding.domain.models import Account, AccountRole, Profile, Proxy, ProxyStatus

log = structlog.get_logger(__name__)


def capacity() -> int:
    return max(1, int(get_settings().accounts_per_proxy))


async def loads(session: AsyncSession) -> dict[uuid.UUID, int]:
    """So profile dang gan tren moi proxy."""
    rows = await session.execute(
        select(Profile.proxy_id, func.count())
        .where(Profile.proxy_id.is_not(None))
        .group_by(Profile.proxy_id)
    )
    return {pid: int(n) for pid, n in rows.all()}


class ProxyPool:
    """Cac proxy con cho, lay ra theo thu tu it nguoi nhat truoc. Thuan tuy de test."""

    def __init__(self, proxies_with_load: list[tuple[Proxy, int]], cap: int):
        self.cap = max(1, cap)
        self.misses = 0
        self._heap: list[tuple[int, int, Proxy]] = [
            (load, order, proxy)
            for order, (proxy, load) in enumerate(proxies_with_load)
            if load < self.cap
        ]
        heapq.heapify(self._heap)

    def take(self) -> Proxy | None:
        """Proxy it nguoi nhat con cho; None khi moi proxy da day (dem vao `misses`)."""
        if not self._heap:
            self.misses += 1
            return None
        load, order, proxy = heapq.heappop(self._heap)
        load += 1
        if load < self.cap:
            heapq.heappush(self._heap, (load, order, proxy))
        return proxy

    @property
    def free_slots(self) -> int:
        return sum(self.cap - load for load, _, _ in self._heap)


async def build_pool(session: AsyncSession) -> ProxyPool:
    """Pool tu cac proxy da thu OK, kem tai hien tai cua tung cai."""
    counts = await loads(session)
    proxies = (
        (
            await session.execute(
                select(Proxy).where(Proxy.status == ProxyStatus.OK).order_by(Proxy.created_at)
            )
        )
        .unique()
        .scalars()
        .all()
    )
    return ProxyPool([(p, counts.get(p.id, 0)) for p in proxies], capacity())


async def attach_missing(session: AsyncSession) -> dict:
    """Gan proxy cho acc xay kenh con thieu: profile chua co proxy, va acc chua co profile
    (tao profile kem proxy de nguoi van hanh mo trinh duyet dang nhap duoc).

    Chay sau khi dan them proxy, hoac bam nut "Gan proxy cho acc con thieu". Acc da co
    proxy khong bi dung toi: mot acc o yen mot proxy.
    """
    from seeding.domain import profiles as profiles_mod

    pool = await build_pool(session)
    attached = 0

    bare = (
        (
            await session.execute(
                select(Profile)
                .join(Account, Account.id == Profile.account_id)
                .where(Profile.proxy_id.is_(None), Account.role != AccountRole.BOOSTER)
                .order_by(Profile.created_at)
            )
        )
        .unique()
        .scalars()
        .all()
    )
    missing = len(bare)
    for profile in bare:
        proxy = pool.take()
        if proxy is None:
            break
        profile.proxy_id = proxy.id
        profile.proxy = proxy
        attached += 1

    without_profile = (
        (
            await session.execute(
                select(Account)
                .outerjoin(Profile, Profile.account_id == Account.id)
                .where(Profile.id.is_(None), Account.role != AccountRole.BOOSTER)
                .order_by(Account.created_at)
            )
        )
        .unique()
        .scalars()
        .all()
    )
    missing += len(without_profile)
    for account in without_profile:
        proxy = pool.take()
        if proxy is None:
            break
        await profiles_mod.create_profile(session, account, proxy=proxy)
        attached += 1

    await session.commit()
    result = {
        "attached": attached,
        "still_missing": missing - attached,
        "free_slots": pool.free_slots,
        "capacity": pool.cap,
    }
    if missing:
        log.info("proxypool.attach_missing", **result)
    return result
