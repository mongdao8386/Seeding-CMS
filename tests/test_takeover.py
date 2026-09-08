"""Hang doi cho nguoi, qua API that, tren mot tai khoan thu (don sach sau khi xong).

Cai duoc kiem: mo yeu cau -> tai khoan dung lai va hien tren /takeovers; mo lan hai
chi cap nhat ly do; giai xong -> tai khoan ve WARMING (khong ve ACTIVE); bo -> DEAD;
doi soat tim ra tai khoan NEEDS_HUMAN bi bo quen. Duong hen lai job ket (6 tieng
sau) can mot job that tren tai khoan san sang, khong dung tai khoan that de thu.
"""

import uuid

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
    Platform,
    Profile,
    TakeoverRequest,
    TakeoverStatus,
)
from seeding.ops import takeover
from seeding.platforms import base as adapters


@pytest.fixture(scope="module")
async def client():
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"authorization": f"Bearer {get_settings().api_token}"},
        timeout=60,
    ) as c:
        yield c


@pytest.fixture(autouse=True)
def _tiktok_session_alive(monkeypatch):
    """Resolve hoi nen tang xem phien con song khong. Trong test: song, khong ra mang."""

    async def alive(profile):
        return True, "user_id=1"

    monkeypatch.setitem(adapters._HEALTH, Platform.TIKTOK, alive)


@pytest.fixture
async def stuck_account():
    """Tai khoan ACTIVE co profile; don sach sau khi xong."""
    async with SessionLocal() as s:
        _, persona = await ensure_defaults(s)
        account = Account(
            persona_id=persona.id,
            platform=Platform.TIKTOK,
            handle=f"thu_{uuid.uuid4().hex[:10]}",
            status=AccountStatus.ACTIVE,
        )
        s.add(account)
        await s.flush()
        profile = Profile(
            account_id=account.id, fingerprint=fpm.generate(), os_family="windows", locale="auto"
        )
        s.add(profile)
        await s.commit()
        account_id = account.id

    yield account_id

    async with SessionLocal() as s:
        obj = await s.get(Account, account_id)
        if obj is not None:
            await s.delete(obj)
        await s.commit()


async def test_open_then_resolve_returns_the_account_to_warming(client, stuck_account):
    async with SessionLocal() as s:
        account = await s.get(Account, stuck_account)
        req = await takeover.open_request(s, account, "captcha")
        assert account.status is AccountStatus.NEEDS_HUMAN
        # Mo lan hai: cung yeu cau, ly do moi, khong tao dong moi.
        again = await takeover.open_request(s, account, "captcha lần nữa")
        assert again.id == req.id and again.reason == "captcha lần nữa"

    r = await client.get("/takeovers")
    assert r.status_code == 200
    mine = [t for t in r.json() if t["account_id"] == str(stuck_account)]
    assert len(mine) == 1
    assert mine[0]["has_stuck_job"] is False
    assert mine[0]["reason"] == "captcha lần nữa"
    assert mine[0]["profile_id"] is not None

    r = await client.post(f"/takeovers/{req.id}/resolve", json={"by": "test", "note": "đã giải"})
    assert r.status_code == 200
    assert r.json()["status"] == "resolved"

    async with SessionLocal() as s:
        account = await s.get(Account, stuck_account)
        assert account.status is AccountStatus.WARMING, "vừa qua checkpoint thì đi chậm lại"

    # Giai lan hai la 409: yeu cau da dong.
    r = await client.post(f"/takeovers/{req.id}/resolve", json={"by": "test"})
    assert r.status_code == 409


async def test_abandon_marks_the_account_dead(client, stuck_account):
    async with SessionLocal() as s:
        account = await s.get(Account, stuck_account)
        req = await takeover.open_request(s, account, "khoá vĩnh viễn")

    r = await client.post(f"/takeovers/{req.id}/abandon", json={"by": "test", "note": "bỏ"})
    assert r.status_code == 200
    assert r.json()["status"] == "abandoned"

    async with SessionLocal() as s:
        account = await s.get(Account, stuck_account)
        assert account.status is AccountStatus.DEAD
        req = await s.get(TakeoverRequest, req.id)
        assert req.status is TakeoverStatus.ABANDONED and req.note == "bỏ"


async def test_reconcile_finds_a_stuck_account_with_no_request(client, stuck_account):
    async with SessionLocal() as s:
        account = await s.get(Account, stuck_account)
        account.status = AccountStatus.NEEDS_HUMAN
        await s.commit()

    # GET /takeovers doi soat truoc khi liet ke.
    r = await client.get("/takeovers")
    mine = [t for t in r.json() if t["account_id"] == str(stuck_account)]
    assert len(mine) == 1
    assert "reconcil" in mine[0]["reason"]


async def test_unknown_request_is_404(client):
    r = await client.post(f"/takeovers/{uuid.uuid4()}/resolve", json={"by": "test"})
    assert r.status_code == 404


async def test_settings_never_leak_secrets(client):
    r = await client.get("/settings")
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"warmup_quiet_days", "warmup_days", "alert_configured"}
    for key in body:
        assert "token" not in key and "url" not in key and "password" not in key


async def test_resolve_is_refused_while_the_session_is_still_dead(
    client, stuck_account, monkeypatch
):
    """Nguoi bam "Da giai" ma chua dang nhap lai: tu choi, noi ro phai lam gi, yeu cau van mo."""

    async def dead(profile):
        return False, "phiên chết: session_expired"

    monkeypatch.setitem(adapters._HEALTH, Platform.TIKTOK, dead)
    async with SessionLocal() as s:
        account = await s.get(Account, stuck_account)
        req = await takeover.open_request(s, account, "phiên chết: session_expired")

    r = await client.post(f"/takeovers/{req.id}/resolve", json={"by": "test"})
    assert r.status_code == 409
    assert "đăng nhập lại" in r.json()["detail"]

    r = await client.get("/takeovers")
    assert any(t["id"] == str(req.id) for t in r.json()), "yeu cau phai con mo"
    async with SessionLocal() as s:
        account = await s.get(Account, stuck_account)
        assert account.status is AccountStatus.NEEDS_HUMAN
