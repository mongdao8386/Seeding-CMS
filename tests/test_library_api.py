"""Kho media, tui hashtag, va CRUD day du - qua API that.

Cac test o day dung database that, nen chung cung la kiem chung cho cac rang buoc xoa:
xoa mot thu dang duoc tham chieu phai bi tu choi kem loi noi ro phai lam gi.
"""

import uuid

import httpx
import pytest
from httpx import ASGITransport

from seeding.api.main import app
from seeding.config import get_settings
from seeding.core import media, mediastore

pytestmark = pytest.mark.media  # can ffmpeg de lam anh xem truoc


@pytest.fixture(scope="module")
async def client():
    token = get_settings().api_token
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"authorization": f"Bearer {token}"},
        timeout=120,
    ) as c:
        yield c


@pytest.fixture(scope="module")
async def workspace(client):
    """Mot workspace cho ca module, khong phai moi test mot cai.

    Fixture cu tao mot workspace moi cho tung test va khong bao gio don, nen sau vai
    lan chay thi o chon workspace tren giao dien day nhung dong "Library test".
    """
    r = await client.post("/workspaces", json={"name": "Library test"})
    return r.json()["id"]


@pytest.fixture
def tag() -> str:
    """Hau to duy nhat: handle co rang buoc unique, chay lai khong duoc dung ten cu."""
    return uuid.uuid4().hex[:8]


@pytest.fixture
def sample_video(tmp_path):
    return media.make_test_video(tmp_path / "clip.mp4", seconds=2)


# ----------------------------------------------------------------------- media


async def test_upload_stores_the_file_and_reads_its_shape(client, workspace, sample_video):
    r = await client.post(
        "/media",
        params={"workspace_id": workspace},
        files={"file": ("my clip.mp4", sample_video.read_bytes(), "video/mp4")},
    )
    assert r.status_code == 200, r.text
    asset = r.json()

    assert asset["kind"] == "video"
    assert asset["size_bytes"] > 0
    assert asset["width"] == 640 and asset["height"] == 360
    assert 1.5 < asset["duration_seconds"] < 2.5
    assert asset["has_thumbnail"] is True
    # Ten file duoc lam sach: khong con khoang trang.
    assert " " not in asset["filename"]

    await client.delete(f"/media/{asset['id']}")


async def test_upload_rejects_a_file_type_it_cannot_handle(client, workspace):
    r = await client.post(
        "/media",
        params={"workspace_id": workspace},
        files={"file": ("notes.txt", b"not media", "text/plain")},
    )
    assert r.status_code == 415
    assert "Unsupported file type" in r.json()["detail"]


async def test_the_preview_image_is_served_back(client, workspace, sample_video):
    upload = (
        await client.post(
            "/media",
            params={"workspace_id": workspace},
            files={"file": ("clip.mp4", sample_video.read_bytes(), "video/mp4")},
        )
    ).json()

    r = await client.get(f"/media/{upload['id']}/thumb")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert len(r.content) > 500  # that su la mot buc anh

    await client.delete(f"/media/{upload['id']}")


async def test_deleting_media_removes_the_file_from_disk(client, workspace, sample_video):
    upload = (
        await client.post(
            "/media",
            params={"workspace_id": workspace},
            files={"file": ("clip.mp4", sample_video.read_bytes(), "video/mp4")},
        )
    ).json()

    path = mediastore.sources_dir() / upload["filename"]
    assert path.exists()

    r = await client.delete(f"/media/{upload['id']}")
    assert r.status_code == 200 and r.json()["deleted"] is True
    assert not path.exists()


async def test_media_in_use_is_protected_from_deletion(client, workspace, sample_video):
    upload = (
        await client.post(
            "/media",
            params={"workspace_id": workspace},
            files={"file": ("clip.mp4", sample_video.read_bytes(), "video/mp4")},
        )
    ).json()

    content = (
        await client.post(
            "/content",
            json={
                "workspace_id": workspace,
                "title_template": "with media",
                "media_ref": upload["filename"],
            },
        )
    ).json()

    blocked = await client.delete(f"/media/{upload['id']}")
    assert blocked.status_code == 409
    assert "still reference" in blocked.json()["detail"]

    forced = await client.delete(f"/media/{upload['id']}", params={"force": True})
    assert forced.status_code == 200

    await client.delete(f"/content/{content['id']}")


# -------------------------------------------------------------------- hashtags


async def test_hashtag_set_round_trip_normalises_tags(client, workspace):
    r = await client.post(
        "/hashtag-sets",
        json={"workspace_id": workspace, "name": "tech", "tags": ["  ai ", "#ML", "ai"]},
    )
    assert r.status_code == 200, r.text
    item = r.json()

    assert item["tags"] == ["#ai", "#ML"]  # them dau #, bo trung
    assert item["placeholder"] == "[[tags:tech:3]]"

    await client.delete(f"/hashtag-sets/{item['id']}")


async def test_two_sets_cannot_share_a_name(client, workspace):
    first = (
        await client.post(
            "/hashtag-sets", json={"workspace_id": workspace, "name": "dup", "tags": ["#a"]}
        )
    ).json()
    again = await client.post(
        "/hashtag-sets", json={"workspace_id": workspace, "name": "dup", "tags": ["#b"]}
    )
    assert again.status_code == 409

    await client.delete(f"/hashtag-sets/{first['id']}")


async def test_preview_expands_hashtags_and_counts_their_combinations(client, workspace):
    pool = [f"#tag{i}" for i in range(12)]
    created = (
        await client.post(
            "/hashtag-sets", json={"workspace_id": workspace, "name": "pool", "tags": pool}
        )
    ).json()

    r = await client.post(
        "/content/preview",
        json={
            "workspace_id": workspace,
            "title_template": "hello [[tags:pool:3]]",
            "account_count": 5,
        },
    )
    data = r.json()

    assert data["hashtag_combinations"] == 12 * 11 * 10
    assert data["combinations"] >= data["hashtag_combinations"]
    for sample in data["samples"]:
        assert "[[tags:" not in sample["title"]
        assert sample["title"].count("#") == 3

    await client.delete(f"/hashtag-sets/{created['id']}")


async def test_preview_flags_a_hashtag_set_that_does_not_exist(client, workspace):
    """Go sai ten tui thi phai bao ngay, khong de bai len kem chuoi [[tags:...]]."""
    r = await client.post(
        "/content/preview",
        json={
            "workspace_id": workspace,
            "title_template": "hi [[tags:khong-co:2]]",
            "account_count": 3,
        },
    )
    data = r.json()
    assert data["unknown_pools"] == ["khong-co"]
    assert "No hashtag set named" in data["warning"]


async def test_a_hashtag_pool_collapses_the_collision_risk(client, workspace):
    """Day la ly do dung tui rut ngau nhien thay vi mot khoi hashtag co dinh."""
    plain = (
        await client.post("/content/preview", json={"title_template": "{a|b}", "account_count": 20})
    ).json()

    created = (
        await client.post(
            "/hashtag-sets",
            json={
                "workspace_id": workspace,
                "name": "wide",
                "tags": [f"#t{i}" for i in range(20)],
            },
        )
    ).json()

    with_tags = (
        await client.post(
            "/content/preview",
            json={
                "workspace_id": workspace,
                "title_template": "{a|b} [[tags:wide:4]]",
                "account_count": 20,
            },
        )
    ).json()

    assert plain["collision_risk"] > 0.9
    assert with_tags["collision_risk"] < 0.01

    await client.delete(f"/hashtag-sets/{created['id']}")


# ------------------------------------------------------------------------ CRUD


async def test_account_edit_keeps_the_secrets_it_was_not_told_about(client, workspace, tag):
    """Sua rieng mat khau khong duoc lam mat totp_seed - nguoi sua khong doc lai duoc no."""
    persona = (await client.post("/personas", json={"workspace_id": workspace, "name": "p"})).json()
    account = (
        await client.post(
            "/accounts",
            json={
                "persona_id": persona["id"],
                "platform": "threads",
                "handle": f"crud_test_acc_{tag}",
                "secrets": {"password": "old", "totp_seed": "SEEDVALUE"},
            },
        )
    ).json()

    r = await client.patch(
        f"/accounts/{account['id']}", json={"daily_cap": 9, "secrets": {"password": "new"}}
    )
    assert r.status_code == 200
    assert r.json()["daily_cap"] == 9

    from seeding.db import SessionLocal
    from seeding.models import Account

    async with SessionLocal() as s:
        stored = (await s.get(Account, __import__("uuid").UUID(account["id"]))).get_secrets()
    assert stored["password"] == "new"
    assert stored["totp_seed"] == "SEEDVALUE"

    await client.delete(f"/accounts/{account['id']}")


async def test_a_proxy_bound_to_a_profile_cannot_be_deleted(client, workspace, tag):
    """Xoa proxy cua profile dang chay se lam no mo trinh duyet bang IP that."""
    persona = (
        await client.post("/personas", json={"workspace_id": workspace, "name": "p2"})
    ).json()
    account = (
        await client.post(
            "/accounts",
            json={
                "persona_id": persona["id"],
                "platform": "threads",
                "handle": f"proxy_bound_acc_{tag}",
            },
        )
    ).json()
    proxy = (
        await client.post(
            "/proxies", json={"label": f"bound_{tag}", "host": "10.0.0.1", "port": 8080}
        )
    ).json()
    await client.post("/profiles", json={"account_id": account["id"], "proxy_id": proxy["id"]})

    r = await client.delete(f"/proxies/{proxy['id']}")
    assert r.status_code == 409
    assert "real IP" in r.json()["detail"]

    await client.delete(f"/accounts/{account['id']}")
    await client.delete(f"/proxies/{proxy['id']}")


async def test_proxy_scheme_can_be_changed_to_socks5(client, tag):
    proxy = (
        await client.post(
            "/proxies",
            json={"label": f"socks_{tag}", "host": "10.0.0.2", "port": 1080, "scheme": "socks5"},
        )
    ).json()

    r = await client.patch(f"/proxies/{proxy['id']}", json={"scheme": "socks5", "port": 1081})
    assert r.status_code == 200
    assert r.json()["port"] == 1081

    bad = await client.patch(f"/proxies/{proxy['id']}", json={"scheme": "carrier-pigeon"})
    assert bad.status_code == 422

    await client.delete(f"/proxies/{proxy['id']}")


async def test_content_used_by_a_campaign_cannot_be_deleted(client, workspace, tag):
    persona = (
        await client.post("/personas", json={"workspace_id": workspace, "name": "p3"})
    ).json()
    account = (
        await client.post(
            "/accounts",
            json={
                "persona_id": persona["id"],
                "platform": "reddit",
                "handle": f"camp_del_acc_{tag}",
            },
        )
    ).json()
    content = (
        await client.post(
            "/content", json={"workspace_id": workspace, "title_template": "{a|b} post"}
        )
    ).json()
    await client.post(f"/content/{content['id']}/approve")

    campaign = (
        await client.post(
            "/campaigns",
            json={
                "workspace_id": workspace,
                "content_item_id": content["id"],
                "name": "for deletion test",
                "groups": [
                    {
                        "name": "g",
                        "platform": "reddit",
                        "target": {"subreddit": "test"},
                        "account_ids": [account["id"]],
                    }
                ],
            },
        )
    ).json()

    blocked = await client.delete(f"/content/{content['id']}")
    assert blocked.status_code == 409
    assert "campaign" in blocked.json()["detail"]

    assert (await client.delete(f"/campaigns/{campaign['id']}")).status_code == 200
    assert (await client.delete(f"/content/{content['id']}")).status_code == 200
    await client.delete(f"/accounts/{account['id']}")


# -------------------------------------------------- profile CRUD, groups, test-all


async def test_profile_can_be_rebound_only_on_purpose(client, workspace, tag):
    """Doi proxy pha bat bien mot acc mot IP, nen phai noi ro y dinh moi cho qua."""
    persona = (
        await client.post("/personas", json={"workspace_id": workspace, "name": f"pr_{tag}"})
    ).json()
    account = (
        await client.post(
            "/accounts",
            json={
                "persona_id": persona["id"],
                "platform": "threads",
                "handle": f"rebind_{tag}",
            },
        )
    ).json()
    first = (
        await client.post("/proxies", json={"label": f"p1_{tag}", "host": "10.1.1.1", "port": 8080})
    ).json()
    second = (
        await client.post("/proxies", json={"label": f"p2_{tag}", "host": "10.1.1.2", "port": 8080})
    ).json()
    profile = (
        await client.post("/profiles", json={"account_id": account["id"], "proxy_id": first["id"]})
    ).json()

    blocked = await client.patch(f"/profiles/{profile['id']}", json={"proxy_id": second["id"]})
    assert blocked.status_code == 409
    assert "one-account-one-IP" in blocked.json()["detail"]

    forced = await client.patch(
        f"/profiles/{profile['id']}",
        json={"proxy_id": second["id"], "force_rebind": True, "rebind_reason": "old one died"},
    )
    assert forced.status_code == 200
    assert forced.json()["proxy_label"] == f"p2_{tag}"

    await client.delete(f"/accounts/{account['id']}")
    await client.delete(f"/proxies/{first['id']}")
    await client.delete(f"/proxies/{second['id']}")


async def test_deleting_a_profile_with_a_session_needs_force(client, workspace, tag):
    """Xoa profile la vut ca cookie jar lan fingerprint - phai chac chan moi lam."""
    from seeding.core import profiles as profiles_mod
    from seeding.db import SessionLocal
    from seeding.models import Profile

    persona = (
        await client.post("/personas", json={"workspace_id": workspace, "name": f"pd_{tag}"})
    ).json()
    account = (
        await client.post(
            "/accounts",
            json={"persona_id": persona["id"], "platform": "threads", "handle": f"pdel_{tag}"},
        )
    ).json()
    profile = (await client.post("/profiles", json={"account_id": account["id"]})).json()

    # Gia lap da dang nhap: luu mot cookie jar.
    async with SessionLocal() as s:
        stored = await s.get(Profile, uuid.UUID(profile["id"]))
        await profiles_mod.save_cookies(s, stored, {"cookies": [{"name": "s", "value": "1"}]})

    blocked = await client.delete(f"/profiles/{profile['id']}")
    assert blocked.status_code == 409
    assert "sign in by hand again" in blocked.json()["detail"]

    forced = await client.delete(f"/profiles/{profile['id']}", params={"force": True})
    assert forced.status_code == 200

    await client.delete(f"/accounts/{account['id']}")


async def test_campaign_groups_are_listed_with_their_own_counts(client, workspace, tag):
    """Tang giua cua man hinh ba cot: mot chien dich co nhieu nhom, moi nhom mot muc tieu."""
    persona = (
        await client.post("/personas", json={"workspace_id": workspace, "name": f"g_{tag}"})
    ).json()
    reddit_acc = (
        await client.post(
            "/accounts",
            json={"persona_id": persona["id"], "platform": "reddit", "handle": f"grp_r_{tag}"},
        )
    ).json()
    threads_acc = (
        await client.post(
            "/accounts",
            json={"persona_id": persona["id"], "platform": "threads", "handle": f"grp_t_{tag}"},
        )
    ).json()

    content = (
        await client.post(
            "/content", json={"workspace_id": workspace, "title_template": "{a|b} grouped"}
        )
    ).json()
    await client.post(f"/content/{content['id']}/approve")

    campaign = (
        await client.post(
            "/campaigns",
            json={
                "workspace_id": workspace,
                "content_item_id": content["id"],
                "name": f"grouped {tag}",
                "groups": [
                    {
                        "name": "reddit side",
                        "platform": "reddit",
                        "target": {"subreddit": "test"},
                        "account_ids": [reddit_acc["id"]],
                    }
                ],
            },
        )
    ).json()
    await client.post(f"/campaigns/{campaign['id']}/plan")

    added = await client.post(
        f"/campaigns/{campaign['id']}/groups",
        json={
            "name": "threads side",
            "platform": "threads",
            "account_ids": [threads_acc["id"]],
        },
    )
    assert added.status_code == 200, added.text

    groups = (await client.get(f"/campaigns/{campaign['id']}/groups")).json()
    assert len(groups) == 2
    assert {g["platform"] for g in groups} == {"reddit", "threads"}
    assert all(g["total_jobs"] == 1 for g in groups)

    # Loc job theo nhom - day la cot thu ba cua man hinh.
    only = (
        await client.get(f"/campaigns/{campaign['id']}/jobs", params={"group_id": groups[0]["id"]})
    ).json()
    assert len(only) == 1
    assert only[0]["group_id"] == groups[0]["id"]

    everything = (await client.get(f"/campaigns/{campaign['id']}/jobs")).json()
    assert len(everything) == 2

    await client.delete(f"/campaigns/{campaign['id']}")
    await client.delete(f"/content/{content['id']}")
    await client.delete(f"/accounts/{reddit_acc['id']}")
    await client.delete(f"/accounts/{threads_acc['id']}")


async def test_test_all_reports_duplicate_exit_ips(client, tag):
    """Hai proxy ra cung mot IP nghia la ban chi co MOT loi ra, khong phai hai."""
    made = []
    for i in range(2):
        made.append(
            (
                await client.post(
                    "/proxies",
                    json={"label": f"all_{tag}_{i}", "host": f"10.2.2.{i}", "port": 8080},
                )
            ).json()
        )

    r = await client.post("/proxies/test-all")
    assert r.status_code == 200
    data = r.json()

    assert data["tested"] >= 2
    assert isinstance(data["duplicate_exit_ips"], list)
    # Proxy gia thi khong bao gio pass - va do la ket qua dung.
    labels = {row["label"] for row in data["results"]}
    assert {p["label"] for p in made} <= labels

    for p in made:
        await client.delete(f"/proxies/{p['id']}")
