"""Xoa tai khoan tu dashboard: mot cai, nhieu cai, tat ca - va khong bi FK chan.

08/09/2026: nut xoa "khong hoat dong" - dashboard khong co nut, va API xoa mot acc co bai
dang cho thi Postgres tu choi (post_jobs -> accounts khong cascade)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import httpx
import pytest
from httpx import ASGITransport

from seeding.api.main import app
from seeding.config import get_settings
from seeding.db import SessionLocal
from seeding.domain.defaults import ensure_defaults
from seeding.domain.models import (
    Account,
    AccountStatus,
    Attempt,
    Campaign,
    CampaignGroup,
    ContentItem,
    JobStatus,
    Platform,
    PostJob,
    PostKind,
    Variant,
)


@pytest.fixture(scope="module")
async def client():
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"authorization": f"Bearer {get_settings().api_token}"},
        timeout=60,
    ) as c:
        yield c


async def _account(s, *, posted: bool = False, scheduled: bool = False) -> Account:
    """Tai khoan test; co the kem mot bai (da dang hoac dang cho) qua ca chuoi
    noi dung -> bien the -> chien dich -> nhom -> job, vi post_jobs khong cascade."""
    ws, persona = await ensure_defaults(s)
    account = Account(
        persona_id=persona.id,
        platform=Platform.TIKTOK,
        handle=f"thu_{uuid.uuid4().hex[:10]}",
        status=AccountStatus.WARMING,
    )
    s.add(account)
    await s.flush()
    if posted or scheduled:
        now = datetime.now(UTC)
        item = ContentItem(workspace_id=ws.id, title_template="thu", body_template="thu")
        s.add(item)
        await s.flush()
        variant = Variant(
            content_item_id=item.id, title="thu", body="thu", content_hash=uuid.uuid4().hex
        )
        s.add(variant)
        campaign = Campaign(
            workspace_id=ws.id,
            content_item_id=item.id,
            name="thu",
            starts_at=now,
            stagger_window_seconds=0,
        )
        s.add(campaign)
        await s.flush()
        group = CampaignGroup(
            campaign_id=campaign.id,
            name="thu",
            platform=Platform.TIKTOK,
            post_kind=PostKind.POST,
            target={},
            account_ids=[str(account.id)],
        )
        s.add(group)
        await s.flush()
        job = PostJob(
            campaign_id=campaign.id,
            group_id=group.id,
            account_id=account.id,
            variant_id=variant.id,
            idempotency_key=uuid.uuid4().hex,
            status=JobStatus.SUCCEEDED if posted else JobStatus.SCHEDULED,
            scheduled_at=now,
            target={},
        )
        s.add(job)
        await s.flush()
        if posted:
            s.add(
                Attempt(
                    job_id=job.id,
                    started_at=now,
                    finished_at=now,
                    ok=True,
                    remote_url="https://x/1",
                )
            )
    await s.commit()
    return account


async def _cleanup_content() -> None:
    """Noi dung / chien dich 'thu' tao cho bai gia khong cascade theo acc - don tay."""
    from sqlalchemy import delete, select

    async with SessionLocal() as s:
        ids = (
            await s.execute(select(ContentItem.id).where(ContentItem.title_template == "thu"))
        ).scalars().all()
        await s.execute(delete(Campaign).where(Campaign.content_item_id.in_(ids)))
        await s.execute(delete(ContentItem).where(ContentItem.id.in_(ids)))
        await s.commit()


async def _exists(account_id) -> bool:
    async with SessionLocal() as s:
        return await s.get(Account, account_id) is not None


async def test_deleting_an_account_with_a_scheduled_post_works(client):
    async with SessionLocal() as s:
        acc = await _account(s, scheduled=True)
    r = await client.delete(f"/accounts/{acc.id}")
    assert r.status_code == 200, r.text
    assert not await _exists(acc.id)
    await _cleanup_content()


async def test_posted_account_needs_force(client):
    async with SessionLocal() as s:
        acc = await _account(s, posted=True)
    r = await client.delete(f"/accounts/{acc.id}")
    assert r.status_code == 409
    assert await _exists(acc.id)
    r = await client.delete(f"/accounts/{acc.id}?force=true")
    assert r.status_code == 200
    assert not await _exists(acc.id)
    await _cleanup_content()


async def test_bulk_delete_selected_skips_posted_unless_forced(client):
    async with SessionLocal() as s:
        a = await _account(s)
        b = await _account(s, scheduled=True)
        c = await _account(s, posted=True)
    r = await client.post("/accounts/bulk-delete", json={"ids": [str(a.id), str(b.id), str(c.id)]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deleted"] == 2 and body["skipped"] == [c.handle]
    assert not await _exists(a.id) and not await _exists(b.id) and await _exists(c.id)

    r = await client.post("/accounts/bulk-delete", json={"ids": [str(c.id)], "force": True})
    assert r.json()["deleted"] == 1
    assert not await _exists(c.id)
    await _cleanup_content()


async def test_bulk_delete_all(client):
    async with SessionLocal() as s:
        a = await _account(s)
        b = await _account(s)
    r = await client.post("/accounts/bulk-delete", json={"all": True, "force": True})
    assert r.status_code == 200
    assert r.json()["deleted"] >= 2
    assert not await _exists(a.id) and not await _exists(b.id)
    r = await client.get("/accounts?limit=1")
    assert r.json()["total"] == 0


async def test_bulk_delete_nothing_selected(client):
    r = await client.post("/accounts/bulk-delete", json={})
    assert r.status_code == 200 and r.json()["deleted"] == 0
