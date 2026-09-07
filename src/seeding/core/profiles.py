"""Vong doi profile: tao, gan proxy, luu cookie, theo doi suc khoe phien.

Nguyen tac vong doi phien, ap dung xuyen suot:

    Dang nhap MOT LAN bang tay, giu phien mai mai.

Dang nhap la hanh dong rui ro nhat trong ca he thong. Khi phien chet, dung tu dong
dang nhap lai - day job sang cho nguoi xu ly. Tu dong dang nhap lai lap di lap lai
la cach nhanh nhat de mat tai khoan.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from seeding.core import fingerprint as fpm
from seeding.models import (
    Account,
    AccountStatus,
    BrowserEngine,
    Profile,
    Proxy,
    SessionEvent,
    SessionEventKind,
)

log = structlog.get_logger(__name__)


class ProfileError(RuntimeError):
    pass


async def create_profile(
    session: AsyncSession,
    account: Account,
    *,
    proxy: Proxy | None = None,
    engine: BrowserEngine = BrowserEngine.CAMOUFOX,
    os_family: str = "windows",
    locale: str = "auto",
) -> Profile:
    existing = await get_for_account(session, account.id)
    if existing is not None:
        raise ProfileError(
            f"{account.handle} already has a profile. Creating another would mint a new "
            "fingerprint, which is exactly the anomaly this system exists to avoid."
        )

    profile = Profile(
        account_id=account.id,
        # Gan ca quan he chu khong chi proxy_id: neu chi gan id thi doc profile.proxy
        # tren object vua tao se kich hoat lazy-load dong bo giua ngu canh async.
        proxy=proxy,
        engine=engine,
        os_family=os_family,
        locale=locale,
        fingerprint=fpm.generate(os_family=os_family),
    )
    session.add(profile)
    await session.flush()
    await record_event(
        session,
        profile,
        SessionEventKind.CREATED,
        detail=f"fingerprint: {fpm.summary(profile.fingerprint)}",
        commit=False,
    )
    await session.commit()

    log.info(
        "profile.created",
        handle=account.handle,
        engine=engine.value,
        fingerprint=fpm.summary(profile.fingerprint),
    )
    return profile


async def get_for_account(session: AsyncSession, account_id: uuid.UUID) -> Profile | None:
    stmt = select(Profile).where(Profile.account_id == account_id)
    return (await session.execute(stmt)).unique().scalar_one_or_none()


async def bind_proxy(
    session: AsyncSession,
    profile: Profile,
    proxy: Proxy,
    *,
    force: bool = False,
    reason: str | None = None,
) -> None:
    """Gan proxy. Doi proxy cua mot profile da gan la vi pham bat bien cua he thong.

    Xoay IP giua cac phien cua cung mot tai khoan gay hai nhieu hon la giu mot IP
    dan cu co dinh, ke ca khi IP do cham. Chi force khi proxy cu that su chet, va
    khi do phai ghi ly do de sau nay truy duoc.
    """
    if profile.proxy_id and profile.proxy_id != proxy.id and not force:
        raise ProfileError(
            "This profile is already bound to a different proxy. Rotating breaks the "
            "one-account-one-IP rule. If the old proxy is genuinely dead, call again with "
            "force=True and record why."
        )

    was = profile.proxy_id
    profile.proxy_id = proxy.id
    if was and was != proxy.id:
        await record_event(
            session,
            profile,
            SessionEventKind.TAKEOVER,
            detail=f"proxy changed {was} -> {proxy.id}: {reason or 'no reason given'}",
            commit=False,
        )
        log.warning("profile.proxy_rebound", profile=str(profile.id), reason=reason)
    await session.commit()


async def save_cookies(session: AsyncSession, profile: Profile, storage_state: dict) -> None:
    """Luu phien dang nhap. Day la thu quy nhat trong DB."""
    profile.set_cookies(storage_state)
    profile.session_alive = True
    profile.consecutive_health_failures = 0
    profile.last_login_at = datetime.now(UTC)
    n = len(storage_state.get("cookies", []))
    await record_event(
        session, profile, SessionEventKind.COOKIES_SAVED, detail=f"{n} cookies", commit=False
    )
    await session.commit()
    log.info("profile.cookies_saved", profile=str(profile.id), cookies=n)


async def mark_health(
    session: AsyncSession,
    profile: Profile,
    ok: bool,
    *,
    detail: str | None = None,
    threshold: int = 2,
) -> bool:
    """Ghi ket qua kiem tra phien. Tra ve True neu VUA vuot nguong can nguoi xu ly.

    Nguoi goi PHAI mo mot TakeoverRequest khi ham nay tra ve True. Khong tu mo o day
    vi takeover.py da import module nay - de tranh vong lap import. Truoc day buoc do
    bi bo sot, hau qua la tai khoan nam o NEEDS_HUMAN ma khong bao gio hien ra trong
    hang doi: nguoi van hanh khong bao gio biet de cuu.
    """
    profile.last_health_at = datetime.now(UTC)

    if ok:
        profile.session_alive = True
        profile.consecutive_health_failures = 0
        await record_event(session, profile, SessionEventKind.HEALTH_OK, detail, commit=False)
        await session.commit()
        return False

    profile.consecutive_health_failures += 1
    profile.session_alive = False
    await record_event(session, profile, SessionEventKind.HEALTH_FAIL, detail, commit=False)

    # Qua nguong thi khong thu lai nua - phien phai do nguoi khoi phuc.
    crossed = False
    if profile.consecutive_health_failures >= threshold:
        account = await session.get(Account, profile.account_id)
        if account and account.status != AccountStatus.NEEDS_HUMAN:
            account.status = AccountStatus.NEEDS_HUMAN
            crossed = True
            await record_event(
                session,
                profile,
                SessionEventKind.CHECKPOINT,
                detail=(
                    f"{profile.consecutive_health_failures} health checks failed in a row, "
                    "waiting for a person"
                ),
                commit=False,
            )
            log.warning(
                "profile.needs_human",
                profile=str(profile.id),
                failures=profile.consecutive_health_failures,
            )

    await session.commit()
    return crossed


async def record_event(
    session: AsyncSession,
    profile: Profile,
    kind: SessionEventKind,
    detail: str | None = None,
    *,
    commit: bool = True,
) -> None:
    session.add(SessionEvent(profile_id=profile.id, kind=kind, detail=detail))
    if commit:
        await session.commit()


async def due_for_health_check(
    session: AsyncSession, interval_hours: int, limit: int = 20
) -> list[Profile]:
    """Profile da co phien va da qua han kiem tra.

    Bo qua profile chua dang nhap lan nao va profile dang cho nguoi xu ly - kiem tra
    lai chung khong cho them thong tin gi ma van ton mot lan mo trinh duyet.
    """
    cutoff = datetime.now(UTC) - timedelta(hours=interval_hours)
    stmt = (
        select(Profile)
        .join(Account, Account.id == Profile.account_id)
        .where(
            Profile.cookies_enc.is_not(None),
            Account.status != AccountStatus.NEEDS_HUMAN,
            (Profile.last_health_at.is_(None)) | (Profile.last_health_at <= cutoff),
        )
        .order_by(Profile.last_health_at.nulls_first())
        .limit(limit)
    )
    return list((await session.execute(stmt)).unique().scalars().all())
