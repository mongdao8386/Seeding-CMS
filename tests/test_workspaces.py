"""Workspace: doi ten, xoa co canh bao, va persona phai theo workspace.

Loi that duoc sua o day: `/personas` tra ve TAT CA persona cua moi workspace. Hau qua
khong phai la danh sach dai - la o chon workspace tro nen VO NGHIA. Chon workspace nao
thi danh sach persona van y het, va chon mot persona co san se lang le dat tai khoan
vao workspace cua persona do chu khong phai cai vua chon.
"""

import httpx
import pytest
from httpx import ASGITransport

from seeding.api.main import app
from seeding.config import get_settings


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
async def workspace(client):
    """Mot workspace dung mot lan, tu don khi xong."""
    r = await client.post("/workspaces", json={"name": "Workspace test"})
    ws = r.json()["id"]
    yield ws
    await client.delete(f"/workspaces/{ws}?force=true")


# ------------------------------------------------------------------ doi ten


async def test_a_workspace_can_be_renamed(client, workspace):
    r = await client.patch(f"/workspaces/{workspace}", json={"name": "Ten moi"})
    assert r.status_code == 200
    assert r.json()["name"] == "Ten moi"


async def test_a_vietnamese_name_survives_the_round_trip(client, workspace):
    """Ten workspace la thu nguoi dung go bang tieng Viet. Mat dau la doi ten."""
    await client.patch(f"/workspaces/{workspace}", json={"name": "Chiến dịch tháng 9"})
    rows = (await client.get("/workspaces/detail")).json()
    mine = next(w for w in rows if w["id"] == workspace)
    assert mine["name"] == "Chiến dịch tháng 9"


async def test_an_empty_name_is_refused(client, workspace):
    """Workspace khong ten thi o chon tren thanh dieu huong hien ra mot dong trong."""
    assert (await client.patch(f"/workspaces/{workspace}", json={"name": ""})).status_code == 422


async def test_renaming_something_that_does_not_exist_says_so(client):
    r = await client.patch("/workspaces/00000000-0000-0000-0000-000000000000", json={"name": "x"})
    assert r.status_code == 404


# ------------------------------------------------- persona theo workspace


async def test_personas_are_filtered_by_workspace(client, workspace):
    """Day la loi lam o chon workspace tro nen vo nghia."""
    await client.post("/personas", json={"workspace_id": workspace, "name": "Chi cua rieng toi"})

    mine = (await client.get(f"/personas?workspace_id={workspace}")).json()
    assert [p["name"] for p in mine] == ["Chi cua rieng toi"]

    everything = (await client.get("/personas")).json()
    assert len(everything) >= len(mine)


async def test_a_workspace_with_no_personas_returns_an_empty_list_not_everything(client, workspace):
    """Tra ve tat ca khi khong khop la kieu hong nguy hiem nhat: nguoi dung tin rang
    day la persona cua workspace ho vua chon."""
    assert (await client.get(f"/personas?workspace_id={workspace}")).json() == []


# ------------------------------------------------------------- xoa co canh bao


async def test_counts_come_back_with_each_workspace(client, workspace):
    """Xoa mot workspace keo theo persona, tai khoan, profile va cookie jar cua chung.
    Nguoi dung phai thay minh sap mat gi TRUOC khi bam."""
    await client.post("/personas", json={"workspace_id": workspace, "name": "p"})
    rows = (await client.get("/workspaces/detail")).json()
    mine = next(w for w in rows if w["id"] == workspace)

    assert mine["personas"] == 1
    for key in ("accounts", "campaigns", "content"):
        assert key in mine


async def test_an_empty_workspace_deletes_without_force(client):
    r = await client.post("/workspaces", json={"name": "Bo di duoc"})
    ws = r.json()["id"]
    assert (await client.delete(f"/workspaces/{ws}")).status_code == 200


async def test_deleting_a_workspace_that_holds_accounts_is_refused_and_says_what_is_lost(
    client, workspace
):
    """Mat cookie jar nghia la phai dang nhap tay lai tung tai khoan mot."""
    persona = (
        await client.post("/personas", json={"workspace_id": workspace, "name": "co acc"})
    ).json()["id"]
    made = await client.post(
        "/accounts",
        json={"persona_id": persona, "platform": "threads", "handle": "ws_test_acc"},
    )
    account = made.json()["id"]

    try:
        r = await client.delete(f"/workspaces/{workspace}")
        assert r.status_code == 409
        detail = r.json()["detail"]
        assert "1 account" in detail
        assert "force=true" in detail
    finally:
        await client.delete(f"/accounts/{account}?force=true")


async def test_force_deletes_it_anyway(client):
    r = await client.post("/workspaces", json={"name": "Xoa bang force"})
    ws = r.json()["id"]
    persona = (await client.post("/personas", json={"workspace_id": ws, "name": "p"})).json()["id"]
    await client.post(
        "/accounts",
        json={"persona_id": persona, "platform": "threads", "handle": "ws_force_acc"},
    )

    assert (await client.delete(f"/workspaces/{ws}?force=true")).status_code == 200
    assert all(w["id"] != ws for w in (await client.get("/workspaces/detail")).json())


# -------------------------------------------------------- loc tai khoan


async def test_accounts_can_be_filtered_by_workspace(client, workspace):
    persona = (
        await client.post("/personas", json={"workspace_id": workspace, "name": "p"})
    ).json()["id"]
    made = await client.post(
        "/accounts",
        json={"persona_id": persona, "platform": "threads", "handle": "ws_filter_acc"},
    )
    account = made.json()["id"]

    try:
        page = (await client.get(f"/accounts?workspace_id={workspace}&limit=500")).json()
        assert [a["handle"] for a in page["items"]] == ["ws_filter_acc"]
        assert page["total"] == 1
    finally:
        await client.delete(f"/accounts/{account}?force=true")
