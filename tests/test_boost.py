"""Hai loai tai khoan. Kiem: booster san sang khong can proxy; cot role khi dan; lich
tuong tac cheo (build_jobs thuan tuy: chua tha thi tha, tran moi bai, follow kenh chua
follow, binh luan sau tha tim); plan_all tren DB that voi mot kenh co bai da len va
hai booster thu (don sach sau); API loc theo role va doi role; booster khong len lich dang."""

from __future__ import annotations

import datetime as dt
import random
import uuid
from types import SimpleNamespace

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import select

from seeding.api.main import app
from seeding.config import get_settings
from seeding.db import SessionLocal
from seeding.domain import fingerprint as fpm
from seeding.domain import readiness
from seeding.domain.defaults import ensure_defaults
from seeding.domain.models import (
    Account,
    AccountRole,
    AccountStatus,
    ActivityJob,
    ActivityKind,
    Attempt,
    JobStatus,
    Platform,
    PostJob,
    Profile,
    Proxy,
    ProxyKind,
)
from seeding.ops import bulk
from seeding.platforms import boost

# ------------------------------------------------------------------ thuan tuy


def test_booster_is_ready_without_a_proxy_but_still_needs_a_session():
    p = Profile(proxy_id=None, cookies_enc="enc")
    channel = Account(handle="c", status=AccountStatus.WARMING, role=AccountRole.CHANNEL)
    booster = Account(handle="b", status=AccountStatus.WARMING, role=AccountRole.BOOSTER)
    assert not readiness.check(channel, p).ready and "proxy" in readiness.check(channel, p).reason
    assert readiness.check(booster, p).ready
    assert not readiness.check(booster, Profile(proxy_id=None, cookies_enc=None)).ready


def test_role_column_is_parsed_in_vietnamese_and_english():
    assert bulk.parse_role("booster") is AccountRole.BOOSTER
    assert bulk.parse_role("Tương tác chéo") is AccountRole.BOOSTER
    assert bulk.parse_role("xây kênh") is AccountRole.CHANNEL
    assert bulk.parse_role("") is AccountRole.CHANNEL
    assert bulk.parse_role("", AccountRole.BOOSTER) is AccountRole.BOOSTER
    report = bulk.parse(
        "platform|handle|role\ntiktok|a1|booster\ntiktok|a2|\n", default_role=AccountRole.CHANNEL
    )
    assert [r.role for r in report.rows] == [AccountRole.BOOSTER, AccountRole.CHANNEL]


def _post(i, channel_id, hours_ago=1):
    return boost.ChannelPost(
        url=f"https://www.tiktok.com/@ch/video/{i}",
        account_id=channel_id,
        handle="ch",
        posted_at=dt.datetime.now(dt.UTC) - dt.timedelta(hours=hours_ago),
    )


def test_build_jobs_respects_cap_history_and_ordering():
    ch = Account(id=uuid.uuid4(), handle="ch", role=AccountRole.CHANNEL)
    ch2 = Account(id=uuid.uuid4(), handle="ch2", role=AccountRole.CHANNEL)
    booster = Account(
        id=uuid.uuid4(),
        handle="b1",
        role=AccountRole.BOOSTER,
        warmup_started_at=dt.datetime.now(dt.UTC) - dt.timedelta(days=5),
    )
    posts = [_post(i, ch.id, hours_ago=i) for i in range(1, 8)]
    day = dt.datetime.now(dt.UTC).date()
    start = dt.datetime.combine(day, dt.time.min, tzinfo=dt.UTC) + dt.timedelta(hours=1)
    jobs = boost.build_jobs(
        booster,
        posts,
        [ch, ch2],
        liked_before={posts[0].url},  # da tha bai 1 hom qua
        followed_before={ch.id},  # da follow ch
        likes_today={posts[1].url: 99},  # bai 2 da du tran hom nay
        cap=30,
        budget=(3, 2, 1, 1),
        day=day,
        window=(start, start + dt.timedelta(hours=10)),
        rng=random.Random(1),
        profile_url=lambda h: f"https://www.tiktok.com/@{h}",
    )
    likes = [j for j in jobs if j.kind is ActivityKind.ENGAGE]
    assert len(likes) == 3
    assert all(j.target_url not in (posts[0].url, posts[1].url) for j in likes)
    assert all(j.target_account_id == ch.id for j in likes), (
        "canh noi bo: target_account_id la kenh"
    )
    assert all(30 <= j.duration_seconds <= 45 for j in likes)
    follows = [j for j in jobs if j.kind is ActivityKind.FOLLOW]
    assert [j.target_account_id for j in follows] == [ch2.id], "chi follow kenh chua follow"
    comments = [j for j in jobs if j.kind is ActivityKind.COMMENT]
    reposts = [j for j in jobs if j.kind is ActivityKind.REPOST]
    assert len(comments) == 1 and len(reposts) == 1
    liked_at = {j.target_url: j.scheduled_at for j in likes}
    assert comments[0].scheduled_at >= liked_at[comments[0].target_url] + boost.COMMENT_AFTER_LIKE
    assert reposts[0].target_url != comments[0].target_url


def test_day_zero_booster_only_likes_a_little():
    b = Account(id=uuid.uuid4(), handle="b", role=AccountRole.BOOSTER, warmup_started_at=None)
    likes, _follows, comments, reposts = boost.budget_for(
        b, dt.datetime.now(dt.UTC), random.Random(1)
    )
    assert 1 <= likes <= 2 and comments == 0 and reposts == 0


# ------------------------------------------------------------------ DB that


@pytest.fixture(scope="module")
async def client():
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"authorization": f"Bearer {get_settings().api_token}"},
        timeout=60,
    ) as c:
        yield c


@pytest.fixture
async def fleet(client):
    """Mot kenh Instagram co mot bai da len + hai booster (mot san sang khong proxy, mot chua
    dang nhap). Don sach sau."""
    tag = uuid.uuid4().hex[:6]
    async with SessionLocal() as s:
        _, persona = await ensure_defaults(s)
        proxy = Proxy(
            label=f"thu-{tag}", kind=ProxyKind.RESIDENTIAL, host="proxy.example.com", port=8080
        )
        s.add(proxy)
        channel = Account(
            persona_id=persona.id,
            platform=Platform.INSTAGRAM,
            handle=f"ch_{tag}",
            status=AccountStatus.ACTIVE,
            role=AccountRole.CHANNEL,
            warmup_started_at=dt.datetime.now(dt.UTC) - dt.timedelta(days=9),
        )
        b1 = Account(
            persona_id=persona.id,
            platform=Platform.INSTAGRAM,
            handle=f"b1_{tag}",
            status=AccountStatus.ACTIVE,
            role=AccountRole.BOOSTER,
            warmup_started_at=dt.datetime.now(dt.UTC) - dt.timedelta(days=3),
        )
        b2 = Account(
            persona_id=persona.id,
            platform=Platform.INSTAGRAM,
            handle=f"b2_{tag}",
            status=AccountStatus.ACTIVE,
            role=AccountRole.BOOSTER,
        )
        s.add_all([channel, b1, b2])
        await s.flush()
        pc = Profile(
            account_id=channel.id,
            proxy_id=proxy.id,
            fingerprint=fpm.generate(),
            os_family="windows",
            locale="auto",
        )
        pc.set_cookies({"cookies": [{"name": "sessionid", "value": "1%3Ax"}]})
        p1 = Profile(
            account_id=b1.id,
            proxy_id=None,
            fingerprint=fpm.generate(),
            os_family="windows",
            locale="auto",
        )
        p1.set_cookies({"cookies": [{"name": "sessionid", "value": "2%3Ax"}]})
        p2 = Profile(
            account_id=b2.id,
            proxy_id=None,
            fingerprint=fpm.generate(),
            os_family="windows",
            locale="auto",
        )
        s.add_all([pc, p1, p2])
        await s.commit()
        ids = SimpleNamespace(channel=channel.id, b1=b1.id, b2=b2.id, proxy=proxy.id)

    created = (await client.post("/content", json={"title": f"bài {tag}", "body": "x"})).json()
    far = (dt.date.today() + dt.timedelta(days=25)).isoformat()
    r = await client.post(
        "/schedule",
        json={"content_id": created["id"], "account_ids": [str(ids.channel)], "start_date": far},
    )
    assert r.status_code == 200, r.text
    job_id = uuid.UUID(r.json()[0]["id"])
    async with SessionLocal() as s:
        job = await s.get(PostJob, job_id)
        job.status = JobStatus.SUCCEEDED
        s.add(
            Attempt(
                job_id=job_id,
                ok=True,
                remote_id="1",
                remote_url=f"https://www.instagram.com/p/{tag}/",
                finished_at=dt.datetime.now(dt.UTC),
            )
        )
        await s.commit()
    ids.content = created["id"]
    yield ids
    await client.delete(f"/content/{created['id']}?force=true")
    async with SessionLocal() as s:
        for model, key in (
            (Account, ids.channel),
            (Account, ids.b1),
            (Account, ids.b2),
            (Proxy, ids.proxy),
        ):
            obj = await s.get(model, key)
            if obj is not None:
                await s.delete(obj)
        await s.commit()


async def test_plan_all_targets_channel_posts_from_ready_boosters_only(client, fleet):
    async with SessionLocal() as s:
        n = await boost.plan_all(s)
        assert n >= 2, "b1 phai co it nhat tha tim + follow"
        rows = list(
            (
                await s.execute(
                    select(ActivityJob).where(ActivityJob.account_id.in_([fleet.b1, fleet.b2]))
                )
            ).scalars()
        )
    assert rows and all(r.account_id == fleet.b1 for r in rows), (
        "b2 chua dang nhap thi khong co lich"
    )
    assert all(r.target_account_id == fleet.channel for r in rows)
    likes = [r for r in rows if r.kind is ActivityKind.ENGAGE]
    assert likes and likes[0].target_url.startswith("https://www.instagram.com/p/")
    follows = [r for r in rows if r.kind is ActivityKind.FOLLOW]
    assert (
        follows
        and follows[0].target_url
        == f"https://www.instagram.com/ch_{likes[0].target_url.rstrip('/').rsplit('/', 1)[-1]}/"
    )
    async with SessionLocal() as s:
        assert await boost.plan_all(s) == 0, "hom nay da co lich thi khong lap lai"


async def test_api_filters_by_role_and_refuses_to_schedule_a_booster(client, fleet):
    r = await client.get("/accounts", params={"role": "booster", "limit": 100})
    handles = {a["handle"] for a in r.json()["items"]}
    async with SessionLocal() as s:
        b1 = await s.get(Account, fleet.b1)
    assert b1.handle in handles and all(a["role"] == "booster" for a in r.json()["items"])
    row = next(a for a in r.json()["items"] if a["handle"] == b1.handle)
    assert row["ready"] is True and row["proxy_label"] is None, "booster san sang khong can proxy"

    r = await client.post(
        "/schedule", json={"content_id": fleet.content, "account_ids": [str(fleet.b1)]}
    )
    assert r.status_code == 422 and "tương tác chéo" in r.json()["detail"]

    r = await client.patch(f"/accounts/{fleet.b1}", json={"role": "channel"})
    assert r.status_code == 200 and r.json()["role"] == "channel"
    assert r.json()["ready"] is False, "thanh xay kenh thi lai can proxy"
    stats = (await client.get("/stats")).json()
    assert stats["channels"] + stats["boosters"] == stats["accounts"]
