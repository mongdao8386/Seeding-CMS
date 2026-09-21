"""Mot proxy dung chung toi da ACCOUNTS_PER_PROXY acc (21/09/2026: 10 proxy cho 50 acc).

Chia deu (it nguoi nhat truoc), booster khong chiem cho, acc con thieu duoc gan khi dan them
proxy, danh sach proxy hien du moi acc dang gan, va hai acc chung proxy khong chay cung luc."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import delete, select

from seeding.api.main import app
from seeding.config import get_settings
from seeding.db import SessionLocal
from seeding.domain import fingerprint as fpm
from seeding.domain.defaults import ensure_defaults
from seeding.domain.models import (
    Account,
    AccountRole,
    AccountStatus,
    Platform,
    Profile,
    Proxy,
    ProxyKind,
    ProxyStatus,
)
from seeding.ops import proxypool
from seeding.ops.proxypool import ProxyPool


def _p(label: str):
    return SimpleNamespace(label=label, id=uuid.uuid4())


# ------------------------------------------------------------------ pool thuan tuy


def test_pool_fills_the_least_loaded_proxy_first():
    a, b, c = _p("A"), _p("B"), _p("C")
    pool = ProxyPool([(a, 2), (b, 0), (c, 1)], cap=3)
    taken = [pool.take().label for _ in range(6)]
    # B(0) -> B/C(1) ... khong proxy nao vuot 3, A chi con 1 cho.
    assert taken.count("A") == 1 and taken.count("B") == 3 and taken.count("C") == 2
    assert pool.take() is None and pool.misses == 1
    assert pool.free_slots == 0


def test_ten_proxies_hold_fifty_accounts_five_each():
    proxies = [_p(f"P{i:02d}") for i in range(10)]
    pool = ProxyPool([(p, 0) for p in proxies], cap=5)
    assert pool.free_slots == 50
    got = [pool.take() for _ in range(50)]
    assert all(g is not None for g in got)
    per = {p.label: sum(1 for g in got if g is p) for p in proxies}
    assert set(per.values()) == {5}
    assert pool.take() is None


def test_capacity_one_restores_one_account_per_proxy():
    a, b = _p("A"), _p("B")
    pool = ProxyPool([(a, 0), (b, 1)], cap=1)
    assert pool.take() is a
    assert pool.take() is None


def test_full_proxies_never_enter_the_pool():
    pool = ProxyPool([(_p("A"), 5), (_p("B"), 7)], cap=5)
    assert pool.free_slots == 0 and pool.take() is None


# ------------------------------------------------------------------ DB + API


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
    """2 proxy OK + 1 proxy chua thu, 5 acc kenh co profile KHONG proxy, 1 booster, 1 acc
    kenh chua co profile. Don sach sau."""
    tag = uuid.uuid4().hex[:6]
    ids = SimpleNamespace(accounts=[], proxies=[], tag=tag)
    async with SessionLocal() as s:
        _, persona = await ensure_defaults(s)
        for i, status in enumerate((ProxyStatus.OK, ProxyStatus.OK, ProxyStatus.UNTESTED)):
            proxy = Proxy(
                label=f"sh{tag}{i}",
                kind=ProxyKind.RESIDENTIAL,
                host=f"share-{tag}-{i}.example.com",
                port=8000 + i,
                status=status,
            )
            s.add(proxy)
            await s.flush()
            ids.proxies.append(proxy.id)

        async def account(handle, role, with_profile=True):
            acc = Account(
                persona_id=persona.id,
                platform=Platform.TIKTOK,
                handle=handle,
                status=AccountStatus.WARMING,
                role=role,
            )
            s.add(acc)
            await s.flush()
            ids.accounts.append(acc.id)
            if with_profile:
                s.add(
                    Profile(
                        account_id=acc.id,
                        fingerprint=fpm.generate(),
                        os_family="windows",
                        locale="auto",
                    )
                )
            return acc

        for i in range(5):
            await account(f"sh_kenh_{tag}_{i}", AccountRole.CHANNEL)
        await account(f"sh_clone_{tag}", AccountRole.BOOSTER)
        await account(f"sh_chuaprofile_{tag}", AccountRole.CHANNEL, with_profile=False)
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


async def _loads(ids) -> dict:
    async with SessionLocal() as s:
        counts = await proxypool.loads(s)
    return {pid: counts.get(pid, 0) for pid in ids.proxies}


async def test_attach_missing_spreads_channels_and_skips_boosters(fleet, monkeypatch):
    monkeypatch.setattr(proxypool, "capacity", lambda: 3)
    async with SessionLocal() as s:
        # Chi tinh tren proxy cua test nay: cac proxy OK khac trong DB (neu co) duoc lam day gia.
        others = (
            (await s.execute(select(Proxy).where(Proxy.id.not_in(fleet.proxies))))
            .unique()
            .scalars()
        )
        real_build = proxypool.build_pool

        async def only_mine(session):
            pool = await real_build(session)
            pool._heap = [h for h in pool._heap if h[2].id in fleet.proxies]
            return pool

        monkeypatch.setattr(proxypool, "build_pool", only_mine)
        _ = list(others)
        result = await proxypool.attach_missing(s)

    # 6 acc kenh can proxy (5 co profile + 1 chua co profile); 2 proxy OK x 3 cho = 6 cho.
    assert result["attached"] == 6 and result["still_missing"] == 0
    loads = await _loads(fleet)
    assert loads[fleet.proxies[0]] == 3 and loads[fleet.proxies[1]] == 3
    assert loads[fleet.proxies[2]] == 0, "proxy chua thu OK khong duoc dung"
    async with SessionLocal() as s:
        booster = (
            (
                await s.execute(
                    select(Profile)
                    .join(Account, Account.id == Profile.account_id)
                    .where(Account.handle == f"sh_clone_{fleet.tag}")
                )
            )
            .unique()
            .scalar_one()
        )
        assert booster.proxy_id is None, "booster khong chiem cho proxy"
        late = (
            (
                await s.execute(
                    select(Profile)
                    .join(Account, Account.id == Profile.account_id)
                    .where(Account.handle == f"sh_chuaprofile_{fleet.tag}")
                )
            )
            .unique()
            .scalar_one_or_none()
        )
        assert late is not None and late.proxy_id in fleet.proxies, (
            "acc chua profile duoc tao kem proxy"
        )


async def test_proxy_list_shows_every_bound_handle_and_capacity(client, fleet):
    async with SessionLocal() as s:
        profiles = (
            (
                await s.execute(
                    select(Profile)
                    .join(Account, Account.id == Profile.account_id)
                    .where(Account.handle.like(f"sh_kenh_{fleet.tag}_%"))
                )
            )
            .unique()
            .scalars()
            .all()
        )
        for p in profiles[:3]:
            p.proxy_id = fleet.proxies[0]
        await s.commit()

    body = (await client.get("/proxies", params={"q": f"sh{fleet.tag}", "limit": 50})).json()
    rows = {r["label"]: r for r in body["items"]}
    shared = rows[f"sh{fleet.tag}0"]
    assert shared["bound_count"] == 3 and len(shared["bound_handles"]) == 3
    assert shared["bound_handle"] == shared["bound_handles"][0]
    assert shared["capacity"] == max(1, get_settings().accounts_per_proxy)
    assert body["total"] == 3, "proxy dung chung khong duoc nhan doi dong trong danh sach"
    assert rows[f"sh{fleet.tag}1"]["bound_count"] == 0

    # Con acc gan thi khong xoa duoc; proxy trong thi xoa duoc.
    r = await client.delete(f"/proxies/{shared['id']}")
    assert r.status_code == 409
    r = await client.delete(f"/proxies/{rows[f'sh{fleet.tag}1']['id']}")
    assert r.status_code == 200


async def test_stats_count_free_slots_not_free_proxies(client, fleet):
    before = (await client.get("/stats")).json()
    assert before["accounts_per_proxy"] == max(1, get_settings().accounts_per_proxy)
    async with SessionLocal() as s:
        prof = (
            (
                await s.execute(
                    select(Profile)
                    .join(Account, Account.id == Profile.account_id)
                    .where(Account.handle == f"sh_kenh_{fleet.tag}_0")
                )
            )
            .unique()
            .scalar_one()
        )
        prof.proxy_id = fleet.proxies[0]
        await s.commit()
    after = (await client.get("/stats")).json()
    assert after["proxy_slots_free"] == before["proxy_slots_free"] - 1
    assert after["proxies_free"] == before["proxies_free"], "proxy con cho van tinh la con cho"


async def test_settings_expose_accounts_per_proxy(client):
    body = (await client.get("/settings")).json()
    assert body["accounts_per_proxy"] >= 1


# ------------------------------------------------------------------ worker: khoa theo proxy


class _Redis:
    """Du cho worker: SET NX + DELETE."""

    def __init__(self):
        self.keys: dict[str, str] = {}

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.keys:
            return None
        self.keys[key] = value
        return True

    async def get(self, key):
        return self.keys.get(key)

    async def delete(self, key):
        self.keys.pop(key, None)


async def test_a_job_is_deferred_while_another_account_on_the_same_proxy_runs(fleet):
    from datetime import UTC, datetime

    from seeding.domain.models import ActivityJob, ActivityKind, JobStatus
    from seeding.worker import tasks

    async with SessionLocal() as s:
        prof = (
            (
                await s.execute(
                    select(Profile)
                    .join(Account, Account.id == Profile.account_id)
                    .where(Account.handle == f"sh_kenh_{fleet.tag}_0")
                )
            )
            .unique()
            .scalar_one()
        )
        prof.proxy_id = fleet.proxies[0]
        prof.set_cookies(
            {"cookies": [{"name": "sessionid", "value": "x", "domain": ".tiktok.com", "path": "/"}]}
        )
        job = ActivityJob(
            account_id=prof.account_id,
            kind=ActivityKind.ENGAGE,
            status=JobStatus.RUNNING,
            scheduled_at=datetime.now(UTC),
            duration_seconds=30,
            target_url="https://www.tiktok.com/@x/video/1",
        )
        s.add(job)
        await s.commit()
        job_id = str(job.id)

    redis = _Redis()
    # Acc khac cung proxy dang giu khoa.
    redis.keys[f"lock:proxy:{fleet.proxies[0]}"] = "other-job"
    status = await tasks.run_activity_job({"redis": redis}, job_id)
    assert status == "deferred"
    async with SessionLocal() as s:
        fresh = await s.get(ActivityJob, uuid.UUID(job_id))
        assert fresh.status is JobStatus.SCHEDULED and fresh.attempt_count == 0
        assert "cùng proxy" in (fresh.last_error or "")
    assert f"lock:account:{fresh.account_id}" not in redis.keys, "khoa acc phai duoc tra lai"
    assert redis.keys[f"lock:proxy:{fleet.proxies[0]}"] == "other-job", (
        "khong dung vao khoa cua job kia"
    )
