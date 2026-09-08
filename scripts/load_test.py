"""Chay thu tai: N acc xay kenh + M acc clone GIA, do thoi gian lap lich, API, va don.

    python scripts/load_test.py            # 100 kenh + 1000 clone
    python scripts/load_test.py 50 300

Khong mo trinh duyet, khong ra mang: chi kiem phan DB / lap lich / dashboard - la thu
gay khi len nghin acc (N+1 query, thieu chi muc, trang tai cham). Acc gia co cookie gia
va handle bat dau bang "loadtest_"; cuoi script xoa het bang bulk-delete. Ket qua in ra
la con so de doi chieu voi HUONG-DAN muc "Chiu tai".
"""

from __future__ import annotations

import asyncio
import random
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import func, select

from seeding.config import get_settings
from seeding.db import SessionLocal, engine
from seeding.domain import fingerprint as fpm
from seeding.domain.defaults import ensure_defaults
from seeding.domain.models import (
    Account,
    AccountRole,
    AccountStatus,
    ActivityJob,
    Attempt,
    Campaign,
    CampaignGroup,
    ContentItem,
    JobStatus,
    Platform,
    PostJob,
    PostKind,
    Profile,
    Proxy,
    ProxyKind,
    ProxyStatus,
    Variant,
)

API = "http://127.0.0.1:8000"


def _cookie_state() -> dict:
    return {
        "cookies": [
            {"name": "sessionid", "value": uuid.uuid4().hex, "domain": ".tiktok.com", "path": "/"}
        ]
    }


async def seed(channels: int, boosters: int) -> None:
    async with SessionLocal() as s:
        ws, persona = await ensure_defaults(s)
        now = datetime.now(UTC)
        # Noi dung + chien dich de kenh co "bai da dang" cho clone day.
        item = ContentItem(workspace_id=ws.id, title_template="loadtest", body_template="x")
        s.add(item)
        await s.flush()
        variant = Variant(
            content_item_id=item.id, title="loadtest", body="x", content_hash=uuid.uuid4().hex
        )
        s.add(variant)
        campaign = Campaign(
            workspace_id=ws.id,
            content_item_id=item.id,
            name="loadtest",
            starts_at=now,
            stagger_window_seconds=0,
        )
        s.add(campaign)
        await s.flush()
        group = CampaignGroup(
            campaign_id=campaign.id,
            name="loadtest",
            platform=Platform.TIKTOK,
            post_kind=PostKind.POST,
            target={},
        )
        s.add(group)
        await s.flush()

        proxies = []
        for i in range(channels):
            p = Proxy(
                label=f"LT{i:03d}",
                kind=ProxyKind.RESIDENTIAL,
                scheme="http",
                host=f"10.0.{i // 250}.{i % 250 + 1}",
                port=8000 + i,
                status=ProxyStatus.OK,
            )
            s.add(p)
            proxies.append(p)
        await s.flush()

        for i in range(channels):
            acc = Account(
                persona_id=persona.id,
                platform=Platform.TIKTOK,
                handle=f"loadtest_kenh_{i:04d}",
                status=AccountStatus.ACTIVE,
                role=AccountRole.CHANNEL,
                warmup_started_at=now - timedelta(days=10),
            )
            s.add(acc)
            await s.flush()
            prof = Profile(
                account_id=acc.id,
                proxy_id=proxies[i].id,
                fingerprint=fpm.generate(),
                os_family="windows",
                locale="auto",
            )
            prof.set_cookies(_cookie_state())
            s.add(prof)
            job = PostJob(
                campaign_id=campaign.id,
                group_id=group.id,
                account_id=acc.id,
                variant_id=variant.id,
                idempotency_key=uuid.uuid4().hex,
                status=JobStatus.SUCCEEDED,
                scheduled_at=now - timedelta(days=1),
                target={},
            )
            s.add(job)
            await s.flush()
            s.add(
                Attempt(
                    job_id=job.id,
                    started_at=now - timedelta(days=1),
                    finished_at=now - timedelta(days=1),
                    ok=True,
                    remote_url=(
                        f"https://www.tiktok.com/@loadtest_kenh_{i:04d}/video/{7 * 10**18 + i}"
                    ),
                )
            )
        for i in range(boosters):
            acc = Account(
                persona_id=persona.id,
                platform=Platform.TIKTOK,
                handle=f"loadtest_clone_{i:05d}",
                status=AccountStatus.ACTIVE,
                role=AccountRole.BOOSTER,
                warmup_started_at=now - timedelta(days=10),
            )
            s.add(acc)
            await s.flush()
            prof = Profile(
                account_id=acc.id, fingerprint=fpm.generate(), os_family="windows", locale="auto"
            )
            prof.set_cookies(_cookie_state())
            s.add(prof)
            if i % 200 == 199:
                await s.commit()
        await s.commit()


async def timed(label: str, coro):
    t0 = time.perf_counter()
    out = await coro
    print(f"  {label:44} {time.perf_counter() - t0:7.2f}s  {out if out is not None else ''}")
    return out


async def main(channels: int, boosters: int) -> None:
    print(f"== nap {channels} kenh + {boosters} clone gia")
    await timed("nap du lieu", seed(channels, boosters))

    from seeding.platforms import base as adapters
    from seeding.platforms import boost
    from seeding.platforms.tiktok import sitting

    adapters.load_all()
    async with SessionLocal() as s:
        n = await timed("lap lich clone -> bai kenh (boost.plan_all)", boost.plan_all(s))
        m = await timed("lap lich phien luot kenh (sitting.plan_all)", sitting.plan_all(s))
        total = (await s.execute(select(func.count()).select_from(ActivityJob))).scalar_one()
        print(f"  job nuoi trong DB: {total} (boost {n}, sitting {m})")
        # Mot tick: 50 job toi han
        from seeding.worker import tasks

        class _R:
            async def enqueue_job(self, *a, **k):
                return None

        await timed("activity_tick (nhat 50 job toi han)", tasks.activity_tick({"redis": _R()}))
        due = await timed(
            "due_for_health_check (200 profile)",
            __import__("seeding.domain.profiles", fromlist=["x"]).due_for_health_check(
                s, 12, limit=200, booster_interval_hours=24
            ),
        )
        print(f"  profile toi han kiem: {len(due)}")

    headers = {"authorization": f"Bearer {get_settings().api_token}"}
    async with httpx.AsyncClient(base_url=API, headers=headers, timeout=120) as c:
        for path in (
            "/accounts?limit=50",
            "/accounts?limit=50&q=clone_009",
            "/accounts?limit=50&ready=true",
            "/activity/summary",
            "/takeovers",
            "/proxies?limit=50",
        ):
            t0 = time.perf_counter()
            r = await c.get(path)
            print(f"  GET {path:38} {r.status_code} {time.perf_counter() - t0:6.2f}s")
        first = (await c.get("/accounts?limit=1&q=loadtest_kenh_0000")).json()["items"]
        if first:
            aid = first[0]["id"]
            for path in (f"/accounts/{aid}", f"/accounts/{aid}/timeline"):
                t0 = time.perf_counter()
                r = await c.get(path)
                print(f"  GET {path[:38]:38} {r.status_code} {time.perf_counter() - t0:6.2f}s")

        print("== don")
        async with SessionLocal() as s:
            ids = (
                (await s.execute(select(Account.id).where(Account.handle.like("loadtest_%"))))
                .scalars()
                .all()
            )
        t0 = time.perf_counter()
        r = await c.post(
            "/accounts/bulk-delete", json={"ids": [str(i) for i in ids], "force": True}
        )
        took = time.perf_counter() - t0
        print(
            f"  bulk-delete {len(ids)} acc: {r.status_code} {r.json().get('deleted')} {took:.2f}s"
        )
    async with SessionLocal() as s:
        from sqlalchemy import delete

        items = (
            (
                await s.execute(
                    select(ContentItem.id).where(ContentItem.title_template == "loadtest")
                )
            )
            .scalars()
            .all()
        )
        # campaigns -> content_items khong cascade: xoa chien dich truoc.
        await s.execute(delete(Campaign).where(Campaign.content_item_id.in_(items)))
        await s.execute(delete(ContentItem).where(ContentItem.id.in_(items)))
        await s.execute(delete(Proxy).where(Proxy.label.like("LT%")))
        await s.commit()
    await engine.dispose()


if __name__ == "__main__":
    ch = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    bo = int(sys.argv[2]) if len(sys.argv) > 2 else 1000
    random.seed(1)
    asyncio.run(main(ch, bo))
