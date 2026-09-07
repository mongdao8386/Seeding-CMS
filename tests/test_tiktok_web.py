"""Web API cua TikTok bang HTTP: doc feed, tha tim, theo doi, binh luan - voi client gia.

Cai duoc kiem la lop cua minh: tham so co nhat quan voi UA cua signer khong, body duoc
doc thanh ket qua ra sao, va nhat la LUAT thu lai - tha tim/theo doi thu lai duoc,
binh luan thi khong.
"""

import uuid

import httpx
import pytest

from seeding.core import tiktok_web as tw
from seeding.models import Profile, Proxy

UA_MAC = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15"

FEED = {
    "status_code": 0,
    "itemList": [
        {
            "id": "111",
            "desc": "video mot",
            "author": {"uniqueId": "creator.a", "id": "1", "secUid": "MS4wLjABAAAAa"},
            "stats": {"playCount": 4_400_000, "diggCount": 301_100},
        },
        {
            "id": "222",
            "desc": "video hai",
            "author": {"uniqueId": "creator.b", "id": "2", "secUid": "MS4wLjABAAAAb"},
            "stats": {"playCount": 900, "diggCount": 10},
        },
        {"id": "333", "author": {}},  # khong co uniqueId -> bo
    ],
}


class _FakeSigner:
    async def user_agent(self) -> str:
        return UA_MAC

    async def sign(self, url: str) -> dict:
        return {"signed_url": url + "&X-Bogus=fake&X-Gnarly=fake"}


class _Script:
    """Client httpx gia: tra ve theo kich ban, ghi lai request."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict]] = []

    def __call__(self, *, proxy, cookies, headers):
        self.proxy, self.cookies, self.headers = proxy, cookies, headers

        script = self

        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return None

            async def get(self, url, **kw):
                return await self._next("GET", url, kw)

            async def post(self, url, **kw):
                return await self._next("POST", url, kw)

            async def _next(self, method, url, kw):
                script.calls.append((method, url, kw))
                nxt = script.responses.pop(0)
                if isinstance(nxt, Exception):
                    raise nxt
                status, body = nxt
                content = (
                    body
                    if isinstance(body, bytes)
                    else (b"" if body is None else httpx.Response(200, json=body).content)
                )
                return httpx.Response(status, content=content, request=httpx.Request(method, url))

        return _Client()


def _profile(with_proxy=True) -> Profile:
    p = Profile(id=uuid.uuid4(), proxy_id=uuid.uuid4() if with_proxy else None)
    p.proxy = Proxy(host="1.2.3.4", port=8080, scheme="http", username=None) if with_proxy else None
    p.set_cookies(
        {
            "cookies": [
                {"name": "sessionid", "value": "s"},
                {"name": "msToken", "value": "MS"},
                {"name": "tt_csrf_token", "value": "CSRF"},
                {"name": "s_v_web_id", "value": "VFP"},
            ]
        }
    )
    return p


# ------------------------------------------------------------- thuan tuy


def test_feed_parser_drops_items_without_an_author():
    items = tw.parse_feed(FEED)
    assert [i.item_id for i in items] == ["111", "222"]
    assert items[0].author_sec_uid == "MS4wLjABAAAAa"
    assert items[0].url == "https://www.tiktok.com/@creator.a/video/111"


def test_params_follow_the_signer_ua_not_the_profile():
    """UA Mac -> os=mac, MacIntel. X-Gnarly bam UA; query khai os khac UA la mau thuan."""
    p = tw.base_params(_profile(), {"msToken": "MS", "s_v_web_id": "VFP"}, UA_MAC)
    assert (p["os"], p["browser_platform"]) == ("mac", "MacIntel")
    assert p["msToken"] == "MS" and p["verifyFp"] == "VFP"
    assert p["region"] == "VN" and p["tz_name"] == "Asia/Ho_Chi_Minh"


def test_device_id_is_stable_per_profile_and_19_digits():
    pid = uuid.uuid4()
    assert tw.device_id(pid) == tw.device_id(pid)
    assert len(tw.device_id(pid)) == 19 and tw.device_id(pid).isdigit()
    assert tw.device_id(pid) != tw.device_id(uuid.uuid4())


def test_classify_maps_codes():
    assert tw.classify({"status_code": 0}, idempotent=True).ok
    r = tw.classify({"status_code": 10201, "status_msg": "please login"}, idempotent=True)
    assert r.needs_human and not r.retryable
    r = tw.classify({"status_code": 5, "status_msg": "rate"}, idempotent=True)
    assert r.retryable and not r.needs_human
    r = tw.classify({"status_code": 5, "status_msg": "rate"}, idempotent=False)
    assert not r.retryable


def test_refuses_a_profile_without_a_proxy():
    with pytest.raises(ValueError):
        tw.TikTokWeb(_profile(with_proxy=False), signer=_FakeSigner())


# --------------------------------------------------------------- qua client gia


async def test_feed_is_retried_when_tiktok_answers_empty():
    """200 rong la cach TikTok tu choi chu ky - ky lai va thu lai, khong bo cuoc ngay."""
    script = _Script([(200, None), (200, FEED)])
    async with tw.TikTokWeb(_profile(), signer=_FakeSigner(), client_factory=script) as tt:
        items = await tt.feed()
    assert len(items) == 2
    assert len(script.calls) == 2
    assert script.headers["User-Agent"] == UA_MAC
    assert script.proxy == "http://1.2.3.4:8080"


async def test_like_is_ok_only_with_is_digg_one():
    script = _Script([(200, {"status_code": 0, "is_digg": 1})])
    async with tw.TikTokWeb(_profile(), signer=_FakeSigner(), client_factory=script) as tt:
        assert (await tt.like("111")).ok
    method, url, kw = script.calls[0]
    assert method == "POST" and "aweme_id=111" in url and "type=1" in url
    assert kw["headers"]["tt-csrf-token"] == "CSRF"

    script = _Script([(200, {"status_code": 0, "is_digg": 0})])
    async with tw.TikTokWeb(_profile(), signer=_FakeSigner(), client_factory=script) as tt:
        res = await tt.like("111")
    assert not res.ok and "is_digg=0" in res.detail


async def test_unknown_outcome_retries_a_like_but_hands_a_comment_to_a_human():
    """Tha tim hai lan van la mot tim. Binh luan hai lan la hai binh luan."""
    script = _Script([(200, None)])
    async with tw.TikTokWeb(_profile(), signer=_FakeSigner(), client_factory=script) as tt:
        res = await tt.like("111")
    assert res.retryable and not res.needs_human

    script = _Script([httpx.ReadTimeout("treo")])
    async with tw.TikTokWeb(_profile(), signer=_FakeSigner(), client_factory=script) as tt:
        res = await tt.comment("111", "hay qua")
    assert res.needs_human and not res.retryable


async def test_follow_sends_both_ids_and_is_sent_once():
    script = _Script([(200, {"status_code": 0, "follow_status": 1})])
    async with tw.TikTokWeb(_profile(), signer=_FakeSigner(), client_factory=script) as tt:
        assert (await tt.follow("1", "MS4wLjABAAAAa")).ok
    assert len(script.calls) == 1
    _, url, _ = script.calls[0]
    assert "user_id=1" in url and "sec_user_id=MS4wLjABAAAAa" in url and "action_type=1" in url


async def test_user_detail_is_normalised():
    body = {
        "userInfo": {
            "user": {"id": "9", "secUid": "S", "uniqueId": "x"},
            "stats": {"followerCount": 12},
        }
    }
    script = _Script([(200, body)])
    async with tw.TikTokWeb(_profile(), signer=_FakeSigner(), client_factory=script) as tt:
        u = await tt.user("x")
    assert u == {"id": "9", "secUid": "S", "uniqueId": "x", "followers": 12}
