"""Web API cua TikTok, goi thang bang HTTP qua proxy cua tai khoan - doc feed, tha tim,
theo doi, binh luan. Khong mo trinh duyet.

Vi sao: trang web TikTok khong tai noi qua proxy dan cu (90-300s), nhung cac endpoint
JSON ma chinh trang do goi thi tra loi trong 1-3 giay qua cung con proxy. Do that
07/09/2026: recommend/item_list ve 160-230KB, 7-8 video xu huong Viet Nam, 1-3s.

Ba thu phai nhat quan tren MOI request, neu khong TikTok tra ve 200 rong:
  - Chu ky X-Bogus / X-Gnarly tu signer (tools/tiktok-signer) cho DUNG URL gui di.
  - User-Agent = UA ma signer dang chay (X-Gnarly bam md5(UA)).
  - Cookie cua tai khoan (sessionid, msToken, tt_csrf_token...) va msToken cua no trong
    query - signer duoc va de giu msToken co san thay vi ghi de bang cua no.

Luat cho hanh dong (POST):
  - Tha tim va theo doi la idempotent tren TikTok (tha lai van la da tha) -> khong biet
    ket qua thi thu lai duoc.
  - Binh luan thi KHONG: gui lai la hai binh luan giong nhau duoi cung mot video - day
    sang hang doi cho nguoi.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

import httpx
import structlog

from seeding.core.signer import Signer
from seeding.models import Profile, Proxy

log = structlog.get_logger(__name__)

ORIGIN = "https://www.tiktok.com"
READ_TRIES = 3
TIMEOUT = 60.0

# Dau hieu TikTok dang doi nguoi that: ma loi va chuoi hay gap trong body.
_HUMAN_CODES = {10201, 10202, 10204, 10221, 8, 3006}
_HUMAN_WORDS = ("captcha", "verify", "verification", "login", "log in")


@dataclass(frozen=True, slots=True)
class FeedItem:
    item_id: str
    author_handle: str
    author_id: str
    author_sec_uid: str
    views: int
    likes: int
    desc: str

    @property
    def url(self) -> str:
        return f"{ORIGIN}/@{self.author_handle}/video/{self.item_id}"


@dataclass(slots=True)
class ActionResult:
    ok: bool
    detail: str
    retryable: bool = False
    needs_human: bool = False
    raw: dict = field(default_factory=dict)


ClientFactory = Callable[..., httpx.AsyncClient]


def device_id(profile_id: Any) -> str:
    """19 chu so, on dinh theo profile. TikTok web gui device_id la mot so nhu the; doi
    moi lan la mot dau vet, con dung mot so co dinh cho ca doi thi la dau vet lon hon."""
    h = int(hashlib.sha256(str(profile_id).encode()).hexdigest(), 16)
    return str(7_000_000_000_000_000_000 + h % 999_999_999_999_999_999)


def base_params(profile: Profile, cookies: dict[str, str], user_agent: str) -> dict[str, str]:
    """Bo tham so chuan ma tiktok_web gui kem moi request, dia phuong hoa Viet Nam.

    `os`/`browser_platform` phai khop voi UA cua signer, khong phai voi profile: request
    mang UA cua signer, va mot UA Mac khai os=windows la mau thuan tu ngay trong query.
    """
    mac = "Mac" in user_agent
    return {
        "WebIdLastTime": str(int(time.time())),
        "aid": "1988",
        "app_language": "vi",
        "app_name": "tiktok_web",
        "browser_language": "vi-VN",
        "browser_name": "Mozilla",
        "browser_online": "true",
        "browser_platform": "MacIntel" if mac else "Win32",
        "browser_version": "5.0",
        "channel": "tiktok_web",
        "cookie_enabled": "true",
        "device_id": device_id(profile.id),
        "device_platform": "web_pc",
        "focus_state": "true",
        "history_len": "3",
        "is_fullscreen": "false",
        "is_page_visible": "true",
        "language": "vi",
        "os": "mac" if mac else "windows",
        "priority_region": "VN",
        "region": "VN",
        "screen_height": "1080",
        "screen_width": "1920",
        "tz_name": "Asia/Ho_Chi_Minh",
        "webcast_language": "vi",
        "verifyFp": cookies.get("s_v_web_id", ""),
        "msToken": cookies.get("msToken", ""),
    }


def cookie_dict(storage_state: dict | None) -> dict[str, str]:
    return {
        c["name"]: c["value"] for c in (storage_state or {}).get("cookies", []) if c.get("name")
    }


def proxy_url(proxy: Proxy) -> str:
    auth = f"{proxy.username}:{proxy.get_password() or ''}@" if proxy.username else ""
    return f"{(proxy.scheme or 'http').lower()}://{auth}{proxy.host}:{proxy.port}"


def parse_feed(body: dict) -> list[FeedItem]:
    out = []
    for v in body.get("itemList") or []:
        a = v.get("author") or {}
        st = v.get("stats") or {}
        if not v.get("id") or not a.get("uniqueId"):
            continue
        out.append(
            FeedItem(
                item_id=str(v["id"]),
                author_handle=str(a["uniqueId"]),
                author_id=str(a.get("id") or ""),
                author_sec_uid=str(a.get("secUid") or ""),
                views=int(st.get("playCount") or 0),
                likes=int(st.get("diggCount") or 0),
                desc=str(v.get("desc") or ""),
            )
        )
    return out


def classify(body: dict, *, idempotent: bool) -> ActionResult:
    """Doc body cua mot hanh dong thanh ket qua. `idempotent` quyet dinh 'khong ro' la
    thu lai duoc hay phai cho nguoi."""
    code = body.get("status_code", body.get("statusCode"))
    msg = str(body.get("status_msg") or body.get("statusMsg") or "")
    if code == 0:
        return ActionResult(True, "ok", raw=body)
    text = (msg + " " + str(body)[:300]).lower()
    if code in _HUMAN_CODES or any(w in text for w in _HUMAN_WORDS):
        return ActionResult(
            False, f"TikTok wants a human: {code} {msg}".strip(), needs_human=True, raw=body
        )
    return ActionResult(
        False, f"TikTok refused: status_code={code} {msg}".strip(), retryable=idempotent, raw=body
    )


def _default_client(*, proxy: str | None, cookies: dict, headers: dict) -> httpx.AsyncClient:
    return httpx.AsyncClient(proxy=proxy, cookies=cookies, headers=headers, timeout=TIMEOUT)


class TikTokWeb:
    """Mot phien HTTP cua MOT tai khoan: proxy cua no, cookie cua no, UA cua signer.

    async with TikTokWeb(profile) as tt:
        items = await tt.feed()
        await tt.like(items[0].item_id)
    """

    def __init__(
        self,
        profile: Profile,
        *,
        signer: Signer | None = None,
        client_factory: ClientFactory = _default_client,
    ) -> None:
        if profile.proxy is None:
            raise ValueError("profile has no proxy - refusing to touch TikTok from the host IP")
        self.profile = profile
        self.signer = signer or Signer()
        self._factory = client_factory
        self.cookies = cookie_dict(profile.get_cookies())
        self.user_agent = ""
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> TikTokWeb:
        self.user_agent = await self.signer.user_agent()
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Referer": ORIGIN + "/",
            "Origin": ORIGIN,
        }
        self._client = self._factory(
            proxy=proxy_url(self.profile.proxy), cookies=self.cookies, headers=headers
        )
        await self._client.__aenter__()
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client is not None:
            await self._client.__aexit__(*exc)

    # ------------------------------------------------------------- ha tang

    async def _signed(self, path: str, extra: dict[str, str]) -> str:
        q = {**base_params(self.profile, self.cookies, self.user_agent), **extra}
        return (await self.signer.sign(f"{ORIGIN}{path}?{urlencode(q)}"))["signed_url"]

    async def _get(self, path: str, extra: dict[str, str]) -> dict:
        """GET co thu lai: doc thi lam lai bao nhieu lan cung khong de lai gi.

        200 rong la kieu tu choi cua TikTok khi chu ky/msToken lech - do that: lan dau
        sau khi signer khoi dong hay rong, lan hai la co. Ky lai URL moi lan thu.
        """
        assert self._client is not None
        last = "no response"
        for _ in range(READ_TRIES):
            url = await self._signed(path, extra)
            try:
                r = await self._client.get(url)
            except httpx.TransportError as exc:
                last = f"{type(exc).__name__}"
                continue
            if r.content:
                try:
                    return r.json()
                except ValueError:
                    last = f"non-JSON {r.status_code}: {r.text[:120]}"
                    continue
            last = f"empty {r.status_code}"
        raise RuntimeError(f"{path}: {last}")

    async def _post(self, path: str, extra: dict[str, str], *, idempotent: bool) -> ActionResult:
        """Mot hanh dong. Gui DUNG MOT lan; ket qua khong ro thi tuy `idempotent`."""
        assert self._client is not None
        url = await self._signed(path, extra)
        headers = {"tt-csrf-token": self.cookies.get("tt_csrf_token", "")}
        try:
            r = await self._client.post(url, headers=headers)
        except httpx.TransportError as exc:
            # Khong biet request co toi noi khong.
            return ActionResult(
                False,
                f"{type(exc).__name__} while posting to {path}",
                retryable=idempotent,
                needs_human=not idempotent,
            )
        if not r.content:
            return ActionResult(
                False,
                f"{path}: empty {r.status_code} response (signature or session rejected)",
                retryable=idempotent,
                needs_human=not idempotent,
            )
        try:
            body = r.json()
        except ValueError:
            return ActionResult(
                False, f"{path}: non-JSON {r.status_code}: {r.text[:120]}", retryable=idempotent
            )
        return classify(body, idempotent=idempotent)

    # ------------------------------------------------------------- doc

    async def feed(self, count: int = 12) -> list[FeedItem]:
        """For You cua tai khoan nay - nhin qua proxy cua no, nen la feed no THAT SU thay."""
        body = await self._get(
            "/api/recommend/item_list/", {"count": str(count), "from_page": "fyp"}
        )
        return parse_feed(body)

    async def user(self, handle: str, sec_uid: str = "") -> dict:
        """{'id', 'secUid', 'uniqueId', 'followers'} cua mot nguoi, de follow."""
        body = await self._get("/api/user/detail/", {"uniqueId": handle, "secUid": sec_uid})
        info = body.get("userInfo") or {}
        u = info.get("user") or {}
        return {
            "id": str(u.get("id") or ""),
            "secUid": str(u.get("secUid") or ""),
            "uniqueId": str(u.get("uniqueId") or handle),
            "followers": int((info.get("stats") or {}).get("followerCount") or 0),
        }

    # ------------------------------------------------------------- hanh dong

    async def like(self, item_id: str) -> ActionResult:
        res = await self._post(
            "/api/commit/item/digg/", {"aweme_id": item_id, "type": "1"}, idempotent=True
        )
        if res.ok and res.raw.get("is_digg") in (0, False):
            # status 0 nhung is_digg=0: TikTok nhan request ma khong tha tim. Coi la hong.
            return ActionResult(False, "TikTok accepted the request but is_digg=0", raw=res.raw)
        return res

    async def follow(self, user_id: str, sec_uid: str) -> ActionResult:
        return await self._post(
            "/api/commit/follow/user/",
            {
                "user_id": user_id,
                "sec_user_id": sec_uid,
                "type": "1",
                "action_type": "1",
                "channel_id": "3",
                "from": "18",
                "fromWeb": "1",
            },
            idempotent=True,
        )

    async def comment(self, item_id: str, text: str) -> ActionResult:
        return await self._post(
            "/api/comment/publish/",
            {"aweme_id": item_id, "text": text, "text_extra": "[]"},
            idempotent=False,
        )
