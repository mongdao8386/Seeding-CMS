"""Xac thuc phai fail-closed.

He thong nay giu cookie jar cua hang chuc tai khoan va sinh duoc ma 2FA. Mot API mo
toang la mat sach, nen cac test o day kiem dung mot dieu: khong co token thi khong
lam duoc gi.
"""

import httpx
import pytest
from httpx import ASGITransport

from seeding.api.main import app
from seeding.config import get_settings


@pytest.fixture
def token():
    return get_settings().api_token


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_health_is_open_so_you_can_check_the_api_is_alive(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


async def test_health_says_whether_the_api_is_actually_protected(client):
    """Chay ma khong biet minh dang mo toang la te nhat."""
    assert "authenticated" in (await client.get("/health")).json()


async def test_a_real_route_is_refused_without_a_token(client):
    assert (await client.get("/stats")).status_code == 401


async def test_a_wrong_token_is_refused(client):
    r = await client.get("/stats", headers={"authorization": "Bearer sai-be-bet"})
    assert r.status_code == 401


async def test_the_right_token_gets_through(client, token):
    if not token:
        pytest.skip("chua dat API_TOKEN trong .env")
    r = await client.get("/stats", headers={"authorization": f"Bearer {token}"})
    assert r.status_code == 200


async def test_the_scheme_matters_not_just_the_value(client, token):
    """Gui moi gia tri token ma khong co tien to Bearer thi khong duoc chap nhan."""
    if not token:
        pytest.skip("chua dat API_TOKEN trong .env")
    assert (await client.get("/stats", headers={"authorization": token})).status_code == 401


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/accounts"),
        ("get", "/proxies"),
        ("get", "/stats"),
        ("get", "/system"),
        ("post", "/accounts/import/check"),
        ("post", "/proxies/import"),
    ],
)
async def test_every_sensitive_route_is_behind_the_token(client, method, path):
    """Quet ca danh sach thay vi tin rang khong co route nao bi bo sot."""
    r = await getattr(client, method)(path)
    assert r.status_code == 401, f"{method.upper()} {path} khong duoc bao ve"
