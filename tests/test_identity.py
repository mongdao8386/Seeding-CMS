"""Doi danh tinh: goi y ten / username theo luat tung nen tang, ban anh dai dien rieng,
runner Instagram va X goi dung viec (khong mang), va API hen / huy / tu choi qua DB that
tren tai khoan thu (don sach sau khi xong)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import ClassVar

import httpx
import pytest
from httpx import ASGITransport
from PIL import Image
from twikit import errors as xerr

from seeding.api.main import app
from seeding.config import get_settings
from seeding.content import identity
from seeding.db import SessionLocal
from seeding.domain import fingerprint as fpm
from seeding.domain.defaults import ensure_defaults
from seeding.domain.models import (
    Account,
    AccountStatus,
    ActivityJob,
    ActivityKind,
    JobStatus,
    Platform,
    Profile,
    Proxy,
    ProxyKind,
)
from seeding.platforms.instagram import identity as ig_identity
from seeding.platforms.x import identity as x_identity

# ------------------------------------------------------------------ thuan tuy


def test_strip_accents():
    assert identity.strip_accents("Ngọc Trâm") == "ngoc tram"
    assert identity.strip_accents("Đặng Văn Đạt") == "dang van dat"


def test_suggestions_are_deterministic_and_valid_per_platform():
    assert identity.suggest_names("s1") == identity.suggest_names("s1")
    assert len(set(identity.suggest_names("s1", 3))) == 3
    for platform in (Platform.TIKTOK, Platform.INSTAGRAM, Platform.X):
        got = identity.suggest_usernames("s1", platform, n=4)
        assert got == identity.suggest_usernames("s1", platform, n=4)
        assert len(got) == 4
        for u in got:
            assert identity.validate_username(platform, u) is None, (platform, u)
    assert all("." not in u for u in identity.suggest_usernames("s2", Platform.X, n=5))
    assert identity.suggest_usernames("s3", Platform.INSTAGRAM, from_name="Ngọc Trâm")[
        0
    ].startswith(("ngoctram", "ngoc_tram")) or any(
        "tram" in u
        for u in identity.suggest_usernames("s3", Platform.INSTAGRAM, from_name="Ngọc Trâm")
    )


@pytest.mark.parametrize(
    "platform, username, ok",
    [
        (Platform.X, "abc", False),  # qua ngan
        (Platform.X, "abcd", True),
        (Platform.X, "a.b.c.d", False),  # X khong cho dau cham
        (Platform.INSTAGRAM, "ngoc.tram_99", True),
        (Platform.INSTAGRAM, "ngoc.tram.", False),
        (Platform.INSTAGRAM, "Ngoc", False),  # phai viet thuong
        (Platform.TIKTOK, "a" * 25, False),
        (Platform.TIKTOK, "@ok_name", True),  # @ duoc bo qua
    ],
)
def test_validate_username(platform, username, ok):
    assert (identity.validate_username(platform, username) is None) is ok


def test_plan_round_trip_and_description():
    target = identity.plan_to_target({"username": "x1", "display_name": "", "avatar": "a.jpg"})
    assert target.startswith("identity:")
    plan = identity.plan_from_target(target)
    assert plan == {"avatar": "a.jpg", "username": "x1"}
    assert "@x1" in identity.describe(plan) and "ảnh" in identity.describe(plan)
    assert identity.plan_from_target("https://x.com/a/status/1") == {}
    assert identity.plan_from_target(None) == {}


def _png(path: Path, size=(900, 600)) -> Path:
    im = Image.new("RGB", size)
    px = im.load()
    for x in range(size[0]):
        for y in range(0, size[1], 3):
            px[x, y] = (x % 256, y % 256, (x * y) % 256)
    im.save(path, "PNG")
    return path


def test_avatar_variant_is_square_and_seeded(tmp_path):
    src = _png(tmp_path / "src.png")
    a = identity.avatar_variant(src, tmp_path / "a.jpg", "seed-a")
    b = identity.avatar_variant(src, tmp_path / "b.jpg", "seed-a")
    c = identity.avatar_variant(src, tmp_path / "c.jpg", "seed-c")
    with Image.open(a) as im:
        assert im.size == (640, 640) and im.format == "JPEG"
    assert a.read_bytes() == b.read_bytes(), "cung seed phai ra cung anh"
    assert a.read_bytes() != c.read_bytes(), "khac seed phai ra anh khac"


# ------------------------------------------------------------------ runner


class _NoSession:
    async def get(self, model, key):
        raise AssertionError("session.get duoc goi")


def _profile() -> Profile:
    p = Profile(id=uuid.uuid4(), proxy_id=uuid.uuid4(), fingerprint={})
    p.proxy = Proxy(host="proxy.example.com", port=8080, scheme="http")
    return p


def _job(plan: dict) -> ActivityJob:
    job = ActivityJob(
        id=uuid.uuid4(),
        account_id=uuid.uuid4(),
        kind=ActivityKind.IDENTITY,
        target_url=identity.plan_to_target(plan),
    )
    job.account = Account(handle="old_name", platform=Platform.INSTAGRAM)
    return job


class _FakeIG:
    calls: ClassVar[list] = []
    raise_with: ClassVar[BaseException | None] = None

    def __init__(self, profile):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def change_picture(self, path):
        _FakeIG.calls.append(("picture", Path(path).name))

    async def edit_profile(self, **fields):
        if _FakeIG.raise_with:
            raise _FakeIG.raise_with
        _FakeIG.calls.append(("edit", fields))


@pytest.fixture
def media_dirs(tmp_path, monkeypatch):
    from seeding.content import mediastore

    src = _png(tmp_path / "face.png")
    monkeypatch.setattr(mediastore, "resolve_source", lambda ref: src)
    monkeypatch.setattr(mediastore, "variants_dir", lambda: tmp_path / "variants")
    return src


async def test_instagram_runner_changes_everything_and_updates_handle(media_dirs):
    _FakeIG.calls.clear()
    job = _job({"username": "new_name", "display_name": "Ngọc Trâm", "avatar": "face.png"})
    r = await ig_identity.run(_NoSession(), _profile(), job, client_factory=_FakeIG)
    assert r.ok, r.detail
    assert _FakeIG.calls[0][0] == "picture" and _FakeIG.calls[0][1].startswith("avatar-")
    assert _FakeIG.calls[1] == ("edit", {"username": "new_name", "full_name": "Ngọc Trâm"})
    assert job.account.handle == "new_name"
    assert "@new_name" in r.detail and "ảnh" in r.detail


async def test_instagram_runner_reports_partial_progress_on_failure(media_dirs):
    from aiograpi import exceptions as igerr

    _FakeIG.calls.clear()
    _FakeIG.raise_with = igerr.ChallengeRequired("verify")
    try:
        job = _job({"username": "new_name", "avatar": "face.png"})
        r = await ig_identity.run(_NoSession(), _profile(), job, client_factory=_FakeIG)
    finally:
        _FakeIG.raise_with = None
    assert not r.ok and r.checkpoint is not None and "đã xong" in r.detail
    assert job.account.handle == "old_name", "khong doi handle khi username chua doi"


class _FakeX:
    calls: ClassVar[list] = []
    raise_with: ClassVar[BaseException | None] = None

    def __init__(self, profile):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def change_picture(self, path):
        _FakeX.calls.append(("picture", Path(path).name))

    async def edit_profile(self, *, name=None):
        _FakeX.calls.append(("name", name))

    async def change_username(self, username):
        if _FakeX.raise_with:
            raise _FakeX.raise_with
        _FakeX.calls.append(("username", username))


async def test_x_runner_order_and_library_trouble(media_dirs):
    _FakeX.calls.clear()
    job = _job({"username": "new_x", "display_name": "Minh Anh", "avatar": "face.png"})
    r = await x_identity.run(_NoSession(), _profile(), job, client_factory=_FakeX)
    assert r.ok and [c[0] for c in _FakeX.calls] == ["picture", "name", "username"]
    assert job.account.handle == "new_x"

    _FakeX.raise_with = xerr.ClientTransactionError("ondemand")
    try:
        job = _job({"username": "again"})
        r = await x_identity.run(_NoSession(), _profile(), job, client_factory=_FakeX)
    finally:
        _FakeX.raise_with = None
    assert not r.ok and r.retryable and r.checkpoint is None


async def test_runner_refuses_empty_plan_and_missing_proxy():
    job = _job({})
    r = await ig_identity.run(_NoSession(), _profile(), job, client_factory=_FakeIG)
    assert not r.ok and "no plan" in r.detail
    p = Profile(id=uuid.uuid4(), proxy_id=None, fingerprint={})
    p.proxy = None
    r = await ig_identity.run(_NoSession(), p, _job({"username": "x"}), client_factory=_FakeIG)
    assert not r.ok and "proxy" in r.detail


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
async def ig_account():
    """Tai khoan Instagram thu, san sang (profile + proxy thu + cookie), don sach sau."""
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
            status=AccountStatus.WARMING,
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
        ids = (account.id, proxy.id)

    yield ids[0]

    async with SessionLocal() as s:
        for model, key in ((Account, ids[0]), (Proxy, ids[1])):
            obj = await s.get(model, key)
            if obj is not None:
                await s.delete(obj)
        await s.commit()


async def test_identity_schedule_then_cancel(client, ig_account):
    r = await client.get(f"/accounts/{ig_account}/identity")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["supported"] and body["pending"] is None
    assert len(body["suggestions"]["usernames"]) >= 3 and len(body["suggestions"]["names"]) == 3

    r = await client.post(f"/accounts/{ig_account}/identity", json={"username": "Bad Name!"})
    assert r.status_code == 422
    r = await client.post(f"/accounts/{ig_account}/identity", json={})
    assert r.status_code == 422

    r = await client.post(
        f"/accounts/{ig_account}/identity",
        json={"username": body["suggestions"]["usernames"][0], "display_name": "Ngọc Trâm"},
    )
    assert r.status_code == 200, r.text
    pending = r.json()["pending"]
    assert pending and pending["status"] == "scheduled" and "@" in pending["plan"]
    when = datetime.fromisoformat(pending["scheduled_at"])
    assert timedelta(seconds=30) < when - datetime.now(UTC) < timedelta(minutes=6)

    r = await client.post(f"/accounts/{ig_account}/identity", json={"display_name": "x"})
    assert r.status_code == 409, "dang co mot lan doi cho chay"

    r = await client.delete(f"/accounts/{ig_account}/identity")
    assert r.status_code == 200 and r.json()["pending"] is None


async def test_username_change_respects_the_platform_interval(client, ig_account):
    async with SessionLocal() as s:
        s.add(
            ActivityJob(
                account_id=ig_account,
                kind=ActivityKind.IDENTITY,
                status=JobStatus.SUCCEEDED,
                scheduled_at=datetime.now(UTC) - timedelta(days=2),
                target_url=identity.plan_to_target({"username": "recent"}),
            )
        )
        await s.commit()
    r = await client.post(f"/accounts/{ig_account}/identity", json={"username": "another_1"})
    assert (r.status_code == 409 and "14" not in r.json()["detail"]) or r.status_code == 409
    r = await client.post(f"/accounts/{ig_account}/identity", json={"display_name": "Chỉ tên"})
    assert r.status_code == 200, "ten hien thi khong bi gioi han"
    await client.delete(f"/accounts/{ig_account}/identity")


async def test_tiktok_is_refused_with_a_reason(client):
    tk = (await client.get("/accounts", params={"limit": 1})).json()["items"]
    if not tk or tk[0]["platform"] != "tiktok":
        pytest.skip("khong co tai khoan tiktok")
    r = await client.get(f"/accounts/{tk[0]['id']}/identity")
    assert r.status_code == 200 and not r.json()["supported"]
    assert "trình duyệt" in r.json()["why_not"]
    r = await client.post(f"/accounts/{tk[0]['id']}/identity", json={"display_name": "x"})
    assert r.status_code == 409
