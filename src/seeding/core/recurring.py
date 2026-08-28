"""Chien dich lap lai: moi ky sinh mot ban sao moi.

Cach lam la NHAN BAN chu khong phai dat lai lich chien dich cu. Dat lai lich thi lich
su bi ghi de - tuan nay dang duoc bao nhieu, tuan truoc hong o dau, khong con dau vet.
Nhan ban giu nguyen tung ky nhu mot chien dich doc lap, va `repeat_parent_id` noi ca
chuoi lai voi nhau.

Mot he qua co y nua: seed cua bien the la (campaign_id, group_id, account_id). Ban sao
co id moi, nen tuan sau moi tai khoan viet mot cau khac - dung thu can, vi dang y het
mot cau moi tuan la dau vet ro rang hon ca viec dang cung gio.

Ban goc la thu duy nhat mang `repeat`. Ban sao luon ve NONE, neu khong moi ban sao lai
tu de ra ban sao va lich se no theo cap so nhan.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from seeding.core.planner import plan_campaign
from seeding.models import Campaign, CampaignGroup, Repeat

log = structlog.get_logger(__name__)

_INTERVALS: dict[Repeat, timedelta] = {
    Repeat.DAILY: timedelta(days=1),
    Repeat.WEEKLY: timedelta(days=7),
}


def interval_for(repeat: Repeat) -> timedelta | None:
    return _INTERVALS.get(repeat)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def next_run(campaign: Campaign) -> datetime | None:
    """Moc ky ke tiep, hoac None neu chuoi da het han.

    Tinh tu `last_repeated_at` chu khong tu bay gio, de cac ky khong bi troi dan moi
    lan cron chay lech vai phut.
    """
    step = interval_for(campaign.repeat)
    if step is None:
        return None

    when = _aware(campaign.last_repeated_at or campaign.starts_at) + step
    if campaign.repeat_until is not None and when > _aware(campaign.repeat_until):
        return None
    return when


def due_boundary(campaign: Campaign, now: datetime) -> tuple[datetime, int] | None:
    """Ky GAN NHAT da toi han, kem so ky bi bo qua trai duong.

    Cac ky bi lo KHONG duoc bu. Worker chet mot tuan roi song lai ma bu du bay ky la
    bay chien dich cung den han mot luc - toan bo tai khoan dang lien tuc trong vai
    phut. Do dung la mau hinh ma ca he thong nay ton tai de tranh.

    Bo qua mot ngay seeding khong mat gi. Dang bu ca tuan trong mot buoi thi mat tai khoan.
    """
    step = interval_for(campaign.repeat)
    if step is None:
        return None

    when = next_run(campaign)
    if when is None or when > now:
        return None

    # Truot toi moc cuoi cung con <= now.
    skipped = 0
    while True:
        following = when + step
        if following > now:
            break
        if campaign.repeat_until is not None and following > _aware(campaign.repeat_until):
            break
        when = following
        skipped += 1

    return when, skipped


async def due(session: AsyncSession, now: datetime | None = None) -> list[Campaign]:
    """Chien dich goc da toi ky sinh ban sao."""
    now = now or datetime.now(UTC)
    stmt = (
        select(Campaign)
        .where(Campaign.repeat != Repeat.NONE, Campaign.repeat_parent_id.is_(None))
        .options(selectinload(Campaign.groups))
    )
    rows = (await session.execute(stmt)).unique().scalars().all()

    return [c for c in rows if due_boundary(c, now) is not None]


async def spawn(
    session: AsyncSession, campaign: Campaign, now: datetime | None = None
) -> tuple[Campaign, int] | None:
    """Tao ban sao cho ky da toi han va lap ke hoach job cho no.

    Tra ve (ban sao, so job), hoac None neu chua toi han / chuoi da het han.
    """
    now = now or datetime.now(UTC)
    boundary = due_boundary(campaign, now)
    if boundary is None:
        return None
    when, skipped = boundary

    groups = campaign.groups
    if not groups:
        # Khong co nhom thi ban sao rong. Van danh dau da qua ky, neu khong vong cron
        # sau se thu lai ngay lap tuc va lap mai.
        campaign.last_repeated_at = when
        await session.commit()
        log.warning("recurring.skipped", campaign=str(campaign.id), reason="no groups")
        return None

    if skipped:
        log.warning("recurring.periods_skipped", campaign=str(campaign.id), skipped=skipped)

    # Moc ky co the da troi qua (cron chay moi tieng, hoac worker vua song lai). Lay
    # gio hien tai lam diem bat dau de cua so rai van con tac dung - dat starts_at vao
    # qua khu thi moi job deu qua han ngay va ca nhom dang cung mot luc.
    clone = Campaign(
        workspace_id=campaign.workspace_id,
        content_item_id=campaign.content_item_id,
        name=f"{campaign.name} - {when.date().isoformat()}",
        starts_at=max(when, now),
        stagger_window_seconds=campaign.stagger_window_seconds,
        repeat=Repeat.NONE,
        repeat_parent_id=campaign.id,
    )
    session.add(clone)
    await session.flush()

    for group in groups:
        session.add(
            CampaignGroup(
                campaign_id=clone.id,
                name=group.name,
                platform=group.platform,
                post_kind=group.post_kind,
                target=dict(group.target),
                account_ids=list(group.account_ids),
            )
        )

    campaign.last_repeated_at = when
    await session.commit()

    jobs = await plan_campaign(session, clone.id)
    log.info("recurring.spawned", parent=str(campaign.id), clone=str(clone.id), jobs=len(jobs))
    return clone, len(jobs)


async def run_due(session: AsyncSession, now: datetime | None = None) -> int:
    """Sinh moi ky da toi han. Tra ve so job da tao.

    Mot chien dich hong khong duoc chan cac chien dich con lai: noi dung chua duyet la
    loi thuong gap va no chi anh huong chuoi do.
    """
    now = now or datetime.now(UTC)
    total = 0
    for campaign in await due(session, now):
        try:
            result = await spawn(session, campaign, now)
        except Exception as exc:
            await session.rollback()
            log.warning(
                "recurring.failed",
                campaign=str(campaign.id),
                error=f"{type(exc).__name__}: {exc}",
            )
            continue
        if result is not None:
            total += result[1]
    return total


async def chain(session: AsyncSession, campaign_id: uuid.UUID) -> list[Campaign]:
    """Ban goc cung moi ban sao cua no, theo thu tu thoi gian."""
    campaign = (
        await session.execute(select(Campaign).where(Campaign.id == campaign_id))
    ).scalar_one()
    root_id = campaign.repeat_parent_id or campaign.id
    stmt = (
        select(Campaign)
        .where((Campaign.id == root_id) | (Campaign.repeat_parent_id == root_id))
        .order_by(Campaign.starts_at)
    )
    return list((await session.execute(stmt)).unique().scalars().all())
