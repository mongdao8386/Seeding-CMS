"""Dang bai TikTok bang HTTP - kiem ca chuoi 7 buoc tren mot TikTok gia.

Khong cham mang. `httpx.MockTransport` dong vai TikTok + kho upload, mot signer gia
ky "chu ky". Cai duoc kiem la nhung thu THUOC VE minh: thu tu buoc, header nao di
kem buoc nao, phan loai ket qua - dac biet la bat bien "buoc 7 khong bao gio tu thu
lai". Hinh dang phan hoi cua TikTok lay tu bai that da dang (07/09/2026).
"""

import datetime as dt
import json
import uuid
from pathlib import Path

import httpx
import pytest

from seeding.domain.models import Account, AccountStatus, Platform, Profile, Proxy, Variant
from seeding.platforms.tiktok import publish as mod
from seeding.platforms.tiktok.signer import SignerNotReady

# Phan hoi THAT cua buoc 7 (bai dau tien dang bang duong HTTP).
REAL_POST_RESPONSE = {
    "extra": {
        "fatal_item_ids": [],
        "logid": "202609072338381C2FFA02E7DEECF52DE6",
        "now": 1788795518000,
    },
    "log_pb": {"impr_id": "202609072338381C2FFA02E7DEECF52DE6"},
    "project_id": "7682818173327004693",
    "project_status": 1,
    "single_post_resp_list": [
        {"batch_index": 0, "item_id": "7682818232956341524", "status_code": 0, "status_msg": ""}
    ],
    "status_code": 0,
    "status_msg": "",
}

APPLY_RESPONSE = {
    "Result": {
        "InnerUploadAddress": {
            "UploadNodes": [
                {
                    "Vid": "vTEST",
                    "UploadHost": "tos-test-up.tiktokcdn.com",
                    "SessionKey": "SESSION",
                    "UploadHeader": {"X-Storage-U": "u1"},
                    "StoreInfos": [
                        {
                            "StoreUri": "tos/abc",
                            "Auth": "STORE-AUTH",
                            "UploadID": "UPID",
                            "UploadHeader": {},
                        }
                    ],
                }
            ]
        }
    }
}


# ------------------------------------------------------------------- fixtures


class FakeSigner:
    def __init__(self, *, ready: bool = True) -> None:
        self.ready = ready
        self.signed: list[str] = []

    async def user_agent(self) -> str:
        if not self.ready:
            raise SignerNotReady("signer down")
        return "UA-TEST"

    async def sign(self, url: str) -> dict:
        self.signed.append(url)
        return {
            "signed_url": f"{url}&X-Bogus=BOGUS&X-Gnarly=GNARLY",
            "x-bogus": "BOGUS",
            "x-gnarly": "GNARLY",
        }


class FakeTikTok:
    """Dinh tuyen theo URL. Ghi lai moi request de test doc thu tu va header."""

    def __init__(
        self, *, post_response: dict | None = None, fail_apply_once: bool = False, post_raises=None
    ):
        self.requests: list[httpx.Request] = []
        self.post_response = post_response or REAL_POST_RESPONSE
        self.fail_apply_once = fail_apply_once
        self.post_raises = post_raises

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        if "/api/v1/web/project/create/" in url:
            return httpx.Response(200, json={"status_code": 0, "project": {"project_id": "190"}})
        if "/api/v1/video/upload/auth/" in url:
            return httpx.Response(
                200,
                json={
                    "video_token_v5": {
                        "access_key_id": "AK",
                        "secret_acess_key": "SK",
                        "session_token": "TOK",
                    }
                },
            )
        if "Action=ApplyUploadInner" in url:
            if self.fail_apply_once:
                self.fail_apply_once = False
                raise httpx.ReadTimeout("proxy treo", request=request)
            return httpx.Response(200, json=APPLY_RESPONSE)
        if "phase=transfer" in url:
            return httpx.Response(200, json={})
        if "phase=finish" in url:
            return httpx.Response(200, json={"success": 0})
        if "Action=CommitUploadInner" in url:
            return httpx.Response(200, json={"Result": {"Results": [{"Vid": "vTEST"}]}})
        if "/tiktok/web/project/post/v1/" in url:
            if self.post_raises is not None:
                raise self.post_raises(request=request)
            return httpx.Response(200, json=self.post_response)
        return httpx.Response(404, text=f"unrouted {url}")

    def factory(self, *, proxy, cookies, headers) -> httpx.AsyncClient:
        self.proxy = proxy
        return httpx.AsyncClient(
            transport=httpx.MockTransport(self.handle), cookies=cookies, headers=headers
        )

    def paths(self) -> list[str]:
        return [r.url.path for r in self.requests]


def _account() -> Account:
    return Account(platform=Platform.TIKTOK, handle="acc_thu", status=AccountStatus.WARMING)


def _profile(monkeypatch, *, proxy: bool = True, cookies: bool = True) -> Profile:
    p = Profile(cookies_enc="da-ma-hoa" if cookies else None)
    if proxy:
        p.proxy = Proxy(
            label="P", scheme="http", host="proxy.test", port=3128, username="u", password_enc=None
        )
        p.proxy_id = uuid.uuid4()
    monkeypatch.setattr(
        Profile,
        "get_cookies",
        lambda self: {
            "cookies": [{"name": "sessionid", "value": "S"}, {"name": "msToken", "value": "MS"}]
        },
    )
    return p


def _variant(tmp_path: Path, *, media: bool = True) -> Variant:
    path = None
    if media:
        f = tmp_path / "clip.mp4"
        f.write_bytes(b"\x00" * 1024)
        path = str(f)
    return Variant(
        title="Trưa nay đợi hoài", body="Cả nhà thấy sao ạ? #fyp", media_variant_ref=path
    )


def _adapter(
    tiktok: FakeTikTok, signer: FakeSigner | None = None, browser=None
) -> mod.TikTokHttpAdapter:
    return mod.TikTokHttpAdapter(
        signer=signer or FakeSigner(),
        client_factory=tiktok.factory,
    )


# ----------------------------------------------------------------- happy path


async def test_posts_through_all_seven_steps_in_order(monkeypatch, tmp_path):
    tiktok = FakeTikTok()
    signer = FakeSigner()
    result = await _adapter(tiktok, signer).publish(
        _account(), _variant(tmp_path), {"kind": "post"}, profile=_profile(monkeypatch)
    )

    assert result.ok, result.error
    assert result.remote_id == "7682818232956341524"
    assert result.remote_url == "https://www.tiktok.com/@acc_thu/video/7682818232956341524"
    assert result.metrics["path"] == "http"
    assert result.metrics["video_id"] == "vTEST"

    assert tiktok.paths() == [
        "/api/v1/web/project/create/",
        "/api/v1/video/upload/auth/",
        "/top/v1",
        "/tos/abc",  # part 1
        "/tos/abc",  # finish
        "/top/v1",
        "/tiktok/web/project/post/v1/",
    ]


async def test_every_request_carries_the_signers_user_agent_and_the_account_cookies(
    monkeypatch, tmp_path
):
    """X-Gnarly bam md5(UA): lech UA giua signer va request la chu ky vo gia tri."""
    tiktok = FakeTikTok()
    await _adapter(tiktok).publish(
        _account(), _variant(tmp_path), {}, profile=_profile(monkeypatch)
    )

    for r in tiktok.requests:
        assert r.headers["user-agent"] == "UA-TEST"
    tiktok_requests = [r for r in tiktok.requests if r.url.host == "www.tiktok.com"]
    assert all("sessionid=S" in r.headers.get("cookie", "") for r in tiktok_requests)


async def test_the_publish_request_uses_the_signed_url_verbatim(monkeypatch, tmp_path):
    tiktok = FakeTikTok()
    signer = FakeSigner()
    await _adapter(tiktok, signer).publish(
        _account(), _variant(tmp_path), {}, profile=_profile(monkeypatch)
    )

    post = tiktok.requests[-1]
    assert post.url.params["X-Bogus"] == "BOGUS"
    assert post.url.params["X-Gnarly"] == "GNARLY"
    assert post.url.params["msToken"] == "MS", "msToken cua TAI KHOAN, khong phai cua signer"
    body = json.loads(post.content)
    assert body["single_post_req_list"][0]["video_id"] == "vTEST"
    assert (
        body["single_post_req_list"][0]["single_post_feature_info"]["text"]
        == "Trưa nay đợi hoài\n\nCả nhà thấy sao ạ? #fyp"
    )


async def test_parts_go_to_the_upload_host_with_store_auth_and_crc(monkeypatch, tmp_path):
    tiktok = FakeTikTok()
    await _adapter(tiktok).publish(
        _account(), _variant(tmp_path), {}, profile=_profile(monkeypatch)
    )

    part = next(r for r in tiktok.requests if "phase=transfer" in str(r.url))
    assert part.url.host == "tos-test-up.tiktokcdn.com"
    assert part.headers["authorization"] == "STORE-AUTH"
    assert part.headers["x-storage-u"] == "u1", "UploadHeader cua node phai di kem tung part"
    assert part.headers["content-crc32"] == mod.crc32_hex(b"\x00" * 1024)
    assert len(part.headers["content-crc32"]) == 8


async def test_the_proxy_of_the_profile_is_the_one_used(monkeypatch, tmp_path):
    tiktok = FakeTikTok()
    await _adapter(tiktok).publish(
        _account(), _variant(tmp_path), {}, profile=_profile(monkeypatch)
    )
    assert tiktok.proxy == "http://u:@proxy.test:3128"


# ------------------------------------------------------------ phan loai loi


async def test_a_proxy_stall_on_step_3_is_retried_and_still_succeeds(monkeypatch, tmp_path):
    """Do that: 1/8 request bi proxy nuot 40-180s. Thu lai la du, khong can nguoi."""
    tiktok = FakeTikTok(fail_apply_once=True)
    result = await _adapter(tiktok).publish(
        _account(), _variant(tmp_path), {}, profile=_profile(monkeypatch)
    )
    assert result.ok, result.error
    assert tiktok.paths().count("/top/v1") == 3  # apply x2 (1 treo) + commit


async def test_signer_down_means_retry_later_and_no_request_reaches_tiktok(monkeypatch, tmp_path):
    """Signer chet thi khong duoc tao project rong tren tai khoan roi moi bao loi."""
    tiktok = FakeTikTok()
    result = await _adapter(tiktok, FakeSigner(ready=False)).publish(
        _account(), _variant(tmp_path), {}, profile=_profile(monkeypatch)
    )
    assert not result.ok
    assert result.retryable
    assert not result.needs_human
    assert tiktok.requests == []


async def test_tiktok_refusing_the_post_is_final_not_retried(monkeypatch, tmp_path):
    """TikTok noi ro "khong dang" -> that bai ro rang, mang thong bao cua no, khong retry."""
    tiktok = FakeTikTok(post_response={"status_code": 3, "status_msg": "video is being reviewed"})
    result = await _adapter(tiktok).publish(
        _account(), _variant(tmp_path), {}, profile=_profile(monkeypatch)
    )
    assert not result.ok
    assert not result.retryable
    assert not result.needs_human
    assert "status_code=3" in result.error and "video is being reviewed" in result.error


async def test_no_answer_after_sending_the_publish_goes_to_a_human(monkeypatch, tmp_path):
    """BAT BIEN: da gui buoc 7 ma khong biet ket qua thi KHONG thu lai - co the da len."""
    tiktok = FakeTikTok(
        post_raises=lambda request: httpx.ReadTimeout("mat ket noi", request=request)
    )
    result = await _adapter(tiktok).publish(
        _account(), _variant(tmp_path), {}, profile=_profile(monkeypatch)
    )
    assert not result.ok
    assert result.needs_human
    assert not result.retryable
    assert "MAY be live" in result.error


async def test_status_zero_without_item_id_also_goes_to_a_human(monkeypatch, tmp_path):
    tiktok = FakeTikTok(post_response={"status_code": 0, "single_post_resp_list": []})
    result = await _adapter(tiktok).publish(
        _account(), _variant(tmp_path), {}, profile=_profile(monkeypatch)
    )
    assert not result.ok and result.needs_human and not result.retryable


async def test_a_dead_session_at_step_1_goes_to_a_human(monkeypatch, tmp_path):
    tiktok = FakeTikTok()
    original = tiktok.handle

    def handle(request):
        if "/project/create/" in str(request.url):
            return httpx.Response(200, json={"status_code": 8, "status_msg": "please login"})
        return original(request)

    tiktok.handle = handle
    result = await _adapter(tiktok).publish(
        _account(), _variant(tmp_path), {}, profile=_profile(monkeypatch)
    )
    assert not result.ok and result.needs_human and not result.retryable


async def test_text_only_content_is_refused_before_any_request(monkeypatch, tmp_path):
    tiktok = FakeTikTok()
    result = await _adapter(tiktok).publish(
        _account(), _variant(tmp_path, media=False), {}, profile=_profile(monkeypatch)
    )
    assert not result.ok and not result.retryable
    assert "cannot post text alone" in result.error
    assert tiktok.requests == []


async def test_no_proxy_is_refused_before_any_request(monkeypatch, tmp_path):
    tiktok = FakeTikTok()
    result = await _adapter(tiktok).publish(
        _account(), _variant(tmp_path), {}, profile=_profile(monkeypatch, proxy=False)
    )
    assert not result.ok and "no proxy" in result.error
    assert tiktok.requests == []


def test_extract_item_id_reads_the_real_response_shape():
    assert mod.extract_item_id(REAL_POST_RESPONSE) == "7682818232956341524"
    assert mod.extract_item_id({"status_code": 0, "data": {"item_id": "x"}}) is None
    assert mod.extract_item_id({}) is None


def test_sigv4_is_deterministic_and_binds_query_and_body():
    now = dt.datetime(2026, 9, 7, 15, 0, 0, tzinfo=dt.UTC)
    url = (
        "https://www.tiktok.com/top/v1?Version=2020-11-19&Action=ApplyUploadInner&SpaceName=tiktok"
    )
    a = mod.sigv4_headers("GET", url, b"", ak="AK", sk="SK", token="TOK", now=now)
    b = mod.sigv4_headers("GET", url, b"", ak="AK", sk="SK", token="TOK", now=now)
    assert a == b
    assert a["x-amz-date"] == "20260907T150000Z"
    assert a["x-amz-security-token"] == "TOK"
    # `host` nam trong SignedHeaders: day la hinh dang TikTok da chap nhan tren bai that.
    assert a["Authorization"].startswith(
        "AWS4-HMAC-SHA256 Credential=AK/20260907/ap-singapore-1/vod/aws4_request, "
        "SignedHeaders=host;x-amz-content-sha256;x-amz-date;x-amz-security-token, Signature="
    )
    # Doi body hoac query thi chu ky phai doi - neu khong, chu ky khong bao ve gi ca.
    c = mod.sigv4_headers("GET", url, b"x", ak="AK", sk="SK", token="TOK", now=now)
    d = mod.sigv4_headers("GET", url + "&FileSize=1", b"", ak="AK", sk="SK", token="TOK", now=now)
    assert a["Authorization"] != c["Authorization"] != d["Authorization"]


def test_proxy_url_quotes_passwords_with_at_signs(monkeypatch):
    p = Proxy(label="P", scheme="http", host="h.test", port=8080, username="user", password_enc="x")
    monkeypatch.setattr(Proxy, "get_password", lambda self: "p@ss:w/rd")
    assert mod.proxy_url(p) == "http://user:p%40ss%3Aw%2Frd@h.test:8080"


def test_caption_matches_the_browser_adapters_join():
    assert mod.caption_for(Variant(title="A", body="B")) == "A\n\nB"
    assert mod.caption_for(Variant(title="A", body=None)) == "A"


@pytest.mark.parametrize("n", [1, 5 * 1024 * 1024, 5 * 1024 * 1024 + 1])
def test_crc32_hex_is_always_eight_lowercase_hex_chars(n):
    crc = mod.crc32_hex(b"\xff" * n)
    assert len(crc) == 8 and crc == crc.lower() and int(crc, 16) >= 0
