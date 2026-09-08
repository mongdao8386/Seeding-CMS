"""Mo mot profile ra man hinh tu dashboard.

Cai duoc kiem la hai thu quanh cua so: dong lenh sinh ra co dung khong, va lop chan
proxy co con hieu luc tren duong nay khong. "Mo tay de xem thoi" rat de duoc coi la
ngoai le - ma no khong phai: cua so mo ra van tai trang that tu IP nha nguoi van hanh.
"""

import sys
import uuid

import httpx
import pytest
from httpx import ASGITransport

from seeding.api.main import app
from seeding.config import get_settings
from seeding.db import SessionLocal
from seeding.domain import fingerprint as fpm
from seeding.domain.defaults import ensure_defaults
from seeding.domain.models import Account, Platform, Profile
from seeding.ops import desktop

# ------------------------------------------------------------ dong lenh sinh ra


def test_command_points_at_the_script_with_the_same_interpreter():
    """`sys.executable`, khong phai "python": tren may nay `python` la ban he thong."""
    profile_id = uuid.uuid4()
    cmd = desktop.command(profile_id)
    assert cmd[0] == sys.executable
    assert cmd[1].endswith("open_profile.py")
    assert cmd[2] == str(profile_id)


def test_a_url_is_passed_through_when_given():
    cmd = desktop.command(uuid.uuid4(), "https://www.tiktok.com/")
    assert cmd[-1] == "https://www.tiktok.com/"


def test_the_script_actually_exists():
    assert desktop.SCRIPT.is_file(), f"khong thay {desktop.SCRIPT}"


# ----------------------------------------------------------------- qua API that


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
async def profile_without_proxy():
    """Mot tai khoan co profile nhung KHONG gan proxy, don sach sau khi xong."""
    async with SessionLocal() as s:
        _, persona = await ensure_defaults(s)
        account = Account(
            persona_id=persona.id,
            platform=Platform.TIKTOK,
            handle=f"thu_{uuid.uuid4().hex[:10]}",
        )
        s.add(account)
        await s.flush()
        profile = Profile(
            account_id=account.id, fingerprint=fpm.generate(), os_family="windows", locale="auto"
        )
        s.add(profile)
        await s.commit()
        ids = (account.id, profile.id)

    yield ids[1]

    async with SessionLocal() as s:
        for model, key in ((Profile, ids[1]), (Account, ids[0])):
            obj = await s.get(model, key)
            if obj is not None:
                await s.delete(obj)
        await s.commit()


async def test_opening_a_profile_without_a_proxy_is_refused(client, profile_without_proxy):
    r = await client.post(f"/profiles/{profile_without_proxy}/open", json={})
    assert r.status_code == 409
    assert "proxy" in r.json()["detail"].lower()


async def test_opening_an_unknown_profile_is_a_404(client):
    r = await client.post(f"/profiles/{uuid.uuid4()}/open", json={})
    assert r.status_code == 404
