"""Proxy chet thi 5 acc tren no khong duoc mac ket: doi dia chi tai cho, hoac chuyen acc di."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import delete, select

from seeding.api import proxies as proxies_api
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
    Proxy,
    ProxyKind,
    ProxyStatus,
)
from seeding.ops import proxypool


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
async def fleet():
    """Proxy A (hong) dang gan 3 acc; proxy B (OK) trong. Don sach sau."""
    tag = uuid.uuid4().hex[:6]
    ids = SimpleNamespace(tag=tag, accounts=[], proxies=[])
    async with SessionLocal() as s:
        _, persona = await ensure_defaults(s)
        for i, status in enumerate((ProxyStatus.FAILING, ProxyStatus.OK)):
            proxy = Proxy(
                label=f"ev{tag}{i}",
                kind=ProxyKind.RESIDENTIAL,
                host=f"ev-{tag}-{i}.example.com",
                port=9000 + i,
                status=status,
                username="olduser",
            )
            proxy.set_password("oldpass")
            s.add(proxy)
            await s.flush()
            ids.proxies.append(proxy.id)
        for i in range(3):
            acc = Account(
                persona_id=persona.id,
                platform=Platform.TIKTOK,
                handle=f"ev_{tag}_{i}",
                status=AccountStatus.WARMING,
            )
            s.add(acc)
            await s.flush()
            ids.accounts.append(acc.id)
            s.add(
                Profile(
                    account_id=acc.id,
                    proxy_id=ids.proxies[0],
                    fingerprint=fpm.generate(),
                    os_family="windows",
                    locale="auto",
                )
            )
        await s.commit()
    yield ids
    async with SessionLocal() as s:
        for aid in ids.accounts:
            obj = await s.get(Account, aid)
            if obj is not None:
                await s.delete(obj)
        await s.commit()
        await s.execute(delete(Proxy).where(Proxy.id.in_(ids.proxies)))
        await s.commit()


async def _bound(proxy_id) -> int:
    async with SessionLocal() as s:
        return len(
            (await s.execute(select(Profile).where(Profile.proxy_id == proxy_id)))
            .unique()
            .scalars()
            .all()
        )


async def test_replacing_the_address_keeps_every_bound_account(client, fleet, monkeypatch):
    async def fake_test(proxy):
        proxy.status = ProxyStatus.OK
        proxy.last_exit_ip = "203.0.113.9"
        return SimpleNamespace(ok=True, exit_ip="203.0.113.9", latency_ms=10, error=None)

    monkeypatch.setattr(proxies_api.proxytest, "run", fake_test)
    new_line = f"new-{fleet.tag}.example.com:7777:newuser:newpass"
    r = await client.put(f"/proxies/{fleet.proxies[0]}", data={"text": new_line, "test": "true"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["host"] == f"new-{fleet.tag}.example.com" and body["port"] == 7777
    assert body["status"] == "ok" and body["bound_count"] == 3
    assert "newpass" not in r.text, "mat khau proxy khong di ra ngoai"
    async with SessionLocal() as s:
        proxy = await s.get(Proxy, fleet.proxies[0])
        assert proxy.username == "newuser" and proxy.get_password() == "newpass"
    assert await _bound(fleet.proxies[0]) == 3


async def test_replacing_with_an_address_another_proxy_uses_is_refused(client, fleet):
    async with SessionLocal() as s:
        other = await s.get(Proxy, fleet.proxies[1])
        line = f"{other.host}:{other.port}"
    r = await client.put(f"/proxies/{fleet.proxies[0]}", data={"text": line, "test": "false"})
    assert r.status_code == 409


async def test_garbage_is_refused_without_touching_the_proxy(client, fleet):
    r = await client.put(
        f"/proxies/{fleet.proxies[0]}", data={"text": "khong phai proxy", "test": "false"}
    )
    assert r.status_code == 422
    async with SessionLocal() as s:
        proxy = await s.get(Proxy, fleet.proxies[0])
        assert proxy.host == f"ev-{fleet.tag}-0.example.com"


async def test_evacuate_moves_accounts_to_other_ok_proxies_and_records_why(
    client, fleet, monkeypatch
):
    real_build = proxypool.build_pool

    async def only_mine(session):
        pool = await real_build(session)
        pool._heap = [h for h in pool._heap if h[2].id in fleet.proxies]
        return pool

    monkeypatch.setattr(proxypool, "build_pool", only_mine)
    monkeypatch.setattr(proxypool, "capacity", lambda: 2)
    r = await client.post(f"/proxies/{fleet.proxies[0]}/evacuate", data={"reason": "hết hạn"})
    assert r.status_code == 200, r.text
    body = r.json()
    # Proxy B chi con 2 cho: 2 acc chuyen duoc, 1 acc o lai.
    assert body["moved"] == 2 and body["stuck"] == 1
    assert await _bound(fleet.proxies[1]) == 2 and await _bound(fleet.proxies[0]) == 1
    assert "dán thêm proxy" in body["detail"]
