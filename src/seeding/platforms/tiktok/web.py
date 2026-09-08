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

from seeding.domain.models import Profile, Proxy
from seeding.platforms.tiktok.signer import Signer

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


def parse_search(body: dict) -> list[FeedItem]:
    """Body cua search/general/full: {"data": [{"type": 1, "item": {...video...}}, ...]}."""
    items = [
        d.get("item")
        for d in (body.get("data") or [])
        if isinstance(d, dict) and d.get("type") == 1 and isinstance(d.get("item"), dict)
    ]
    return parse_feed({"itemList": items})


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
        allow_direct: bool = False,
    ) -> None:
        if profile.proxy is None and not allow_direct:
            raise ValueError("profile has no proxy - refusing to touch TikTok from the host IP")
        self.profile = profile
        self.signer = signer or Signer()
        self._factory = client_factory
        self.cookies = cookie_dict(profile.get_cookies())
        self.user_agent = ""
        self._client: httpx.AsyncClient | None = None
        self._secsdk: str | None = None

    async def __aenter__(self) -> TikTokWeb:
        self.user_agent = await self.signer.user_agent()
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Referer": ORIGIN + "/",
            "Origin": ORIGIN,
        }
        self._client = self._factory(
            proxy=proxy_url(self.profile.proxy) if self.profile.proxy else None,
            cookies=self.cookies,
            headers=headers,
        )
        await self._client.__aenter__()
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client is not None:
            await self._client.__aexit__(*exc)

    # ------------------------------------------------------------- ha tang

    async def _signed(self, path: str, extra: dict[str, str], *, fresh_token: bool = False) -> str:
        """Ky URL. `fresh_token`: bo msToken cua tai khoan (da cu) de signer dien msToken
        cua phien trinh duyet no dang giu, va tu do dung token do cho ca cookie lan query.

        msToken TikTok cap cho trinh duyet song vai gio; cookie dan vao tu hom truoc
        thi token da chet, TikTok tra 200 rong cho moi request. Signer chay mot phien
        that voi webmssdk nen luon co token song - dung no thay vi doi nguoi dan lai."""
        q = {**base_params(self.profile, self.cookies, self.user_agent), **extra}
        if fresh_token:
            q.pop("msToken", None)
        data = await self.signer.sign(f"{ORIGIN}{path}?{urlencode(q)}")
        if fresh_token and data.get("msTokenUsed"):
            token = str(data["msTokenUsed"])
            self.cookies["msToken"] = token
            if self._client is not None:
                self._client.cookies.set("msToken", token, domain=".tiktok.com")
            log.info("tiktok_web.mstoken_refreshed", profile=str(self.profile.id))
        return data["signed_url"]

    def _adopt_mstoken(self, response) -> bool:
        """TikTok tra 200 rong + Set-Cookie msToken moi khi token cu het han: nhan token
        do cho ca cookie lan query, gui lai la duoc. Do that 08/09/2026 tren digg."""
        token = None
        for raw in response.headers.get_list("set-cookie"):
            if raw.startswith("msToken="):
                token = raw.split(";", 1)[0].split("=", 1)[1]
        if not token or self._client is None:
            return False
        self.cookies["msToken"] = token
        jar = self._client.cookies
        for c in list(jar.jar):
            if c.name == "msToken":
                jar.jar.clear(c.domain, c.path, c.name)
        jar.set("msToken", token, domain=".tiktok.com")
        log.info("tiktok_web.mstoken_rotated", profile=str(self.profile.id))
        return True

    async def _get(self, path: str, extra: dict[str, str]) -> dict:
        """GET co thu lai: doc thi lam lai bao nhieu lan cung khong de lai gi.

        200 rong la kieu tu choi cua TikTok khi chu ky/msToken lech. Lan dau ky voi
        msToken cua tai khoan; rong thi lan sau bo token do, lay token song cua signer.
        """
        assert self._client is not None
        last = "no response"
        # Thu tu do that 08/09/2026: token cua tai khoan (cu) -> rong; token cua phien
        # signer -> co; token TikTok vua cap trong Set-Cookie -> van rong voi doc. Nen
        # lan 2 dung token signer, lan 3 moi thu token Set-Cookie (neu co).
        adopted = False
        for attempt in range(READ_TRIES):
            use_signer_token = attempt == 1 or (attempt >= 2 and not adopted)
            url = await self._signed(path, extra, fresh_token=use_signer_token)
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
            if attempt == 1:
                adopted = self._adopt_mstoken(r)
        raise RuntimeError(f"{path}: {last}")

    async def _post(
        self,
        path: str,
        extra: dict[str, str],
        *,
        idempotent: bool,
        extra_headers: dict[str, str] | None = None,
    ) -> ActionResult:
        """Mot hanh dong. Gui DUNG MOT lan; ket qua khong ro thi tuy `idempotent`."""
        assert self._client is not None
        url = await self._signed(path, extra)
        # Endpoint ghi (tha tim, follow, binh luan, xoa) doi x-secsdk-csrf-token ngoai
        # tt-csrf-token. Lay mot lan cho ca phien; khong lay duoc thi van gui, de body
        # TikTok tra ve noi ro.
        if self._secsdk is None:
            self._secsdk = await self.secsdk_csrf()
        headers = {"tt-csrf-token": self.cookies.get("tt_csrf_token", "")}
        if self._secsdk:
            headers["x-secsdk-csrf-token"] = self._secsdk
        headers.update(extra_headers or {})
        for attempt in range(2):
            if attempt:
                url = await self._signed(path, extra)
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
            if r.content:
                break
            # 200 rong kem msToken moi = TikTok tu choi vi token cu, KHONG lam gi ca.
            # Nhan token moi, ky lai, gui lai dung mot lan.
            if attempt == 0 and self._adopt_mstoken(r):
                continue
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

    async def search(self, keyword: str, count: int = 12) -> list[FeedItem]:
        """Tim video theo tu khoa - cai trang tim kiem goi. Ket qua cung hinh voi feed."""
        body = await self._get(
            "/api/search/general/full/",
            {
                "keyword": keyword,
                "offset": "0",
                "search_source": "normal_search",
                "from_page": "search",
            },
        )
        return parse_search(body)[:count]

    async def item(self, item_id: str) -> dict:
        """Chi tiet mot video - cai trang video goi khi mo. Runner goi truoc khi "xem"."""
        return await self._get("/api/item/detail/", {"itemId": item_id})

    async def repost(self, item_id: str) -> ActionResult:
        """Dang lai (repost) mot video. Idempotent. CHUA kiem chung tren tai khoan that:
        endpoint theo nut Repost cua trang web; sai thi job hong voi body TikTok tra ve."""
        return await self._post(
            "/api/repost/item/", {"item_id": item_id, "action_type": "1"}, idempotent=True
        )

    async def posts(self, sec_uid: str, count: int = 10) -> list[FeedItem]:
        """Video cua mot nguoi (dung cho chinh minh: chatbot doc bai cua tai khoan)."""
        body = await self._get(
            "/api/post/item_list/", {"secUid": sec_uid, "count": str(count), "cursor": "0"}
        )
        return parse_feed(body)

    async def comments(self, item_id: str, count: int = 20) -> dict:
        """Binh luan duoi mot video, body tho: {"comments": [{cid, text, user, create_time,
        reply_comment}], ...}."""
        return await self._get(
            "/api/comment/list/", {"aweme_id": item_id, "count": str(count), "cursor": "0"}
        )

    async def reply(self, item_id: str, comment_id: str, text: str) -> ActionResult:
        """Tra loi mot binh luan. KHONG idempotent."""
        return await self._post(
            "/api/comment/publish/",
            {
                "aweme_id": item_id,
                "text": text,
                "text_extra": "[]",
                "reply_id": comment_id,
                "reply_to_reply_id": "0",
            },
            idempotent=False,
        )

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

    async def secsdk_csrf(self) -> str:
        """x-secsdk-csrf-token cho cac endpoint doi no (xoa video): mot HEAD toi
        passport/web/account/info voi x-secsdk-csrf-request=1, token nam trong
        x-ware-csrf-token dang "0,<token>,<ttl>,...". Khong lay duoc thi tra ve rong."""
        assert self._client is not None
        try:
            r = await self._client.head(
                f"{ORIGIN}/passport/web/account/info/",
                headers={"x-secsdk-csrf-request": "1", "x-secsdk-csrf-version": "1.2.8"},
            )
        except Exception:
            return ""
        parts = r.headers.get("x-ware-csrf-token", "").split(",")
        return parts[1] if len(parts) > 1 and parts[0] == "0" else ""

    async def delete_video(self, item_id: str) -> ActionResult:
        """Xoa mot video cua chinh tai khoan. Idempotent: xoa lan hai la da xoa roi."""
        token = await self.secsdk_csrf()
        return await self._post(
            "/api/aweme/delete/",
            {"aweme_id": item_id, "target": item_id},
            idempotent=True,
            extra_headers={"x-secsdk-csrf-token": token} if token else None,
        )

    async def comment(self, item_id: str, text: str) -> ActionResult:
        return await self._post(
            "/api/comment/publish/",
            {"aweme_id": item_id, "text": text, "text_extra": "[]"},
            idempotent=False,
        )
