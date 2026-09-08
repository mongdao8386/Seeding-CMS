"""Bai da dang: ke hoach xoa/sua, runner tung nen tang (khong mang), va API liet ke / hen
xoa / hen sua / huy qua DB that tren mot tai khoan Instagram thu voi mot bai da len gia."""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace
from typing import ClassVar

import httpx
import pytest
from httpx import ASGITransport

from seeding.api.main import app
from seeding.config import get_settings
from seeding.db import SessionLocal
from seeding.domain import fingerprint as fpm
from seeding.domain.defaults import ensure_defaults
from seeding.domain.models import (
    Account,
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
from seeding.platforms import manage
from seeding.platforms.instagram import manage as ig_manage
from seeding.platforms.tiktok import manage as tt_manage
from seeding.platforms.tiktok.web import ActionResult as TTResult
from seeding.platforms.x import manage as x_manage

# ------------------------------------------------------------------ thuan tuy


def test_plan_round_trip_and_support_table():
    plan = manage.Plan("edit", "a1", "r1", "https://x/p/1", caption="mới")
    got = manage.decode(manage.encode(plan))
    assert got == plan and got.kind is ActivityKind.EDIT
    assert manage.decode("https://x.com/a/status/1") is None
    assert manage.decode('manage:{"action":"nope"}') is None
    assert manage.supported(ActivityKind.DELETE, Platform.TIKTOK) is None
    assert "TikTok" in manage.supported(ActivityKind.EDIT, Platform.TIKTOK)
    assert "trả phí" in manage.supported(ActivityKind.EDIT, Platform.X)
    assert manage.supported(ActivityKind.EDIT, Platform.INSTAGRAM) is None
    assert "Facebook" in manage.supported(ActivityKind.DELETE, Platform.FACEBOOK)


# ------------------------------------------------------------------ runner


class _NoSession:
    async def get(self, model, key):
        return None  # mark_done khong tim thay attempt: bo qua, khong loi


def _profile() -> Profile:
    p = Profile(id=uuid.uuid4(), proxy_id=uuid.uuid4(), fingerprint={})
    p.proxy = Proxy(host="proxy.example.com", port=8080, scheme="http")
    return p


def _job(plan: manage.Plan) -> ActivityJob:
    return ActivityJob(
        id=uuid.uuid4(), account_id=uuid.uuid4(), kind=plan.kind, target_url=manage.encode(plan)
    )


class _FakeTT:
    calls: ClassVar[list] = []
    answer: ClassVar[TTResult] = TTResult(True, "ok")

    def __init__(self, profile):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def delete_video(self, item_id):
        _FakeTT.calls.append(item_id)
        return _FakeTT.answer


async def test_tiktok_delete_and_refuse_edit():
    _FakeTT.calls.clear()
    r = await tt_manage.run(
        _NoSession(), _profile(), _job(manage.Plan("delete", "a", "777", "u")), web_factory=_FakeTT
    )
    assert r.ok and _FakeTT.calls == ["777"]
    r = await tt_manage.run(
        _NoSession(),
        _profile(),
        _job(manage.Plan("edit", "a", "777", "u", caption="x")),
        web_factory=_FakeTT,
    )
    assert not r.ok and "trình duyệt" in r.detail
    _FakeTT.answer = TTResult(False, "verify", needs_human=True)
    try:
        r = await tt_manage.run(
            _NoSession(),
            _profile(),
            _job(manage.Plan("delete", "a", "1", "u")),
            web_factory=_FakeTT,
        )
    finally:
        _FakeTT.answer = TTResult(True, "ok")
    assert not r.ok and r.checkpoint is not None


class _FakeAio:
    calls: ClassVar[list] = []

    async def media_delete(self, media_id):
        _FakeAio.calls.append(("delete", media_id))
        return True

    async def media_edit(self, media_id, caption):
        _FakeAio.calls.append(("edit", media_id, caption))
        return {}


class _FakeIG:
    def __init__(self, profile):
        self.client = _FakeAio()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None


async def test_instagram_delete_and_edit():
    _FakeAio.calls.clear()
    r = await ig_manage.run(
        _NoSession(),
        _profile(),
        _job(manage.Plan("delete", "a", "99", "u")),
        client_factory=_FakeIG,
    )
    assert r.ok
    r = await ig_manage.run(
        _NoSession(),
        _profile(),
        _job(manage.Plan("edit", "a", "99", "u", caption="chú thích mới")),
        client_factory=_FakeIG,
    )
    assert r.ok and "sửa" in r.detail
    assert _FakeAio.calls == [("delete", "99"), ("edit", "99", "chú thích mới")]


class _FakeTwikit:
    calls: ClassVar[list] = []
    raise_with: ClassVar[BaseException | None] = None

    async def delete_tweet(self, tweet_id):
        if _FakeTwikit.raise_with:
            raise _FakeTwikit.raise_with
        _FakeTwikit.calls.append(tweet_id)


class _FakeX:
    def __init__(self, profile):
        self.client = _FakeTwikit()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None


async def test_x_delete_and_library_trouble():
    from twikit import errors as xerr

    _FakeTwikit.calls.clear()
    r = await x_manage.run(
        _NoSession(), _profile(), _job(manage.Plan("delete", "a", "5", "u")), client_factory=_FakeX
    )
    assert r.ok and _FakeTwikit.calls == ["5"]
    r = await x_manage.run(
        _NoSession(),
        _profile(),
        _job(manage.Plan("edit", "a", "5", "u", caption="x")),
        client_factory=_FakeX,
    )
    assert not r.ok and "trả phí" in r.detail
    _FakeTwikit.raise_with = xerr.ClientTransactionError("ondemand")
    try:
        r = await x_manage.run(
            _NoSession(),
            _profile(),
            _job(manage.Plan("delete", "a", "6", "u")),
            client_factory=_FakeX,
        )
    finally:
        _FakeTwikit.raise_with = None
    assert not r.ok and r.retryable and r.checkpoint is None


# ------------------------------------------------------------------ API that


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
async def published_post(client):
    """Tai khoan Instagram thu san sang + mot bai len lich qua API + mot Attempt "da len"."""
    async with SessionLocal() as s:
        _, persona = await ensure_defaults(s)
        proxy = Proxy(
            label=f"thu-{uuid.uuid4().hex[:6]}",
            kind=ProxyKind.RESIDENTIAL,
            host="proxy.example.com",
            port=8080,
        )
        s.add(proxy)
        account = Account(
            persona_id=persona.id,
            platform=Platform.INSTAGRAM,
            handle=f"thu_{uuid.uuid4().hex[:8]}",
            status=AccountStatus.ACTIVE,
            warmup_started_at=dt.datetime.now(dt.UTC) - dt.timedelta(days=10),
        )
        s.add(account)
        await s.flush()
        profile = Profile(
            account_id=account.id,
            proxy_id=proxy.id,
            fingerprint=fpm.generate(),
            os_family="windows",
            locale="auto",
        )
        profile.set_cookies({"cookies": [{"name": "sessionid", "value": "1%3Ax"}]})
        s.add(profile)
        await s.commit()
        account_id, proxy_id = account.id, proxy.id

    created = (
        await client.post(
            "/content", json={"title": f"bài thử {uuid.uuid4().hex[:5]}", "body": "x"}
        )
    ).json()
    far = (dt.date.today() + dt.timedelta(days=25)).isoformat()
    r = await client.post(
        "/schedule",
        json={"content_id": created["id"], "account_ids": [str(account_id)], "start_date": far},
    )
    assert r.status_code == 200, r.text
    job_id = uuid.UUID(r.json()[0]["id"])
    async with SessionLocal() as s:
        job = await s.get(PostJob, job_id)
        job.status = JobStatus.SUCCEEDED
        attempt = Attempt(
            job_id=job_id,
            ok=True,
            remote_id="3355",
            remote_url="https://www.instagram.com/p/ABC/",
            finished_at=dt.datetime.now(dt.UTC),
        )
        s.add(attempt)
        await s.commit()
        attempt_id = attempt.id

    yield SimpleNamespace(account_id=account_id, attempt_id=attempt_id, content_id=created["id"])

    await client.delete(f"/content/{created['id']}?force=true")
    async with SessionLocal() as s:
        for model, key in ((Account, account_id), (Proxy, proxy_id)):
            obj = await s.get(model, key)
            if obj is not None:
                await s.delete(obj)
        await s.commit()


async def test_list_delete_edit_cancel(client, published_post):
    pp = published_post
    r = await client.get("/posts", params={"account_id": str(pp.account_id)})
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["attempt_id"] == str(pp.attempt_id)
    assert row["remote_url"] == "https://www.instagram.com/p/ABC/"
    assert row["can_delete"] is None and row["can_edit"] is None and row["pending"] is None

    r = await client.post(f"/posts/{pp.attempt_id}/edit", json={"caption": "   "})
    assert r.status_code == 422

    r = await client.post(f"/posts/{pp.attempt_id}/edit", json={"caption": "chú thích mới"})
    assert r.status_code == 200, r.text
    assert r.json()["pending"] == "edit"

    r = await client.post(f"/posts/{pp.attempt_id}/delete")
    assert r.status_code == 409, "dang co viec cho chay"

    async with SessionLocal() as s:
        jobs = (
            (
                await s.execute(
                    __import__("sqlalchemy")
                    .select(ActivityJob)
                    .where(
                        ActivityJob.account_id == pp.account_id,
                        ActivityJob.kind == ActivityKind.EDIT,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(jobs) == 1
        plan = manage.decode(jobs[0].target_url)
        assert plan.caption == "chú thích mới" and plan.remote_id == "3355"
        when = jobs[0].scheduled_at
        assert dt.timedelta(seconds=10) < when - dt.datetime.now(dt.UTC) < dt.timedelta(minutes=3)

    r = await client.post(f"/posts/{pp.attempt_id}/cancel")
    assert r.status_code == 200 and r.json()["pending"] is None

    r = await client.post(f"/posts/{pp.attempt_id}/delete")
    assert r.status_code == 200 and r.json()["pending"] == "delete"

    # mark_done tren attempt: bai da xoa thi khong hien nua, tru khi include_deleted
    async with SessionLocal() as s:
        jobs = (
            (
                await s.execute(
                    __import__("sqlalchemy")
                    .select(ActivityJob)
                    .where(
                        ActivityJob.account_id == pp.account_id,
                        ActivityJob.kind == ActivityKind.DELETE,
                    )
                )
            )
            .scalars()
            .all()
        )
        job = jobs[0]
        job.status = JobStatus.SUCCEEDED
        await manage.mark_done(s, job, manage.decode(job.target_url))
        await s.commit()
    r = await client.get("/posts", params={"account_id": str(pp.account_id)})
    assert r.json() == []
    r = await client.get(
        "/posts", params={"account_id": str(pp.account_id), "include_deleted": "true"}
    )
    assert len(r.json()) == 1 and r.json()[0]["deleted_at"]
    r = await client.post(f"/posts/{pp.attempt_id}/delete")
    assert r.status_code == 409 and "đã xoá" in r.json()["detail"]


async def test_unknown_post_is_404(client):
    r = await client.post(f"/posts/{uuid.uuid4()}/delete")
    assert r.status_code == 404
