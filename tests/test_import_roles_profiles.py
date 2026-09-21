"""Nhap acc that (21/09/2026): chon "Tuong tac cheo" ma acc van thanh xay kenh; 80/100 dong
khong co cookie nen khong co profile, va booster khong proxy thi nut Mo trinh duyet bi khoa -
khong con duong nao de dang nhap chung."""

from __future__ import annotations

import uuid

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import delete, select

from seeding.api import profiles as profiles_api
from seeding.api.main import app
from seeding.config import get_settings
from seeding.db import SessionLocal
from seeding.domain.models import (
    Account,
    AccountRole,
    Platform,
    Profile,
    Proxy,
    ProxyKind,
    ProxyStatus,
)
from seeding.ops import bulk

GUID = "9e5f94bc-e8a4-4e73-b8be-63364c29d753"
COOKIE = "; ".join(f"k{i}=v{i}" for i in range(25)) + "; sessionid=abc123def456; ttwid=1|x"


@pytest.fixture(scope="module")
async def client():
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"authorization": f"Bearer {get_settings().api_token}"},
        timeout=60,
    ) as c:
        yield c


def _rows(tag: str) -> str:
    six = f"bo_{tag}_a|TikPw1|a{tag}@hotmail.com|MailPw1|M.C5_BAY.tok-a|{GUID}"
    eight = (
        f"bo_{tag}_b|TikPw2|b{tag}@hotmail.com|MailPw2|M.C5_BAY.tok-b|{GUID}|"
        f"kp{tag}@getnada.com|{COOKIE}"
    )
    seven = f"bo_{tag}_c|TikPw3|c{tag}@hotmail.com|MailPw3|M.C5_BAY.tok-c|{GUID}|{COOKIE}"
    return chr(10).join([six, eight, seven]) + chr(10)


async def _cleanup(tag: str, proxy_ids=()):
    async with SessionLocal() as s:
        accounts = (
            (await s.execute(select(Account).where(Account.handle.like(f"bo_{tag}_%"))))
            .scalars()
            .all()
        )
        for a in accounts:
            await s.delete(a)
        await s.commit()
        if proxy_ids:
            await s.execute(delete(Proxy).where(Proxy.id.in_(list(proxy_ids))))
            await s.commit()


def test_six_column_rows_are_the_oauth_format_even_when_they_come_first():
    tag = "p1"
    report = bulk.parse(_rows(tag), default_platform=Platform.TIKTOK)
    assert report.ok, [p.detail for p in report.problems]
    assert report.inferred_header.startswith("username|passtiktok")
    a, b, c = report.rows
    assert a.cookie is None and a.secrets["mail_client_id"] == GUID
    assert a.secrets["password"] == "TikPw1" and a.secrets["recovery_password"] == "MailPw1"
    assert b.cookie and b.secrets["backup_email"] == f"kp{tag}@getnada.com"
    # 7 cot: nguoi ban bo cot mailKP, cookie troi vao cho cua no -> duoc dua ve dung cot.
    assert c.cookie and "sessionid=" in c.cookie and "backup_email" not in c.secrets
    assert report.with_cookies == 2


def test_the_chosen_role_reaches_every_row():
    report = bulk.parse(
        _rows("p2"), default_platform=Platform.TIKTOK, default_role=AccountRole.BOOSTER
    )
    assert {r.role for r in report.rows} == {AccountRole.BOOSTER}


async def test_import_as_booster_creates_boosters_with_profiles_and_no_proxy(client):
    tag = uuid.uuid4().hex[:6]
    try:
        r = await client.post(
            "/accounts/import",
            data={
                "text": _rows(tag),
                "platform": "tiktok",
                "role": "booster",
                "attach_proxies": "true",
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["created"] == 3 and body["profiles_with_session"] == 2

        check = await client.post(
            "/accounts/import/check",
            data={"text": _rows(tag), "platform": "tiktok", "role": "booster"},
        )
        assert check.status_code == 200

        listed = (
            await client.get("/accounts", params={"q": f"bo_{tag}_", "role": "booster"})
        ).json()
        assert listed["total"] == 3, "chon Tuong tac cheo thi acc phai nam o Tuong tac cheo"
        async with SessionLocal() as s:
            profiles = (
                (
                    await s.execute(
                        select(Profile)
                        .join(Account, Account.id == Profile.account_id)
                        .where(Account.handle.like(f"bo_{tag}_%"))
                    )
                )
                .unique()
                .scalars()
                .all()
            )
            assert len(profiles) == 3, "acc khong cookie van co profile de mo trinh duyet dang nhap"
            assert all(p.proxy_id is None for p in profiles), "booster khong chiem cho proxy"
            assert sum(1 for p in profiles if p.cookies_enc) == 2
    finally:
        await _cleanup(tag)


async def test_channel_accounts_without_a_cookie_still_get_a_profile_and_a_proxy(client):
    tag = uuid.uuid4().hex[:6]
    async with SessionLocal() as s:
        proxy = Proxy(
            label=f"ip{tag}",
            kind=ProxyKind.RESIDENTIAL,
            host=f"imp-{tag}.example.com",
            port=8080,
            status=ProxyStatus.OK,
        )
        s.add(proxy)
        await s.commit()
        proxy_id = proxy.id
    try:
        r = await client.post(
            "/accounts/import",
            data={
                "text": _rows(tag),
                "platform": "tiktok",
                "role": "channel",
                "attach_proxies": "true",
            },
        )
        assert r.status_code == 200, r.text
        async with SessionLocal() as s:
            profiles = (
                (
                    await s.execute(
                        select(Profile)
                        .join(Account, Account.id == Profile.account_id)
                        .where(Account.handle.like(f"bo_{tag}_%"))
                    )
                )
                .unique()
                .scalars()
                .all()
            )
            assert len(profiles) == 3
            assert all(p.proxy_id is not None for p in profiles), "acc xay kenh lay cho proxy"
    finally:
        await _cleanup(tag, [proxy_id])


async def test_a_booster_without_a_proxy_can_be_opened_but_a_channel_cannot(client, monkeypatch):
    tag = uuid.uuid4().hex[:6]
    spawned = []
    monkeypatch.setattr(
        profiles_api.desktop, "spawn", lambda pid, url=None: spawned.append(pid) or 4242
    )
    try:
        await client.post(
            "/accounts/import",
            data={
                "text": _rows(tag),
                "platform": "tiktok",
                "role": "booster",
                "attach_proxies": "false",
            },
        )
        async with SessionLocal() as s:
            booster = (
                (
                    await s.execute(
                        select(Profile)
                        .join(Account, Account.id == Profile.account_id)
                        .where(Account.handle == f"bo_{tag}_a")
                    )
                )
                .unique()
                .scalar_one()
            )
            r = await client.post(f"/profiles/{booster.id}/open", json={})
            assert r.status_code == 200, r.text
            assert spawned == [booster.id]

            account = await s.get(Account, booster.account_id)
            account.role = AccountRole.CHANNEL
            await s.commit()
            r = await client.post(f"/profiles/{booster.id}/open", json={})
            assert r.status_code == 409, "acc xay kenh khong proxy van bi chan"
    finally:
        await _cleanup(tag)
