"""Campaign planner: bung mot chien dich thanh ma tran job.

    Campaign x Group x Account  ->  1 PostJob, moi job mot Variant rieng.

Ham nay chay lai duoc bao nhieu lan cung cho ket qua giong nhau: idempotency_key
chan tao trung, con RNG co seed dam bao noi dung khong doi giua cac lan goi.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from seeding.core import hashtags
from seeding.core.spintax import content_hash, expand, rng_for
from seeding.models import (
    Campaign,
    CampaignGroup,
    ContentItem,
    HashtagSet,
    JobStatus,
    PostJob,
    Variant,
)


def idempotency_key(campaign_id, group_id, account_id) -> str:
    """Mot tai khoan chi dang dung mot lan cho moi group cua moi campaign.

    Co y khong dua variant_id vao khoa: neu dua, lap ke hoach lai voi variant moi
    se lach qua duoc rang buoc va sinh ra bai dang trung.
    """
    raw = f"{campaign_id}:{group_id}:{account_id}"
    return hashlib.sha256(raw.encode()).hexdigest()


async def plan_campaign(session: AsyncSession, campaign_id: uuid.UUID) -> list[PostJob]:
    campaign = (
        await session.execute(
            select(Campaign)
            .where(Campaign.id == campaign_id)
            .options(selectinload(Campaign.groups))
        )
    ).scalar_one()

    content = (
        await session.execute(select(ContentItem).where(ContentItem.id == campaign.content_item_id))
    ).scalar_one()

    if not content.approved:
        raise ValueError("This content has not been approved yet")

    existing = set(
        (
            await session.execute(
                select(PostJob.idempotency_key).where(PostJob.campaign_id == campaign_id)
            )
        )
        .scalars()
        .all()
    )

    # Tui hashtag cua workspace nay. Nap mot lan roi dung cho ca ma tran job.
    pools = {
        item.name.lower(): list(item.tags or [])
        for item in (
            await session.execute(
                select(HashtagSet).where(HashtagSet.workspace_id == campaign.workspace_id)
            )
        )
        .scalars()
        .all()
    }

    created: list[PostJob] = []
    for group in campaign.groups:
        for raw_account_id in group.account_ids:
            account_id = uuid.UUID(str(raw_account_id))
            key = idempotency_key(campaign.id, group.id, account_id)
            if key in existing:
                continue

            job = _build_job(campaign, group, content, account_id, key, pools)
            session.add(job)
            created.append(job)
            existing.add(key)

    await session.commit()
    return created


def _build_job(
    campaign: Campaign,
    group: CampaignGroup,
    content: ContentItem,
    account_id: uuid.UUID,
    key: str,
    pools: dict[str, list[str]],
) -> PostJob:
    rng = rng_for(campaign.id, group.id, account_id)

    # Spintax truoc, roi den hashtag - cung mot RNG, nen ca hai deu on dinh theo
    # (campaign, group, account) va lap ke hoach lai khong doi noi dung.
    title = hashtags.expand(expand(content.title_template, rng), pools, rng)
    body = hashtags.expand(expand(content.body_template, rng), pools, rng)
    variant = Variant(
        content_item_id=content.id,
        title=title,
        body=body,
        media_ref=content.media_ref,
        content_hash=content_hash(title, body),
    )

    # Stagger: khong bao gio dang cung mot giay. Cua so lay tu campaign.
    window = max(0, campaign.stagger_window_seconds)
    offset = rng.randrange(window + 1) if window else 0
    scheduled_at = campaign.starts_at + timedelta(seconds=offset)

    return PostJob(
        campaign_id=campaign.id,
        group_id=group.id,
        account_id=account_id,
        variant=variant,
        idempotency_key=key,
        status=JobStatus.SCHEDULED,
        scheduled_at=scheduled_at,
        # `kind` di kem target chu khong nam thanh cot rieng: no la mot phan cua chi
        # dan gui cho adapter ("lam gi voi cho nay"), va adapter la thu duy nhat doc no.
        target={**dict(group.target), "kind": group.post_kind.value},
    )


async def due_jobs(session: AsyncSession, now: datetime | None = None, limit: int = 50):
    """Job da toi gio va chua chay. Scheduler tick doc bang query nay."""
    now = now or datetime.now(UTC)
    stmt = (
        select(PostJob)
        .where(PostJob.status == JobStatus.SCHEDULED, PostJob.scheduled_at <= now)
        .order_by(PostJob.scheduled_at)
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())
