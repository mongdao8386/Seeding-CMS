"""Phan trang cho cac danh sach dai.

Truoc day moi endpoint tra ve tat ca. Duoi 200 ban ghi thi khong ai thay gi; tren nua
thi man hinh cham dan. Nguy hiem hon la hai cho cat bot AM THAM: `/campaigns` cat cung
o 100 va `/content` o 200 - mot chuoi lap hang ngay vuot moc 100 trong ba thang, va
cac chien dich cu lang le bien mat khoi man hinh ma khong co dau hieu gi.

Nen thu duoc kiem ky nhat o day la `total`: no phai la so ban ghi KHOP DIEU KIEN LOC,
khong phai so dong trong trang. Sai cho do thi giao dien bao "10 tai khoan" trong khi
co 213, va khong ai phat hien ra.
"""

import httpx
import pytest
from httpx import ASGITransport

from seeding.api.main import app
from seeding.config import get_settings

PAGED = ("/accounts", "/profiles", "/proxies", "/campaigns", "/content")


@pytest.fixture(scope="module")
async def client():
    token = get_settings().api_token
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"authorization": f"Bearer {token}"},
        timeout=60,
    ) as c:
        yield c


# ------------------------------------------------------------- hinh dang chung


@pytest.mark.parametrize("path", PAGED)
async def test_every_paged_endpoint_returns_the_same_envelope(client, path):
    """Bon khoa nay la hop dong voi giao dien. Thieu mot cai la mot man hinh hong."""
    body = (await client.get(path)).json()
    assert set(body) == {"items", "total", "limit", "offset"}
    assert isinstance(body["items"], list)
    assert isinstance(body["total"], int)


@pytest.mark.parametrize("path", PAGED)
async def test_a_page_never_holds_more_than_the_limit(client, path):
    body = (await client.get(f"{path}?limit=2")).json()
    assert len(body["items"]) <= 2


@pytest.mark.parametrize("path", PAGED)
async def test_total_counts_everything_not_just_this_page(client, path):
    """Neu `total` dem theo trang thi no luon bang so dong dang hien - dung cai khong
    ai can biet, va giao dien se khong bao gio biet con trang sau."""
    everything = (await client.get(f"{path}?limit=500")).json()
    if everything["total"] < 2:
        pytest.skip("chua du du lieu de chia trang")

    one = (await client.get(f"{path}?limit=1")).json()
    assert one["total"] == everything["total"]
    assert len(one["items"]) == 1


@pytest.mark.parametrize("path", PAGED)
async def test_the_echoed_limit_and_offset_are_what_was_asked_for(client, path):
    body = (await client.get(f"{path}?limit=3&offset=1")).json()
    assert body["limit"] == 3
    assert body["offset"] == 1


# -------------------------------------------------------------------- di trang


async def test_pages_do_not_overlap_and_cover_everything(client):
    """Loi off-by-one o offset lam mot ban ghi bi bo qua hoac hien hai lan. Voi tai
    khoan seeding, mot cai bi bo qua nghia la no khong bao gio duoc lap lich."""
    everything = (await client.get("/accounts?limit=500")).json()
    if everything["total"] < 4:
        pytest.skip("chua du tai khoan de chia trang")

    seen = []
    offset = 0
    while offset < everything["total"]:
        page = (await client.get(f"/accounts?limit=2&offset={offset}")).json()
        seen.extend(x["id"] for x in page["items"])
        offset += 2

    expected = [x["id"] for x in everything["items"]]
    assert seen == expected
    assert len(set(seen)) == len(seen), "co ban ghi hien ra hai lan"


async def test_reading_past_the_end_gives_an_empty_page_not_an_error(client):
    body = (await client.get("/accounts?limit=5&offset=100000")).json()
    assert body["items"] == []
    assert body["total"] >= 0


# ------------------------------------------------------------------- tran cung


async def test_an_absurd_limit_is_refused_rather_than_obeyed(client):
    """Khong phai de tiet kiem bang - de mot loi go nham khong keo ca database vao
    bo nho roi lam chet API."""
    assert (await client.get("/accounts?limit=100000")).status_code == 422


async def test_a_negative_offset_is_refused(client):
    assert (await client.get("/accounts?offset=-1")).status_code == 422


async def test_a_zero_limit_is_refused(client):
    """limit=0 tra ve trang rong mai mai - vong lap di trang se khong bao gio ket thuc."""
    assert (await client.get("/accounts?limit=0")).status_code == 422


# ---------------------------------------------------------------- loc va tim


async def test_filtering_narrows_total_as_well_as_items(client):
    """`total` phai theo bo loc. Neu no van dem tat ca thi giao dien se ve nut "next"
    dan toi nhung trang rong."""
    everything = (await client.get("/accounts?limit=500")).json()
    if not everything["items"]:
        pytest.skip("chua co tai khoan nao")

    platform = everything["items"][0]["platform"]
    filtered = (await client.get(f"/accounts?platform={platform}&limit=500")).json()

    assert filtered["total"] <= everything["total"]
    assert all(a["platform"] == platform for a in filtered["items"])
    assert filtered["total"] == len(filtered["items"])


async def test_search_matches_part_of_a_handle(client):
    everything = (await client.get("/accounts?limit=500")).json()
    if not everything["items"]:
        pytest.skip("chua co tai khoan nao")

    handle = everything["items"][0]["handle"]
    fragment = handle[1:-1] or handle
    found = (await client.get(f"/accounts?q={fragment}&limit=500")).json()
    assert any(a["handle"] == handle for a in found["items"])


async def test_search_that_matches_nothing_says_zero_rather_than_everything(client):
    """Bo loc bi bo qua am tham thi ket qua tra ve la TOAN BO danh sach - trong khi
    nguoi dung tin rang day la nhung gi khop voi tu khoa cua ho."""
    body = (await client.get("/accounts?q=zzz_khong_ton_tai_zzz")).json()
    assert body["total"] == 0
    assert body["items"] == []


async def test_an_unknown_platform_is_refused_instead_of_ignored(client):
    assert (await client.get("/accounts?platform=myspace")).status_code == 422


# --------------------------------------------------- hang doi thi khong cat


async def test_accounts_without_a_profile_is_a_full_list_not_a_page(client):
    """Day la hang doi viec phai lam. Mot hang doi chi hien trang dau thi khong con la
    hang doi - va nhung tai khoan o trang hai se khong bao gio duoc tao profile."""
    body = (await client.get("/accounts/without-profile")).json()
    assert isinstance(body, list)


async def test_reddit_accounts_never_appear_in_the_no_profile_queue(client):
    """Reddit di bang API, khong can profile. Dua no vao hang doi la tao viec khong
    ton tai, va no se nam do mai vi khong ai lam duoc gi."""
    body = (await client.get("/accounts/without-profile")).json()
    assert all(a["platform"] != "reddit" for a in body)


async def test_dead_accounts_are_not_asked_to_get_a_profile(client):
    body = (await client.get("/accounts/without-profile")).json()
    assert all(a["status"] != "dead" for a in body)


async def test_profiles_can_be_filtered_to_the_ones_never_signed_into(client):
    body = (await client.get("/profiles?logged_in=false&limit=500")).json()
    assert all(p["last_login_at"] is None for p in body["items"])
