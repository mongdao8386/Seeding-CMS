"""Mo mot profile ra man hinh tu dashboard.

Cai duoc kiem o day khong phai la trinh duyet co hien ra khong - cai do phai nhin
bang mat. Cai duoc kiem la hai thu quanh no: dong lenh sinh ra co dung khong, va lop
chan proxy co con hieu luc tren duong nay khong.

Lop chan moi la phan quan trong. Job dang bai da bi chan khi thieu proxy roi, nhung
"mo tay de xem thoi" rat de duoc coi la ngoai le - ma no khong phai ngoai le nao ca:
cua so mo ra van tai trang that, tu IP nha nguoi van hanh, va nen tang ghi lai dieu
do y het nhu khi worker chay.
"""

import sys
import uuid

import httpx
import pytest
from httpx import ASGITransport

from seeding.api.main import app
from seeding.config import get_settings
from seeding.core import desktop

# ------------------------------------------------------------ dong lenh sinh ra


def test_command_points_at_the_script_with_the_same_interpreter():
    """Phai la `sys.executable`, khong phai "python".

    Tren may nay `python` tren PATH la ban he thong con du an chay trong .venv. Goi
    nham ban se hong ngay o dong import dau tien - va vi tien trinh duoc sinh ra roi
    buong tay, khong ai nhin thay thong bao loi do ca.
    """
    profile_id = uuid.uuid4()
    cmd = desktop.command(profile_id)

    assert cmd[0] == sys.executable
    assert cmd[1].endswith("open_profile.py")
    assert cmd[2] == str(profile_id)


def test_a_url_is_passed_through_when_given():
    cmd = desktop.command(uuid.uuid4(), "https://www.tiktok.com/tiktokstudio/upload")
    assert cmd[-1] == "https://www.tiktok.com/tiktokstudio/upload"


def test_no_url_means_no_extra_argument():
    assert len(desktop.command(uuid.uuid4())) == 3


def test_the_script_actually_exists():
    """Duong dan dung `__file__` len ba cap - de hong am tham khi doi cau truc thu muc."""
    assert desktop.SCRIPT.is_file(), f"khong thay {desktop.SCRIPT}"


# ----------------------------------------------------------------- qua API that


@pytest.fixture(scope="module")
async def client():
    token = get_settings().api_token
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"authorization": f"Bearer {token}"},
        timeout=60,
    ) as c:
        yield c


@pytest.fixture
async def profile_without_proxy(client):
    """Mot tai khoan co profile nhung KHONG gan proxy, roi don sach sau khi xong."""
    workspaces = (await client.get("/workspaces")).json()
    ws = workspaces[0]["id"] if workspaces else None
    persona = (
        await client.post(
            "/personas",
            json={"name": f"thu-{uuid.uuid4().hex[:8]}", **({"workspace_id": ws} if ws else {})},
        )
    ).json()

    account = (
        await client.post(
            "/accounts",
            json={
                "persona_id": persona["id"],
                "platform": "tiktok",
                "handle": f"thu_{uuid.uuid4().hex[:10]}",
                "start_warmup": False,
            },
        )
    ).json()
    profile = (await client.post("/profiles", json={"account_id": account["id"]})).json()

    yield profile["id"]

    await client.delete(f"/profiles/{profile['id']}?force=true")
    await client.delete(f"/accounts/{account['id']}?force=true")
    await client.delete(f"/personas/{persona['id']}?force=true")


async def test_opening_a_profile_without_a_proxy_is_refused(client, profile_without_proxy):
    """Va noi ro vi sao, chu khong phai mot ma 409 tron."""
    r = await client.post(f"/profiles/{profile_without_proxy}/open", json={})

    assert r.status_code == 409
    assert "proxy" in r.json()["detail"].lower()


async def test_opening_an_unknown_profile_is_a_404(client):
    r = await client.post(f"/profiles/{uuid.uuid4()}/open", json={})
    assert r.status_code == 404
